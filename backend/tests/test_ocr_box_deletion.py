import json

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ocr import KHNConfig
from backend.tests.test_new_data import bundle, imported_page, raw_book


def setup_page(client, imported=False):
    book, = client.get('/api/workspace').json()['books']
    if imported:
        page = imported_page(client, book)
    else:
        page, = client.get(f"/api/books/{book['id']}/pages").json()
        boxes = [{'id': f'box-{i}', 'transcription': text,
                  'points': [[10,y],[90,y],[90,y+25],[10,y+25]]}
                 for i, (text, y) in enumerate([('天地',10),('玄黃',70),('宇宙',130)])]
        vi = [{**box, 'id': 'vi-'+box['id'], 'transcription': text}
              for box, text in zip(boxes, ['trời đất', 'huyền hoàng', 'vũ trụ'])]
        response = client.patch(f"/api/pages/{page['id']}", json={
            'category': 'both', 'boxes': boxes, 'vi_boxes': vi, 'ocr_granularity': 'phrase'})
        assert response.status_code == 200, response.text
    prepared = client.post(f"/api/books/{book['id']}/alignments/prepare")
    assert prepared.status_code == 200, prepared.text
    return book, client.get(f"/api/pages/{page['id']}").json(), prepared.json()['rows']


@pytest.mark.parametrize('imported', [False, True])
@pytest.mark.parametrize('method', ['patch', 'put'])
@pytest.mark.parametrize('delete', ['first', 'middle', 'last', 'all'])
def test_deleted_ocr_groups_remove_pairs_and_export_boxes_without_shifting_targets(tmp_path, imported, method, delete):
    bundle(tmp_path) if imported else raw_book(tmp_path, count=1)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, page, original = setup_page(client, imported)
        deleted_index = 0 if delete == 'first' else len(page['boxes'])//2 if delete == 'middle' else len(page['boxes'])-1
        keep = [] if delete == 'all' else [box for index, box in enumerate(page['boxes']) if index != deleted_index]
        keep = [{**box, **({'review_order': index+1} if 'review_order' in box else {})} for index, box in enumerate(keep)]
        payload = {'boxes': keep, 'version': page['version'], 'input_revision': book['input_revision']}
        if method == 'put':
            payload.update(category=page['category'], done=False, ocr_granularity='phrase')
        saved = getattr(client, method)(f"/api/pages/{page['id']}", json=payload)
        assert saved.status_code == 200, saved.text
        expected = [] if delete == 'all' else [row for index, row in enumerate(original) if index != deleted_index]
        endpoint = f"/api/books/{book['id']}"
        for _ in range(2):
            response = client.post(endpoint+'/alignments/prepare')
            rows = response.json()['rows']
            assert [(r['id'],r['source'],r['target']) for r in rows] == [(r['id'],r['source'],r['target']) for r in expected]
            assert [r['source_line_index'] for r in rows] == list(range(len(expected)))
            current = client.get(f"/api/pages/{page['id']}").json()
            assert len(current['boxes']) == len(keep)
            assert {box['alignment_id'] for box in current['export_boxes']} == {r['id'] for r in expected}
        reviewed = [{**row, 'reviewed': True} for row in rows]
        confirmed = client.put(endpoint+'/alignments', json={'rows': reviewed, 'input_revision': book['input_revision']})
        assert confirmed.status_code == 200, confirmed.text
        assert all(row['reviewed'] for row in confirmed.json())
        assert current['source_text'] == '\n'.join(row['source'] for row in expected)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as reopened:
        assert [r['id'] for r in reopened.get(endpoint+'/alignments').json()] == [r['id'] for r in expected]


@pytest.mark.parametrize('imported', [False, True])
def test_opening_alignment_repairs_a_previously_saved_box_deletion(tmp_path, imported):
    bundle(tmp_path) if imported else raw_book(tmp_path, count=1)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, page, original = setup_page(client, imported)
        keep = page['boxes'][:-1]
        with app.state.store.db() as db:
            db.execute("UPDATE pages SET boxes=?,source_text=?,edited_fields='[\"boxes\",\"source_text\"]',version=version+1 WHERE id=?",
                       (json.dumps(keep, ensure_ascii=False), '\n'.join(box['transcription'] for box in keep), page['id']))
        rows = client.get(f"/api/books/{book['id']}/alignments").json()
        assert [row['id'] for row in rows] == [row['id'] for row in original[:-1]]
        current = client.get(f"/api/pages/{page['id']}").json()
        assert len(current['export_boxes']) == len(keep)


