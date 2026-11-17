import json
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from backend.app import create_app
from backend.ocr import KHNConfig
from backend.tests.test_new_data import bundle, imported_page, raw_book


def test_cached_image_does_not_load_ocr_or_wait_for_editor_lock(tmp_path):
    raw_book(tmp_path, count=1)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, = client.get('/api/workspace').json()['books']
        page, = client.get(f"/api/books/{book['id']}/pages").json()
        original = client.get(page['image_url'])
        assert original.status_code == 200
        thumbnail = client.get(page['image_url'] + '?thumbnail=true')
        assert thumbnail.status_code == 200
        lock = MagicMock()
        lock.__enter__.side_effect = AssertionError('Cached image waited for an edit')
        with patch.object(app.state.store, 'lock', lock), patch.object(
            app.state.store, 'page', side_effect=AssertionError('Image loaded OCR data')
        ):
            cached = client.get(page['image_url'])
            cached_thumbnail = client.get(page['image_url'] + '?thumbnail=true')
        assert cached.status_code == 200 and cached.content == original.content
        assert cached_thumbnail.status_code == 200 and cached_thumbnail.content == thumbnail.content


def test_phrase_edit_loads_current_page_once_and_updates_all_affected_pairs(tmp_path):
    bundle(tmp_path)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, = client.get('/api/workspace').json()['books']
        page = imported_page(client, book)
        boxes = [{**box, 'transcription': box['transcription'] + '人'} for box in page['boxes']]
        source = '\n'.join(box['transcription'] for box in boxes)
        store = app.state.store
        with store.db() as db:
            db.execute('UPDATE pages SET boxes=?,source_text=?,version=version+1 WHERE id=?',
                       (json.dumps(boxes, ensure_ascii=False), source, page['id']))
        with patch.object(store, 'page', wraps=store.page) as load_page:
            assert store.sync_alignment_page_text(page, page['source_text'], page['target_text'], source, page['target_text'])
            load_page.assert_called_once_with(page['id'])
        assert [row['source'] for row in store.alignment_rows(book['id'])] == [box['transcription'] for box in boxes]


def test_loading_unchanged_alignments_skips_repeated_ocr_repair(tmp_path):
    raw_book(tmp_path, count=1)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, = client.get('/api/workspace').json()['books']
        page, = client.get(f"/api/books/{book['id']}/pages").json()
        store = app.state.store
        row = {'id': 'pair', 'sentence_id': 'Book_Y.001.1', 'source': '天', 'target': 'trời'}
        result = {'text_lines': ['天'], 'vi_text_lines': ['trời']}
        with store.db() as db:
            db.execute('INSERT INTO alignments VALUES (?,?)', (book['id'], json.dumps([row])))
            db.execute('INSERT INTO ocr_results VALUES (?,?,?,?,?,?)', ('result', page['id'], 0, '{}', json.dumps(result), '2026-01-01'))
            db.execute("UPDATE pages SET source_text='天',target_text='trời',edited_fields='[\"boxes\"]',version=version+1 WHERE id=?", (page['id'],))
        endpoint = f"/api/books/{book['id']}/alignments"
        with patch.object(store, 'sync_alignment_page_text', wraps=store.sync_alignment_page_text) as repair:
            assert client.get(endpoint).status_code == 200
            assert repair.call_count == 1
            assert client.get(endpoint).status_code == 200
            assert repair.call_count == 1
            with store.db() as db:
                db.execute('UPDATE pages SET version=version+1 WHERE id=?', (page['id'],))
            assert client.get(endpoint).status_code == 200
            assert repair.call_count == 2


def test_confirming_page_returns_version_that_next_box_edit_can_save(tmp_path):
    bundle(tmp_path)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, = client.get('/api/workspace').json()['books']
        page = imported_page(client, book)
        endpoint = f"/api/pages/{page['id']}"
        boxes = [{**box, 'review_order': len(page['boxes']) - index} for index, box in enumerate(page['boxes'])]
        edited = client.patch(endpoint, json={'boxes': boxes, 'version': page['version'], 'input_revision': book['input_revision']})
        assert edited.status_code == 200, edited.text
        confirmed = client.put(endpoint, json={
            'boxes': edited.json()['boxes'], 'version': edited.json()['version'],
            'input_revision': book['input_revision'], 'category': 'ch', 'done': True, 'ocr_granularity': 'phrase'})
        assert confirmed.status_code == 200, confirmed.text
        current = client.get(endpoint).json()
        assert current['export_boxes']
        assert current['version'] == confirmed.json()['version']
        next_edit = client.patch(endpoint, json={
            'target_text': 'bầu trời\nhuyền hoàng', 'version': confirmed.json()['version'],
            'input_revision': book['input_revision']})
        assert next_edit.status_code == 200, next_edit.text
