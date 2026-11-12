import io
import json
import zipfile

import pymupdf
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.auto_alignment import page_rows


def upload(client, name):
    document = pymupdf.open()
    document.new_page(width=300, height=400).insert_text((30, 40), 'test')
    response = client.post('/api/books/upload', files={'file': (name, document.tobytes(), 'application/pdf')})
    document.close()
    assert response.status_code == 201, response.text
    book = response.json()
    page = client.get(f"/api/books/{book['id']}/pages").json()[0]
    return book, page


def box(box_id, text, x):
    return {'id': box_id, 'transcription': text,
            'points': [[x, 60], [x + 20, 60], [x + 20, 100], [x, 100]]}


def test_prepare_saves_pairs_and_ocr_boxes_without_overwriting_review(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        book, page = upload(client, 'first.pdf')
        response = client.patch(f"/api/pages/{page['id']}", json={
            'category': 'both', 'boxes': [box('han1', '天', 160), box('han2', '地', 100)],
            'vi_boxes': [box('vi1', 'trời', 20), box('vi2', 'đất', 50)],
            'reading_direction_override': 1,
        })
        assert response.status_code == 200, response.text
        waiting = client.post(f"/api/books/{book['id']}/alignments/prepare")
        assert waiting.status_code == 200 and waiting.json()['created'] == 0
        page = response.json()
        confirmed = client.put(f"/api/pages/{page['id']}", json={
            'version': page['version'], 'category': 'both', 'boxes': page['boxes'],
            'vi_boxes': page['vi_boxes'], 'reading_direction': 1,
            'ocr_granularity': 'character', 'done': True,
        })
        assert confirmed.status_code == 200, confirmed.text
        prepared = client.post(f"/api/books/{book['id']}/alignments/prepare")
        assert prepared.status_code == 200, prepared.text
        assert prepared.json()['created'] == 2
        assert prepared.json()['boxes_created'] == 2
        rows = prepared.json()['rows']
        assert [(row['source'], row['target']) for row in rows] == [('天', 'trời'), ('地', 'đất')]
        saved_page = client.get(f"/api/books/{book['id']}/pages").json()[0]
        assert [item['alignment_id'] for item in saved_page['export_boxes']] == [row['id'] for row in rows]
        rows[0]['target'] = 'bầu trời'
        rows[0]['reviewed'] = True
        assert client.put(f"/api/books/{book['id']}/alignments", json={'rows': rows}).status_code == 200
        second = client.post(f"/api/books/{book['id']}/alignments/prepare")
        assert second.status_code == 200, second.text
        assert second.json()['created'] == 0
        assert second.json()['boxes_created'] == 0
        assert second.json()['rows'][0]['target'] == 'bầu trời'
        assert second.json()['rows'][0]['reviewed'] is True


def test_phrase_ocr_requires_confirmation_and_keeps_its_box(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        book, page = upload(client, 'phrases.pdf')
        phrase = box('phrase', '天地', 100)
        patched = client.patch(f"/api/pages/{page['id']}", json={
            'category': 'both', 'boxes': [phrase], 'vi_boxes': [box('vi', 'trời đất', 20)],
        })
        assert patched.status_code == 200, patched.text
        page = patched.json()
        common = {'version': page['version'], 'category': 'both', 'boxes': page['boxes'],
                  'vi_boxes': page['vi_boxes'], 'done': True}
        assert client.put(f"/api/pages/{page['id']}", json=common).status_code == 422
        assert client.put(f"/api/pages/{page['id']}", json={**common,
               'ocr_granularity': 'character'}).status_code == 422
        confirmed = client.put(f"/api/pages/{page['id']}", json={**common,
               'ocr_granularity': 'phrase'})
        assert confirmed.status_code == 200, confirmed.text
        prepared = client.post(f"/api/books/{book['id']}/alignments/prepare")
        assert prepared.status_code == 200, prepared.text
        assert [(row['source'], row['target']) for row in prepared.json()['rows']] == [('天地', 'trời đất')]
        saved = client.get(f"/api/books/{book['id']}/pages").json()[0]
        assert saved['ocr_granularity'] == 'phrase'
        assert saved['export_boxes'][0]['points'] == phrase['points']


def test_phrase_boxes_in_one_column_become_separate_pairs(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        book, page = upload(client, 'same-column.pdf')
        first = box('first', '天地', 100)
        second = {**box('second', '玄黃', 100),
                  'points': [[100, 120], [120, 120], [120, 160], [100, 160]]}
        patched = client.patch(f"/api/pages/{page['id']}", json={
            'category': 'both', 'boxes': [first, second],
            'vi_boxes': [box('vi1', 'trời đất', 20), box('vi2', 'huyền hoàng', 50)],
            'reading_direction_override': 1,
        })
        assert patched.status_code == 200, patched.text
        page = patched.json()
        confirmed = client.put(f"/api/pages/{page['id']}", json={
            'version': page['version'], 'category': 'both', 'boxes': page['boxes'],
            'vi_boxes': page['vi_boxes'], 'ocr_granularity': 'phrase', 'done': True,
        })
        assert confirmed.status_code == 200, confirmed.text
        prepared = client.post(f"/api/books/{book['id']}/alignments/prepare")
        assert prepared.status_code == 200, prepared.text
        assert [(row['source'], row['target']) for row in prepared.json()['rows']] == [
            ('天地', 'trời đất'), ('玄黃', 'huyền hoàng')]
        saved = client.get(f"/api/books/{book['id']}/pages").json()[0]
        assert [item['points'] for item in saved['export_boxes']] == [first['points'], second['points']]


def test_prepare_rebuilds_only_untouched_legacy_phrase_pairs(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        book, page = upload(client, 'legacy-phrases.pdf')
        first = box('first', '天地', 100)
        second = {**box('second', '玄黃', 100),
                  'points': [[100, 120], [120, 120], [120, 160], [100, 160]]}
        patched = client.patch(f"/api/pages/{page['id']}", json={
            'category': 'both', 'boxes': [first, second],
            'vi_boxes': [box('vi1', 'trời đất', 20), box('vi2', 'huyền hoàng', 50)],
            'reading_direction_override': 1,
        }).json()
        assert client.put(f"/api/pages/{page['id']}", json={
            'version': patched['version'], 'category': 'both', 'boxes': patched['boxes'],
            'vi_boxes': patched['vi_boxes'], 'ocr_granularity': 'phrase', 'done': True,
        }).status_code == 200
        legacy = {'id': 'old', 'sentence_id': f"{book['name']}.001.1",
                  'source': '天地玄黃', 'target': 'trời đất', 'reviewed': False,
                  'source_page_id': page['id'], 'source_line_index': 0,
                  'target_page_id': page['id'], 'target_line_index': 0, 'marks': []}
        old_box = {'id': 'old-box', 'transcription': legacy['source'],
                   'points': [[100, 60], [120, 60], [120, 160], [100, 160]],
                   'alignment_id': 'old', 'box_axis': 'vertical', 'export_group': 'old-box',
                   'export_order': 1, 'export_character_order': 0}
        with app.state.store.db() as db:
            db.execute('INSERT INTO alignments VALUES (?,?)', (book['id'], json.dumps([legacy])))
            db.execute('UPDATE pages SET export_boxes=? WHERE id=?', (json.dumps([old_box]), page['id']))
        prepared = client.post(f"/api/books/{book['id']}/alignments/prepare")
        assert prepared.status_code == 200, prepared.text
        assert [(row['source'], row['target']) for row in prepared.json()['rows']] == [
            ('天地', 'trời đất'), ('玄黃', 'huyền hoàng')]
        assert 'old' not in [row['id'] for row in prepared.json()['rows']]
        saved = client.get(f"/api/books/{book['id']}/pages").json()[0]
        assert [item['points'] for item in saved['export_boxes']] == [first['points'], second['points']]


def test_prepare_removes_redundant_phrase_export_boxes(tmp_path):
    app = create_app(tmp_path)
    with TestClient(app) as client:
        book, page = upload(client, 'extra-boxes.pdf')
        first = box('first', '天地', 100)
        second = {**box('second', '玄黃', 100),
                  'points': [[100, 120], [120, 120], [120, 160], [100, 160]]}
        patched = client.patch(f"/api/pages/{page['id']}", json={
            'category': 'both', 'boxes': [first, second],
            'vi_boxes': [box('vi1', 'trời đất', 20), box('vi2', 'huyền hoàng', 50)],
            'reading_direction_override': 1,
        }).json()
        assert client.put(f"/api/pages/{page['id']}", json={
            'version': patched['version'], 'category': 'both', 'boxes': patched['boxes'],
            'vi_boxes': patched['vi_boxes'], 'ocr_granularity': 'phrase', 'done': True,
        }).status_code == 200
        assert client.post(f"/api/books/{book['id']}/alignments/prepare").status_code == 200
        saved = client.get(f"/api/books/{book['id']}/pages").json()[0]
        duplicates = []
        for index, source in enumerate((first, second), 1):
            duplicates.append({**source, 'id': f'extra-{index}', 'alignment_id': None,
                               'box_axis': 'vertical', 'export_group': f'extra-{index}',
                               'export_order': index + 2, 'export_character_order': 0})
        duplicates.append({'id': 'joined', 'transcription': '天地玄黃',
                           'points': [[100, 60], [120, 60], [120, 160], [100, 160]],
                           'box_axis': 'vertical', 'export_group': 'joined',
                           'export_order': 5, 'export_character_order': 0})
        with app.state.store.db() as db:
            db.execute('UPDATE pages SET export_boxes=? WHERE id=?',
                       (json.dumps(saved['export_boxes'] + duplicates), page['id']))
        repaired = client.post(f"/api/books/{book['id']}/alignments/prepare")
        assert repaired.status_code == 200, repaired.text
        assert repaired.json()['boxes_removed'] == 3
        saved = client.get(f"/api/books/{book['id']}/pages").json()[0]
        assert len(saved['export_boxes']) == 2
        assert all(box['alignment_id'] for box in saved['export_boxes'])


def test_archive_contains_results_from_every_book_before_completion(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        first, _ = upload(client, 'first.pdf')
        second, _ = upload(client, 'second.pdf')
        stale = tmp_path / 'backend' / 'data' / 'output_alignment' / first['id'] / f"{first['name']}.csv"
        stale.parent.mkdir(exist_ok=True)
        stale.write_text('old export', encoding='utf-8')
        response = client.get('/api/results/archive')
        assert response.status_code == 200, response.text
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            for book in (first, second):
                prefix = f"books/{book['name']}__{book['id']}/"
                assert prefix + 'summary.json' in names
                assert prefix + 'pages.json' in names
                assert prefix + f"{book['name']}_labels.zip" in names
            manifest = json.loads(archive.read('manifest.json'))
            assert len(manifest['books']) == 2
            assert len(manifest['omitted_exports']) == 4
            assert not any(name.endswith('/' + stale.name) for name in names)


def test_unequal_line_counts_leave_extra_source_line_separate():
    page = {'id': 'source', 'number': 1, 'source_text': '天\n地\n玄',
            'target_text': 'trời\nđất', 'linked_page_ids': [], 'ocr_skip': False,
            'ocr_languages': ['han', 'vi']}
    rows = page_rows(page, [page], 'book')
    assert [(row['source'], row['target']) for row in rows] == [
        ('天', 'trời'), ('地', 'đất'), ('玄', '')]
    assert [row['source_line_index'] for row in rows] == [0, 1, 2]
    assert all(not row['reviewed'] for row in rows)


def test_phrase_boxes_are_never_merged_when_target_has_fewer_lines():
    source = {'id': 'source', 'number': 46, 'source_text': '天地玄黃',
              'target_text': '', 'boxes': [box('a', '天地', 100), box('b', '玄黃', 100)],
              'reading_direction': 1, 'width': 300, 'height': 400,
              'ocr_granularity': 'phrase', 'linked_page_ids': ['target'],
              'ocr_skip': False, 'ocr_languages': ['han']}
    target = {'id': 'target', 'number': 47, 'target_text': 'trời đất',
              'ocr_skip': False, 'ocr_languages': ['vi']}
    rows = page_rows(source, [source, target], 'book')
    assert [(row['source'], row['target']) for row in rows] == [
        ('天地', 'trời đất'), ('玄黃', '')]
    assert [row['source_line_index'] for row in rows] == [0, 1]
    assert [row['target_page_id'] for row in rows] == ['target', None]
