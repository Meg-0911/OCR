import copy
import csv
import io
import json
import zipfile

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import create_app
from backend.alignment_review import export_text
from backend.export_labels import select_label_pages
from backend.alignment_merge import merge_rows
from backend.ocr import KHNConfig
from backend.tests.test_new_data import bundle, imported_page, raw_book


def box(identity, text, y):
    return {'id': identity, 'transcription': text,
            'points': [[10, y], [100, y], [100, y + 20], [10, y + 20]]}


def prepare(client, empty_target=False):
    book, = client.get('/api/workspace').json()['books']
    endpoint = f"/api/books/{book['id']}"
    page = client.get(endpoint + '/pages').json()[0]
    targets = ([box('empty', '', 80)] if empty_target else []) + [
        box('vi-a', 'thiên địa', 110), box('vi-b', 'huyền hoàng', 140)]
    response = client.patch(f"/api/pages/{page['id']}", json={
        'category': 'both', 'ocr_granularity': 'phrase',
        'boxes': [box('han-a', '天地', 10), box('han-b', '玄黃', 40)], 'vi_boxes': targets})
    assert response.status_code == 200, response.text
    return book, page, endpoint, client.post(endpoint + '/alignments/prepare').json()['rows']


def save(client, endpoint, rows, **extra):
    response = client.put(endpoint + '/alignments', json={'rows': rows, **extra})
    assert response.status_code == 200, response.text
    return response.json()


def test_empty_target_box_keeps_its_identity_when_editing_a_pair(tmp_path):
    raw_book(tmp_path, count=1)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, page, endpoint, rows = prepare(client, empty_target=True)
        assert rows[0]['target_line_index'] == 1
        assert rows[0]['target_refs'][0]['box_id'] == 'vi-a'
        rows[0]['target'] = 'thiên địa đã sửa'
        save(client, endpoint, rows)
        current = client.get(f"/api/pages/{page['id']}").json()
        assert [(b['id'], b['transcription']) for b in current['vi_boxes']] == [
            ('empty', ''), ('vi-a', 'thiên địa đã sửa'), ('vi-b', 'huyền hoàng')]


