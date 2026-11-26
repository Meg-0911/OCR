import io
import json
import zipfile
from pathlib import Path

import pymupdf
import pytest
from fastapi.testclient import TestClient
from openpyxl import Workbook, load_workbook
from PIL import Image

from backend.app import create_app
from backend.new_data import correctness_bits
from backend.ocr import KHNConfig
from backend.store import Store


def raw_book(root, filename='Book_Y.pdf', count=5):
    raw = root / 'backend/data/raw_data'
    raw.mkdir(parents=True, exist_ok=True)
    path = raw / filename
    if not path.exists():
        with pymupdf.open() as document:
            for _ in range(count):
                document.new_page(width=200, height=300)
            document.save(path)
    return path


def bundle(root, name='Book', page=3, records=None, labels_in_images=False, mandatory=True):
    if mandatory:
        raw_book(root, name + '_Y.pdf')
    folder = root / 'backend/data/new'
    images = folder / name / 'images'
    images.mkdir(parents=True, exist_ok=True)
    image_name = f'{name}.{page:03d}.jpg'
    Image.new('RGB', (240, 200), 'white').save(images / image_name)
    labels = [{'transcription': '', 'points': [[10, y], [110, y], [110, y + 30], [10, y + 30]]}
              for y in (10, 80)]
    destination = images if labels_in_images else images.parent
    label_path = destination / 'Label.txt'
    old = label_path.read_text(encoding='utf-8') if label_path.exists() else ''
    old = '\n'.join(line for line in old.splitlines() if not line.startswith('images/' + image_name + '\t'))
    label_path.write_text((old+'\n' if old else '')+'images/'+image_name+'\t'+json.dumps(labels)+'\n', encoding='utf-8')
    # This deliberately wrong character prediction must not replace voted phrase text.
    (destination / 'char_det.txt').write_text('images/'+image_name+'\t'+json.dumps([
        {'labels': ['錯'], 'scores': [0.99], 'points': [[12,12],[47,12],[47,37],[12,37]]}])+'\n', encoding='utf-8')
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(['Extra', 'Correctness', 'Label', 'Patch ID', 'Vietnamese'])
    for line, source, target, bits in records if records is not None else [(0, '𡗶地', 'thiên địa', 1), (1, '玄黃', 'huyền hoàng', 11)]:
        sheet.append(['unused', bits, source, f'{name}.{page:03d}.{line:03d}', target])
    alignment = folder / 'Alignment'
    alignment.mkdir(exist_ok=True)
    path = alignment / f'{name}.{page}.xlsx'
    workbook.save(path)
    return path


def imported_page(client, book, number=3):
    return next(page for page in client.get(f"/api/books/{book['id']}/pages").json() if page['number'] == number)


@pytest.mark.parametrize('labels_in_images', [False, True])
def test_matching_mandatory_book_uses_phrase_boxes_and_consistent_exports(tmp_path, labels_in_images):
    bundle(tmp_path, labels_in_images=labels_in_images)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        workspace = client.get('/api/workspace').json()
        assert workspace['source_errors'] == []
        book, = workspace['books']
        assert book['has_new_data'] and book['has_pdf'] and book['input_revision']
        assert (book['pages'], book['new_data_pages'], book['new_data_lines']) == (5, 1, 2)
        assert workspace['pair_stats']['pairs'] == 0 and workspace['pair_stats']['reviewed_pairs'] == 0
        assert workspace['pair_stats']['pending_error_pairs'] == 2 and book['done'] == 0
        page = imported_page(client, book)
        assert page['ocr_granularity'] == 'phrase'
        assert page['status'] == 'pending' and page['review_state'] == 'unchecked'
        assert [box['transcription'] for box in page['boxes']] == ['𡗶地', '玄黃']
        assert [mark['kind'] for mark in page['boxes'][0]['review_marks']] == ['mismatch', 'match']
        assert client.get(page['image_url']).status_code == 200
        rows = client.get(f"/api/books/{book['id']}/alignments").json()
        assert [row['sentence_id'] for row in rows] == ['Book_Y.003.1', 'Book_Y.003.2']
        assert all(row['marks'] == [] for row in rows)
        assert [box['alignment_id'] for box in page['export_boxes']] == [row['id'] for row in rows]
        for side, value in (('C2', '𡗶地'), ('D2', 'thiên địa')):
            response = client.get(f"/api/books/{book['id']}/export?format=xlsx")
            workbook = load_workbook(io.BytesIO(response.content), rich_text=True)
            assert str(workbook.active[side].value) == value
            assert [block.font.color.rgb for block in workbook.active[side].value] == ['FFCC0000', 'FF000000']
            workbook.close()
        labels = client.get(f"/api/books/{book['id']}/export?format=labels")
        with zipfile.ZipFile(io.BytesIO(labels.content)) as archive:
            output = json.loads(archive.read('Book_Y/ch/Label.txt').decode().split('\t')[1])
            assert [box['transcription'] for box in output] == ['𡗶地', '玄黃']
            assert len([name for name in archive.namelist() if name.endswith('.jpg')]) == 5
        summary = client.get(f"/api/books/{book['id']}/results/summary.json").json()
        assert summary['pairs'] == 0 and summary['ocr_pages'] == 1
        assert summary['similarity_review'] == {'total': 4, 'red': 1, 'unmarked': 0, 'percent': 75.0}
        assert client.get(f"/api/pages/{page['id']}/ocr").json()['text_lines'] == ['𡗶地', '玄黃']
        assert client.post(f"/api/books/{book['id']}/alignments/prepare").json()['created'] == 0