def test_deleting_one_character_keeps_pair_and_shrinks_its_alignment_box(tmp_path):
    raw_book(tmp_path, count=1)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, page, _ = setup_page(client)
        boxes = [{'id': f'char-{i}', 'transcription': char,
                  'points': [[10+i*30,10],[30+i*30,10],[30+i*30,40],[10+i*30,40]]}
                 for i, char in enumerate('天地')]
        # Reset the fixture to one character-level pair before testing deletion.
        with app.state.store.db() as db:
            db.execute('DELETE FROM alignments WHERE book_id=?', (book['id'],))
            db.execute("UPDATE pages SET boxes=?,source_text='天地',target_text='trời đất',export_boxes='[]',ocr_granularity='character',version=version+1 WHERE id=?",
                       (json.dumps(boxes), page['id']))
        row, = client.post(f"/api/books/{book['id']}/alignments/prepare").json()['rows']
        saved = client.patch(f"/api/pages/{page['id']}", json={'boxes': boxes[:1]})
        assert saved.status_code == 200, saved.text
        current, = client.get(f"/api/books/{book['id']}/alignments").json()
        assert current['id'] == row['id'] and current['source'] == '天' and current['target'] == 'trời đất'
        assert saved.json()['export_boxes'][0]['points'] == boxes[0]['points']


def test_legacy_empty_surplus_pair_is_removed_even_when_its_old_frame_overlaps_live_ocr(tmp_path):
    raw_book(tmp_path, count=1)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, page, original = setup_page(client)
        rows = [*original[:-1], {**original[-1], 'source': '', 'target': ''}]
        exports = [*page['export_boxes'][:-1], {**page['export_boxes'][-1],
                   'transcription': '', 'points': [[0,0],[200,0],[200,200],[0,200]]}]
        with app.state.store.db() as db:
            db.execute('UPDATE alignments SET rows=? WHERE book_id=?', (json.dumps(rows), book['id']))
            db.execute("UPDATE pages SET boxes=?,export_boxes=?,edited_fields='[\"boxes\"]',version=version+1 WHERE id=?",
                       (json.dumps(page['boxes'][:-1]),json.dumps(exports),page['id']))
        current = client.post(f"/api/books/{book['id']}/alignments/prepare").json()['rows']
        assert [r['id'] for r in current] == [r['id'] for r in original[:-1]]
        assert len(client.get(f"/api/pages/{page['id']}").json()['export_boxes']) == 2


def test_ocr_deletion_keeps_manually_added_pair_and_its_box(tmp_path):
    raw_book(tmp_path, count=1)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, page, original = setup_page(client)
        manual = {'id': 'manual', 'sentence_id': 'Book_Y.001.4', 'source': '手寫', 'target': 'viết tay', 'reviewed': True}
        manual_box = {**page['export_boxes'][-1], 'id': 'manual-box', 'alignment_id': 'manual',
                      'export_group': 'manual-box', 'export_order': 4, 'transcription': '手寫'}
        with app.state.store.db() as db:
            db.execute('UPDATE alignments SET rows=? WHERE book_id=?', (json.dumps([*original,manual]),book['id']))
            db.execute('UPDATE pages SET export_boxes=? WHERE id=?', (json.dumps([*page['export_boxes'],manual_box]),page['id']))
        response = client.patch(f"/api/pages/{page['id']}", json={'boxes': page['boxes'][:-1]})
        assert response.status_code == 200, response.text
        current = client.post(f"/api/books/{book['id']}/alignments/prepare").json()['rows']
        assert [r['id'] for r in current] == [original[0]['id'],original[1]['id'],'manual']
        assert next(r for r in current if r['id']=='manual')['reviewed'] is True


@pytest.mark.parametrize('manual_order', [False, True])
def test_prepare_removes_unboxed_stale_phrase_and_repairs_only_default_targets(tmp_path, manual_order):
    raw_book(tmp_path, count=1)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, page, original = setup_page(client)
        orphan = {**original[1], 'id': 'obsolete-ocr', 'source': '舊文'}
        rows = [dict(original[0]), orphan, dict(original[1]), dict(original[2])]
        for index, row in enumerate(rows):
            row['source_line_index'] = index
            row['sentence_id'] = f"{book['name']}.001.{index+1}"
            target = original[index] if index < len(original) else {}
            row.update(target=target.get('target', ''), target_page_id=target.get('target_page_id'),
                       target_line_index=target.get('target_line_index'))
        if manual_order:
            rows[0]['target'], rows[1]['target'] = rows[1]['target'], rows[0]['target']
            rows[0]['target_line_index'], rows[1]['target_line_index'] = rows[1]['target_line_index'], rows[0]['target_line_index']
        with app.state.store.db() as db:
            db.execute('UPDATE alignments SET rows=? WHERE book_id=?', (json.dumps(rows), book['id']))
        endpoint = f"/api/books/{book['id']}/alignments"
        for _ in range(2):
            response = client.post(endpoint+'/prepare')
            assert response.status_code == 200, response.text
            current = response.json()['rows']
            assert [r['id'] for r in current] == [r['id'] for r in original]
            assert [r['source_line_index'] for r in current] == [0, 1, 2]
            expected = [rows[i]['target'] for i in (0, 2, 3)] if manual_order else [r['target'] for r in original]
            assert [r['target'] for r in current] == expected
            assert client.get(endpoint).json() == current