def test_confirmation_and_current_files_survive_ocr_edit(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        endpoint = f"/api/books/{book['id']}"
        rows = client.get(endpoint + '/alignments').json()
        rows[0]['reviewed'] = True
        save(client, endpoint, rows, input_revision=book['input_revision'])
        page = imported_page(client, book)
        response = client.patch(f"/api/pages/{page['id']}", json={
            'version': page['version'], 'input_revision': book['input_revision'],
            'target_text': '  THIÊN 123, ĐỊA!  \nhuyền hoàng'})
        assert response.status_code == 200, response.text
        current = client.get(endpoint + '/alignments').json()
        assert current[0]['reviewed'] and current[0]['id'] == rows[0]['id']
        output = tmp_path / 'backend/data/output_alignment' / book['id']
        with (output / 'Book_Y.csv').open(encoding='utf-8-sig', newline='') as stream:
            exported = list(csv.reader(stream))
        assert len(exported) == 2 and exported[1][3] == 'thiên địa'
        workbook = load_workbook(output / 'Book_Y.xlsx', rich_text=True)
        assert str(workbook.active['D2'].value) == exported[1][3]
        workbook.close()
        assert not (output / 'events.jsonl').exists()


def test_new_input_never_replaces_edited_pairs_or_removed_source_rows(tmp_path):
    source = bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        endpoint = f"/api/books/{book['id']}"
        rows = client.get(endpoint + '/alignments').json()
        rows[0].update(target='bản đã sửa', reviewed=True)
        saved = save(client, endpoint, rows, input_revision=book['input_revision'])
        bundle(tmp_path, records=[(0, '宇宙', 'bản nguồn thay đổi', '11')])
        workspace = client.post('/api/sources/sync').json()
        assert workspace['books'][0]['input_revision'] == book['input_revision']
        assert client.get(endpoint + '/alignments').json() == saved
        source.unlink()
        client.post('/api/sources/sync')
        assert client.get(endpoint + '/alignments').json() == saved


def test_concurrent_independent_edits_merge_but_same_field_conflicts(tmp_path):
    raw_book(tmp_path, count=1)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        _, _, endpoint, base = prepare(client)
        first, second = copy.deepcopy(base), copy.deepcopy(base)
        first[0]['source'] = '天地人'
        save(client, endpoint, first, base_rows=base)
        second[1]['target'] = 'huyền hoàng mới'
        combined = save(client, endpoint, second, base_rows=base)
        assert combined[0]['source'] == '天地人'
        assert combined[1]['target'] == 'huyền hoàng mới'
        stale = copy.deepcopy(base)
        stale[0]['source'] = '玄'
        response = client.put(endpoint + '/alignments', json={'rows': stale, 'base_rows': base})
        assert response.status_code == 409
        assert client.get(endpoint + '/alignments').json()[0]['source'] == '天地人'


def test_split_ranges_preserve_full_ocr_and_block_missing_source_geometry(tmp_path):
    raw_book(tmp_path, count=1)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        _, page, endpoint, rows = prepare(client)
        first = rows[0]
        # Both halves refer to the same real OCR line, with disjoint ranges.
        split = {**first, 'id': 'new-half', 'sentence_id': 'Book_Y.001.3',
                 'source': '地', 'target': 'địa', 'source_line_index': None,
                 'source_refs': [{'box_id': 'han-a', 'start': 1, 'end': 2}],
                 'target_refs': [{'box_id': 'vi-a', 'start': 6, 'end': 9}]}
        first.update(source='天', target='thiên',
                     source_refs=[{'box_id': 'han-a', 'start': 0, 'end': 1}],
                     target_refs=[{'box_id': 'vi-a', 'start': 0, 'end': 5}])
        rows.insert(1, split)
        for row in rows:
            row['reviewed'] = True
        saved = save(client, endpoint, rows)
        current = client.get(f"/api/pages/{page['id']}").json()
        assert current['boxes'][0]['transcription'] == '天地'
        assert current['vi_boxes'][0]['transcription'] == 'thiên địa'
        response = client.get('/api/results/archive')
        assert response.status_code == 422 and 'Book_Y.001.3' in response.text
        saved[1]['target'] = 'đất'
        save(client, endpoint, saved)
        current = client.get(f"/api/pages/{page['id']}").json()
        assert current['vi_boxes'][0]['transcription'] == 'thiên đất'


def test_new_zip_contains_pdf_and_no_synthetic_vietnamese_labels(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        endpoint = f"/api/books/{book['id']}"
        rows = client.get(endpoint + '/alignments').json()
        rows[0]['reviewed'] = True
        save(client, endpoint, rows, input_revision=book['input_revision'])
        response = client.get('/api/results/archive')
        assert response.status_code == 200, response.text
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            names = archive.namelist()
            assert len(names) == len(set(names))
            assert 'Book_Y/Book_Y.pdf' in names
            assert 'Book_Y/Book_Y.csv' in names and 'Book_Y/Book_Y.xlsx' in names
            assert not any(name.startswith('Book_Y/vi/') for name in names)
            assert [name for name in names if name.startswith('Book_Y/ch/') and name.endswith('.jpg')] == ['Book_Y/ch/Book_Y.003.jpg']
            assert 'manifest.json' not in names
            states = archive.read('Book_Y/ch/fileState.txt').decode()
            assert 'Book_Y.003.jpg\t0' in states
            assert len(states.splitlines()) == 1
            labels = archive.read('Book_Y/ch/Label.txt').decode()
            page_line = next(line for line in labels.splitlines() if '.003.jpg\t' in line)
            assert len(json.loads(page_line.split('\t')[1])) == 1


def test_cleanup_preserves_color_offsets_and_removes_all_numbers():
    text, colors = export_text('  12 THIÊN,   ٣ ĐỊA!  ', 'target', ['mismatch'] * 23)
    assert text == 'thiên địa'
    assert len(text) == len(colors)
    assert all(color == 'mismatch' for char, color in zip(text, colors) if char.isalpha())


def test_partial_phrase_edit_only_invalidates_changed_glyphs():
    from backend.alignment_links import replace_ranges
    original = {'id': 'phrase', 'transcription': '𠰺迻法宝即候師兄', 'review_kind': 'match',
                'review_marks': [{'start': 1, 'end': 2, 'kind': 'mismatch'}]}
    refs = [{'box_id': 'phrase', 'start': 0, 'end': 8}]
    boxes, _ = replace_ranges([original], [(refs, original['transcription'], '𠰺迻法宝郎候師兄')])
    def colors(box):
        result = [box.get('review_kind', 'match')] * len(box['transcription'])
        for mark in box['review_marks']:
            result[mark['start']:mark['end']] = [mark['kind']] * (mark['end'] - mark['start'])
        return result
    assert colors(boxes[0]) == ['match', 'mismatch', 'match', 'match', 'unknown', 'match', 'match', 'match']
    assert original['transcription'] == '𠰺迻法宝即候師兄'
    partial = [{'box_id': 'phrase', 'start': 4, 'end': 5}]
    inserted, _ = replace_ranges(boxes, [(partial, '郎', '𠬠𠇮')])
    assert colors(inserted[0]) == ['match', 'mismatch', 'match', 'match', 'unknown', 'unknown', 'match', 'match', 'match']


def test_imported_source_edits_advance_refs_and_preserve_split_ocr(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        endpoint = f"/api/books/{book['id']}"
        rows = client.get(endpoint + '/alignments').json()
        rows[0].update(source='天地人', reviewed=True)
        rows = save(client, endpoint, rows, input_revision=book['input_revision'])
        assert rows[0]['source_refs'][0]['end'] == 3
        original = copy.deepcopy(rows[0])
        rows[0].update(source='天', target='thiên',
                       source_refs=[{**original['source_refs'][0], 'end': 1}])
        rows.insert(1, {**original, 'id': 'split-import', 'sentence_id': 'Book_Y.003.3',
                        'source': '地人', 'target': 'địa nhân', 'source_line_index': None,
                        'source_refs': [{**original['source_refs'][0], 'start': 1}]})
        rows = save(client, endpoint, rows, input_revision=book['input_revision'])
        assert imported_page(client, book)['boxes'][0]['transcription'] == '天地人'
        rows[1]['source'] = '地人人'
        rows = save(client, endpoint, rows, input_revision=book['input_revision'])
        assert imported_page(client, book)['boxes'][0]['transcription'] == '天地人人'
        assert rows[0]['reviewed'] and rows[1]['source_refs'][0]['end'] == 4


def test_zip_retains_real_vietnamese_geometry_and_current_text(tmp_path):
    raw_book(tmp_path, count=1)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        _, _, endpoint, rows = prepare(client)
        for row in rows:
            row['reviewed'] = True
        rows[0]['target'] = 'THIÊN, 123 ĐỊA!'
        save(client, endpoint, rows)
        response = client.get('/api/results/archive')
        assert response.status_code == 200, response.text
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            records = list(csv.reader(io.StringIO(archive.read('Book_Y/Book_Y.csv').decode('utf-8-sig'))))
            assert records[1][3] == 'thiên địa'
            line, = archive.read('Book_Y/vi/Label.txt').decode().splitlines()
            labels = json.loads(line.split('\t')[1])
            assert [item['transcription'] for item in labels] == ['thiên địa', 'huyền hoàng']
            assert labels[0]['points'] == box('vi-a', '', 110)['points']
            assert 'Book_Y/vi/Book_Y.001.jpg' in archive.namelist()


def test_invalid_box_reference_is_rejected_without_changing_saved_rows(tmp_path):
    raw_book(tmp_path, count=1)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        _, _, endpoint, rows = prepare(client)
        original = copy.deepcopy(rows)
        rows[0]['target_refs'][0]['box_id'] = 'vi-b'
        response = client.put(endpoint + '/alignments', json={'rows': rows})
        assert response.status_code == 422
        assert client.get(endpoint + '/alignments').json() == original


def test_queued_save_preserves_fields_merged_from_another_editor(tmp_path):
    raw_book(tmp_path, count=1)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        _, _, endpoint, base = prepare(client)
        remote = copy.deepcopy(base)
        remote[0].update(target='thiên địa đã sửa', reviewed=True)
        save(client, endpoint, remote, base_rows=base)
        first = copy.deepcopy(base)
        first[0]['source'] = '天地人'
        merged = save(client, endpoint, first, base_rows=base)
        queued = copy.deepcopy(first)
        queued[0]['source'] = '天地人人'
        latest = save(client, endpoint, queued, base_rows=first,
                      alignment_version=merged[0]['alignment_version'])
        assert latest[0]['source'] == '天地人人'
        assert latest[0]['target'] == 'thiên địa đã sửa'
        assert latest[0]['reviewed']


def test_zip_rejects_two_pairs_using_the_same_vietnamese_range(tmp_path):
    raw_book(tmp_path, count=1)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        _, _, endpoint, rows = prepare(client)
        rows[1].update(target=rows[0]['target'], target_refs=rows[0]['target_refs'],
                       target_line_index=rows[0]['target_line_index'])
        for row in rows:
            row['reviewed'] = True
        save(client, endpoint, rows)
        response = client.get('/api/results/archive')
        assert response.status_code == 422
        assert 'Book_Y.001.2' in response.text


def test_unlinked_ocr_prevents_complete_file_state():
    source = box('ocr', '天地', 10)
    extra = box('unlinked', '人', 40)
    page = {'id': 'page', 'number': 1, 'category': 'ch', 'ocr_languages': ['han'],
            'boxes': [source, extra], 'vi_boxes': [],
            'export_boxes': [{**source, 'alignment_id': 'pair'}]}
    row = {'id': 'pair', 'sentence_id': 'Book.001.1', 'source_page_id': 'page',
           'source': '天地', 'target': 'thiên địa'}
    assert not select_label_pages([page], [row])[0]['export_complete']
    page['boxes'] = [source]
    assert select_label_pages([page], [row])[0]['export_complete']


def test_concurrent_merge_can_clear_optional_links():
    base = {'id': 'pair', 'sentence_id': 'Book.001.1', 'source': '天', 'target_page_id': 'vi'}
    incoming = {key: value for key, value in base.items() if key != 'target_page_id'}
    remote = {**base, 'source': '天地'}
    merged, = merge_rows([base], [incoming], [remote])
    assert merged['source'] == '天地' and 'target_page_id' not in merged