def test_unmatched_new_books_are_ignored_and_original_files_remain_untouched(tmp_path):
    raw_book(tmp_path)
    path = bundle(tmp_path, name='Outside', mandatory=False)
    before = {file: file.read_bytes() for file in path.parents[1].rglob('*') if file.is_file()}
    (path.parent / 'Other.xlsx').write_bytes(b'not a workbook and not an eligible book')
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        workspace = client.get('/api/workspace').json()
        assert workspace['source_errors'] == []
        book, = workspace['books']
        assert book['filename'] == 'Book_Y.pdf' and not book['has_new_data']
        assert workspace['pair_stats']['pairs'] == 0
        assert all(file.read_bytes() == contents for file, contents in before.items())


def test_new_without_any_mandatory_pdf_never_becomes_a_book(tmp_path):
    bundle(tmp_path, mandatory=False)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        assert client.get('/api/workspace').json()['books'] == []
        raw_book(tmp_path)
        workspace = client.post('/api/sources/sync').json()
        assert len(workspace['books']) == 1 and workspace['books'][0]['has_new_data']


def test_new_input_preserves_existing_work_references_and_layout(tmp_path):
    raw_book(tmp_path)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, = client.get('/api/workspace').json()['books']
        endpoint = f"/api/books/{book['id']}"
        pages = client.get(endpoint+'/pages').json()
        page = pages[0]
        client.patch(f"/api/pages/{page['id']}", json={'source_text': '舊', 'target_text': 'cũ'})
        old = [{'id': 'old', 'sentence_id': 'Book_Y.001.1', 'source': '舊', 'target': 'cũ', 'reviewed': True,
                'source_page_id': page['id']}]
        assert client.put(endpoint+'/alignments', json={'rows': old}).status_code == 200
        client.put(endpoint+'/text-sources/vi', json={'filename': 'old.txt', 'text': 'tham chiếu cũ'})
        client.put(endpoint+'/layout', json={'reading_direction': 1, 'source_regions': [[0,0,.5,.5]]})
        before = client.get(f"/api/pages/{page['id']}").json()
        bundle(tmp_path)
        workspace = client.post('/api/sources/sync').json()
        assert workspace['source_errors'] == []
        rows = client.get(endpoint+'/alignments').json()
        assert rows[0]['id'] == 'old' and rows[0]['reviewed'] and rows[0]['target'] == 'cũ'
        assert len(rows) == 3
        assert client.get(f"/api/pages/{page['id']}").json()['version'] == before['version']
        assert client.get(endpoint+'/text-sources').json()['vi']['text'] == 'tham chiếu cũ'
        assert client.get(endpoint+'/layout').json()['source_regions'] == [[0,0,.5,.5]]


def test_reimport_preserves_edits_and_adds_only_untouched_pages(tmp_path):
    path = bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        endpoint = f"/api/books/{book['id']}/alignments"
        rows = client.get(endpoint).json()
        rows[0]['target'] = 'đã sửa'
        assert client.put(endpoint, json={'rows': rows, 'input_revision': book['input_revision']}).status_code == 200
        assert client.post('/api/sources/sync').json()['books'][0]['input_revision'] == book['input_revision']
        assert client.get(endpoint).json()[0]['target'] == 'đã sửa'
        bundle(tmp_path, page=4, records=[(0, '宇宙', 'vũ trụ', '11')])
        fresh = client.post('/api/sources/sync').json()['books'][0]
        assert fresh['input_revision'] == book['input_revision']
        assert [row['target'] for row in client.get(endpoint).json()] == ['đã sửa', 'huyền hoàng', 'vũ trụ']
        assert client.put(endpoint, json={'rows': client.get(endpoint).json(), 'input_revision': 'obsolete-revision'}).status_code == 409
        path.unlink()  # Removing a supplied file does not delete saved editing work.
        latest = client.post('/api/sources/sync').json()['books'][0]
        assert latest['new_data_lines'] == 3
        assert [row['target'] for row in client.get(endpoint).json()] == ['đã sửa', 'huyền hoàng', 'vũ trụ']
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as restarted:
        assert restarted.get('/api/workspace').json()['pair_stats']['saved_pairs'] == 3


