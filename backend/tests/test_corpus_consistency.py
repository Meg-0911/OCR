import io
import json
import os
import shutil
import zipfile
from unittest.mock import Mock, patch

import pytest
from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import create_app
from backend.ocr import KHNConfig
from backend.tests.test_new_data import bundle, imported_page, raw_book


def save(client, book, rows):
    response = client.put(f"/api/books/{book['id']}/alignments", json={'rows': rows, 'input_revision': book['input_revision']})
    assert response.status_code == 200, response.text
    return response.json()


def test_count_and_completion_are_independent_and_errors_need_confirmation(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        workspace = client.get('/api/workspace').json()
        book, = workspace['books']
        endpoint = f"/api/books/{book['id']}"
        assert workspace['pair_stats']['pairs'] == 0 and book['done'] == 0
        rows = client.get(endpoint+'/alignments').json()
        assert [row['countable'] for row in rows] == [False, False]
        rows[0]['reviewed'] = True
        rows = save(client, book, rows)
        assert client.get('/api/workspace').json()['pair_stats']['pairs'] == 1
        page = imported_page(client, book)
        assert page['status'] == 'pending'
        assert page['review_state'] == 'in_progress'
        response = client.put(f"/api/pages/{page['id']}", json={
            'version': page['version'], 'input_revision': book['input_revision'], 'category': 'ch',
            'boxes': page['boxes'], 'done': True, 'ocr_granularity': 'phrase'})
        assert response.status_code == 200, response.text
        assert response.json()['status'] == 'done'
        rows[0]['reviewed'] = False
        save(client, book, rows)
        data = client.get('/api/workspace').json()
        assert data['pair_stats']['pairs'] == 0 and data['books'][0]['done'] == 1
        summary = client.get(endpoint+'/results/summary.json').json()
        assert summary['pairs'] == 0 and summary['reviewed_pages'] == 1


def test_workspace_reuses_statistics_until_saved_data_changes(tmp_path):
    bundle(tmp_path)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        first = client.get('/api/workspace').json()
        book, = first['books']
        store = app.state.store
        with patch.object(store, 'describe_alignments', wraps=store.describe_alignments) as describe:
            assert client.get('/api/workspace').json()['pair_stats'] == first['pair_stats']
            describe.assert_not_called()
        rows = client.get(f"/api/books/{book['id']}/alignments").json()
        rows[0]['reviewed'] = True
        save(client, book, rows)
        updated = client.get('/api/workspace').json()
        assert updated['pair_stats']['pairs'] == updated['books'][0]['pair_stats']['pairs'] == 1
        page = imported_page(client, book)
        page['boxes'][1]['review_kind'] = 'unknown'
        page['boxes'][1]['review_marks'] = []
        result = client.patch(f"/api/pages/{page['id']}", json={
            'boxes': page['boxes'], 'version': page['version'], 'input_revision': book['input_revision']})
        assert result.status_code == 200, result.text
        current = client.get('/api/workspace').json()
        assert current['pair_stats']['pairs'] == current['books'][0]['pair_stats']['pairs'] == 1


def test_ids_colors_and_ocr_edits_remain_attached_after_reordering(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        endpoint = f"/api/books/{book['id']}"
        original = client.get(endpoint+'/alignments').json()
        reversed_rows = save(client, book, list(reversed(original)))
        assert [(row['id'], row['sentence_id']) for row in reversed_rows] == [(row['id'], row['sentence_id']) for row in reversed(original)]
        assert reversed_rows[1]['review_colors']['source'] == ['mismatch', 'match']
        assert reversed_rows[0]['review_colors']['source'] == ['match', 'match']
        page = imported_page(client, book)
        assert page['boxes'][0]['alignment_id'] == original[1]['id']
        page['boxes'][1]['transcription'] = '天地'
        page['boxes'][1]['review_kind'] = 'match'
        page['boxes'][1]['review_marks'] = []
        changed = client.patch(f"/api/pages/{page['id']}", json={'boxes': page['boxes'], 'input_revision': book['input_revision']})
        assert changed.status_code == 200, changed.text
        current = client.get(endpoint+'/alignments').json()
        assert current[0]['source'] == '玄黃' and current[1]['source'] == '天地'
        xlsx = load_workbook(io.BytesIO(client.get(endpoint+'/export?format=xlsx').content), rich_text=True)
        assert str(xlsx.active['C2'].value) == '玄黃'
        assert str(xlsx.active['C3'].value) == '天地'


@pytest.mark.parametrize('source,target,bits', [('天地', 'trời', '11'), ('天', 'bầu trời rộng', '1')])
def test_unequal_sides_can_be_imported_saved_confirmed_and_exported(tmp_path, source, target, bits):
    bundle(tmp_path, records=[(0, source, target, bits)])
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        endpoint = f"/api/books/{book['id']}"
        page = imported_page(client, book)
        response = client.put(f"/api/pages/{page['id']}", json={
            'version': page['version'], 'input_revision': book['input_revision'], 'category': 'ch',
            'boxes': page['boxes'], 'target_text': target, 'done': True})
        assert response.status_code == 200, response.text
        rows = client.get(endpoint+'/alignments').json()
        assert rows[0]['source'] == source and rows[0]['target'] == target
        assert rows[0]['countable'] is False
        rows[0]['reviewed'] = True
        saved = save(client, book, rows)
        assert saved[0]['countable'] is True
        assert saved[0]['target'] == target
        assert client.get(endpoint+'/export?format=xlsx').status_code == 200


def test_additional_source_pages_keep_existing_page_and_phrase_ids(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        page = imported_page(client, book)
        rows = client.get(f"/api/books/{book['id']}/alignments").json()
        bundle(tmp_path, page=4, records=[(0, '宇宙', 'vũ trụ', '11')])
        updated = client.post('/api/sources/sync').json()['books'][0]
        current = imported_page(client, updated)
        assert current['id'] == page['id'] and current['version'] == page['version']
        assert [row['id'] for row in client.get(f"/api/books/{book['id']}/alignments").json()[:2]] == [row['id'] for row in rows]
        assert client.patch(f"/api/pages/{page['id']}", json={'source_text': 'stale', 'input_revision': 'obsolete-revision'}).status_code == 409
        assert client.get(current['image_url']).status_code == 200


def test_old_dist_is_never_served(tmp_path):
    stale = tmp_path / 'frontend/dist/index.html'
    stale.parent.mkdir(parents=True)
    stale.write_text('stale interface')
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        result = client.get('/', follow_redirects=False)
        assert result.status_code == 307 and result.headers['location'] == 'http://127.0.0.1:5173'
        assert client.get('/old-built-file.js').status_code == 404


def test_runner_uses_project_root_even_when_started_elsewhere(tmp_path, monkeypatch):
    import run
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv('CORPUS_ROOT', 'stale-root-on-another-machine')
    ui = Mock()
    ui.poll.return_value = 0
    with patch('run.shutil.which', return_value='node'), patch.object(type(run.ROOT), 'is_file', return_value=True), patch('uvicorn.Config') as config, patch('run.subprocess.Popen', return_value=ui) as start, patch('uvicorn.Server') as server:
        start.side_effect = lambda *args, **kwargs: (config.return_value.load.assert_called_once(), ui)[1]
        run.main()
    assert start.call_args.kwargs['cwd'] == run.ROOT / 'frontend'
    assert __import__('os').environ['CORPUS_ROOT'] == str(run.ROOT)
    server.return_value.run.assert_called_once()


def test_old_alignment_save_cannot_overwrite_a_new_ocr_edit(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        endpoint = f"/api/books/{book['id']}"
        stale = client.get(endpoint+'/alignments').json()
        page = imported_page(client, book)
        assert client.patch(f"/api/pages/{page['id']}", json={'target_text': 'bầu trời\nhuyền hoàng', 'input_revision': book['input_revision']}).status_code == 200
        response = client.put(endpoint+'/alignments', json={'rows': stale, 'input_revision': book['input_revision']})
        assert response.status_code == 409
        assert client.get(endpoint+'/alignments').json()[0]['target'] == 'bầu trời'


def test_moving_workspace_and_changing_file_timestamps_keeps_edits_and_ids(tmp_path):
    original_root = tmp_path / 'first-machine'
    bundle(original_root)
    with TestClient(create_app(original_root, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        rows = client.get(f"/api/books/{book['id']}/alignments").json()
        rows[0]['target'] = 'bản đã sửa'
        save(client, book, rows)
        page = imported_page(client, book)
    moved = tmp_path / 'second-machine'
    shutil.copytree(original_root, moved, copy_function=shutil.copyfile)
    for path in (moved / 'backend/data/new').rglob('*.jpg'):
        os.utime(path, (1, 1))
    with TestClient(create_app(moved, ocr_config=KHNConfig())) as client:
        current, = client.get('/api/workspace').json()['books']
        assert current['id'] == book['id'] and current['input_revision'] == book['input_revision']
        assert imported_page(client, current)['id'] == page['id']
        assert client.get(f"/api/books/{book['id']}/alignments").json()[0]['target'] == 'bản đã sửa'


def test_incomplete_delivery_cannot_change_active_image_or_text(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        page = imported_page(client, book)
        image = client.get(page['image_url']).content
        (tmp_path / 'backend/data/new/Book/images/Book.003.jpg').write_bytes(b'copy in progress')
        refreshed = client.post('/api/sources/sync').json()
        assert refreshed['source_errors']
        assert refreshed['books'][0]['input_revision'] == book['input_revision']
        assert client.get(page['image_url']).content == image
        assert imported_page(client, book)['source_text'] == page['source_text']


def test_old_page_version_is_rejected_but_color_edits_preserve_confirmation(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        endpoint = f"/api/books/{book['id']}"
        rows = client.get(endpoint+'/alignments').json()
        rows[0]['reviewed'] = True
        save(client, book, rows)
        page = imported_page(client, book)
        boxes = page['boxes']
        boxes[0]['review_marks'][1]['kind'] = 'unknown'
        response = client.patch(f"/api/pages/{page['id']}", json={
            'version': page['version'], 'boxes': boxes, 'input_revision': book['input_revision']})
        assert response.status_code == 200, response.text
        stale = client.patch(f"/api/pages/{page['id']}", json={
            'version': page['version'], 'target_text': 'stale', 'input_revision': book['input_revision']})
        assert stale.status_code == 409
        rows = client.get(endpoint+'/alignments').json()
        assert rows[0]['reviewed'] is True and rows[0]['countable'] is True
        assert rows[0]['review_colors']['source'] == ['mismatch', 'unknown']


def test_editing_imported_pair_preserves_completion_and_updates_outputs(tmp_path):
    bundle(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        page = imported_page(client, book)
        endpoint = f"/api/books/{book['id']}"
        rows = client.get(endpoint+'/alignments').json()
        rows[0]['reviewed'] = True
        save(client, book, rows)
        page = imported_page(client, book)
        assert client.put(f"/api/pages/{page['id']}", json={
            'version': page['version'], 'input_revision': book['input_revision'], 'category': 'ch',
            'boxes': page['boxes'], 'done': True}).status_code == 200
        rows = client.get(endpoint+'/alignments').json()
        rows[0].update(source='天地人', target='trời', reviewed=True)
        saved = save(client, book, rows)
        current = imported_page(client, book)
        assert saved[0]['reviewed'] is True
        assert current['status'] == 'done' and current['review_state'] == 'done'
        assert current['boxes'][0]['transcription'] == '天地人'
        assert current['export_boxes'][0]['transcription'] == '天地人'
        assert current['source_text'] == '天地人\n玄黃' and current['target_text'] == 'trời\nhuyền hoàng'
        assert 'trời' in client.get(endpoint+'/export?format=csv').content.decode('utf-8-sig')
        assert client.get('/api/workspace').json()['books'][0]['done'] == 1


def test_raw_pair_edits_update_ocr_boxes_and_survive_restart(tmp_path):
    raw_book(tmp_path)
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book, = client.get('/api/workspace').json()['books']
        page = client.get(f"/api/books/{book['id']}/pages").json()[0]
        response = client.patch(f"/api/pages/{page['id']}", json={
            'category': 'both', 'ocr_granularity': 'phrase',
            'boxes': [{'id': 'nom', 'transcription': '天地', 'points': [[10,10],[100,10],[100,40],[10,40]]}],
            'vi_boxes': [{'id': 'vi', 'transcription': 'trời đất', 'points': [[10,60],[100,60],[100,90],[10,90]]}]})
        assert response.status_code == 200, response.text
        endpoint = f"/api/books/{book['id']}"
        rows = [{'id': 'pair', 'sentence_id': 'Book_Y.001.1', 'source': '天地', 'target': 'trời đất',
                 'source_page_id': page['id'], 'source_line_index': 0, 'target_page_id': page['id'], 'target_line_index': 0}]
        saved = save(client, book, rows)
        assert client.post(endpoint+'/alignments/prepare').status_code == 200
        saved = client.get(endpoint+'/alignments').json()
        saved[0].update(source='天', target='bầu trời rộng')
        save(client, book, saved)
        current = client.get(endpoint+'/pages').json()[0]
        assert current['source_text'] == '天' and current['boxes'][0]['transcription'] == '天'
        assert current['target_text'] == 'bầu trời rộng' and current['vi_boxes'][0]['transcription'] == 'bầu trời rộng'
        assert current['export_boxes'][0]['transcription'] == '天'
        assert client.get(endpoint+'/export?format=xlsx').status_code == 200
        with zipfile.ZipFile(io.BytesIO(client.get(endpoint+'/export?format=labels').content)) as archive:
            label = archive.read('Book_Y/ch/Label.txt').decode('utf-8').splitlines()[0]
            assert json.loads(label.split('\t')[1])[0]['transcription'] == '天'
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        current = client.get(endpoint+'/pages').json()[0]
        assert current['source_text'] == '天' and current['target_text'] == 'bầu trời rộng'


def test_colors_follow_source_page_id_when_physical_page_has_multiple_records(tmp_path):
    raw_book(tmp_path, count=1)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, = client.get('/api/workspace').json()['books']
        page = client.get(f"/api/books/{book['id']}/pages").json()[0]
        box = {'id': 'first-box', 'transcription': '天', 'review_kind': 'mismatch',
               'points': [[10,10],[100,10],[100,40],[10,40]]}
        assert client.patch(f"/api/pages/{page['id']}", json={'boxes': [box], 'ocr_granularity': 'phrase'}).status_code == 200
        with app.state.store.db() as db:
            db.execute("INSERT INTO pages(id,book_id,number,category,width,height,boxes,ocr_granularity) VALUES (?,?,1,'ch',200,300,?,'phrase')",
                       ('other-source', book['id'], json.dumps([{**box, 'id': 'second-box', 'review_kind': 'match'}])))
        rows = [
            {'id': 'first', 'sentence_id': 'Book_Y.001.1', 'source': '天', 'target': 'trời', 'source_page_id': page['id'], 'source_line_index': 0},
            {'id': 'other', 'sentence_id': 'Book_Y.001.2', 'source': '天', 'target': 'trời', 'source_page_id': 'other-source', 'source_line_index': 0, 'reviewed': True},
        ]
        saved = save(client, book, rows)
        assert saved[0]['review_colors']['source'] == ['mismatch']
        assert saved[1]['review_colors']['source'] == ['match']
        assert sum(row['countable'] for row in saved) == 1
        stats = client.get('/api/workspace').json()['pair_stats']
        assert stats['pairs'] == 1 and stats['duplicate_pairs'] == 1