def test_incomplete_delivery_does_not_partly_replace_a_book(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        before = client.get('/api/workspace').json()['books'][0]
        rows = client.get(f"/api/books/{before['id']}/alignments").json()
        path = bundle(tmp_path, page=4)
        (path.parents[1] / 'Book/images/Book.004.jpg').unlink()
        workspace = client.post('/api/sources/sync').json()
        assert workspace['source_errors'] and workspace['books'][0]['input_revision'] == before['input_revision']
        assert client.get(f"/api/books/{before['id']}/alignments").json() == rows


def test_phrase_edits_synchronize_page_pairs_colors_and_xlsx(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        endpoint = f"/api/books/{book['id']}"
        page = imported_page(client, book)
        page['boxes'][0]['review_marks'] = [{'start': 1, 'end': 2, 'kind': 'mismatch'}]
        page['boxes'][0]['review_kind'] = 'match'
        response = client.patch(f"/api/pages/{page['id']}", json={'boxes': page['boxes'], 'ocr_granularity': 'character', 'input_revision': book['input_revision']})
        assert response.json()['ocr_granularity'] == 'phrase'
        xlsx = load_workbook(io.BytesIO(client.get(endpoint+'/export?format=xlsx').content), rich_text=True)
        assert [block.font.color.rgb for block in xlsx.active['C2'].value] == ['FF000000', 'FFCC0000']
        assert [block.font.color.rgb for block in xlsx.active['D2'].value] == ['FF000000', 'FFCC0000']
        rows = client.get(endpoint+'/alignments').json()
        rows[0]['source'] = '天地'
        rows[0]['target'] = 'bầu trời'
        assert client.put(endpoint+'/alignments', json={'rows': rows, 'input_revision': book['input_revision']}).status_code == 200
        page = imported_page(client, book)
        assert page['source_text'].startswith('天地\n') and page['target_text'].startswith('bầu trời\n')
        assert page['boxes'][0]['transcription'] == page['export_boxes'][0]['transcription'] == '天地'
        assert (tmp_path / 'backend/data/output_alignment' / book['id'] / 'Book_Y.xlsx').exists()
        assert client.patch(f"/api/pages/{page['id']}", json={'target_text': 'trời đất\nhuyền hoàng', 'input_revision': book['input_revision']}).status_code == 200
        assert client.get(endpoint+'/alignments').json()[0]['target'] == 'trời đất'


def test_legacy_new_only_records_do_not_pollute_books_counter_or_zip(tmp_path):
    raw_book(tmp_path)
    store = Store(tmp_path)
    with store.db() as db:
        db.execute("INSERT INTO books VALUES ('outside','Outside','Outside.pdf',NULL,0,'2026')")
        db.execute("INSERT INTO alignments VALUES ('outside',?)", (json.dumps([{'source': '天', 'target': 'trời'}]),))
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        data = client.get('/api/workspace').json()
        assert len(data['books']) == 1 and data['pair_stats']['pairs'] == 0
        assert client.get('/api/books/outside/pages').status_code == 404


def test_incomplete_pairs_are_not_counted_and_empty_target_keeps_its_row_position(tmp_path):
    bundle(tmp_path, records=[(0, '天地', '', '11'), (1, '', 'huyền hoàng', None)])
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        data = client.get('/api/workspace').json()
        assert not data['source_errors']
        book, = data['books']
        assert data['pair_stats']['pairs'] == 0 and data['pair_stats']['incomplete_pairs'] == 2
        page = imported_page(client, book)
        assert client.patch(f"/api/pages/{page['id']}", json={'target_text': 'thiên địa\nhuyền hoàng', 'input_revision': book['input_revision']}).status_code == 200
        assert client.get(f"/api/books/{book['id']}/alignments").json()[0]['target'] == 'thiên địa'
        assert client.get('/api/workspace').json()['pair_stats']['pairs'] == 0


@pytest.mark.parametrize('value,expected', [(1,'01'), (0,'00'), (11.0,'11'), ('01','01'), (None,'')])
def test_correctness_leading_zeroes_and_unicode(value, expected):
    assert correctness_bits(value, '𡗶南') == expected


def test_bad_correctness_or_out_of_range_pages_leave_mandatory_book_intact(tmp_path):
    bundle(tmp_path, records=[(0, '天地', 'thiên địa', '111')])
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        data = client.get('/api/workspace').json()
        assert len(data['books']) == 1 and not data['books'][0]['has_new_data']
        assert 'Correctness' in data['source_errors'][0]['message']


def test_ocr_checkpoints_save_pairs_but_count_only_reviewed_pairs(tmp_path):
    raw_book(tmp_path, count=1)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, = client.get('/api/workspace').json()['books']
        page = imported_page(client, book, 1)
        result = {'result_id': 'han', 'page_id': page['id'], 'version': page['version'],
                  'text_lines': ['天地'], 'completed_languages': ['han'],
                  'boxes': [{'id': 'line', 'transcription': '天地', 'points': [[10,10],[110,10],[110,40],[10,40]]}]}
        app.state.store.save_ocr(result, {}, '2026-11-17T00:00:00+00:00')
        app.state.store.save_ocr({**result, 'result_id': 'both', 'completed_languages': ['han','vi'],
                                 'vi_text_lines': ['thiên địa']}, {}, '2026-11-17T00:00:01+00:00')
        stats = client.get('/api/workspace').json()['pair_stats']
        assert stats['pairs'] == 0 and stats['saved_pairs'] == 1 and stats['reviewed_pairs'] == 0
