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


def test_unequal_line_counts_are_grouped_into_complete_pairs():
    page = {'id': 'source', 'number': 1, 'source_text': '天\n地\n玄',
            'target_text': 'trời\nđất', 'linked_page_ids': [], 'ocr_skip': False,
            'ocr_languages': ['han', 'vi']}
    rows = page_rows(page, [page], 'book')
    assert [(row['source'], row['target']) for row in rows] == [
        ('天', 'trời'), ('地玄', 'đất')]
    assert all(row['source'] and row['target'] and not row['reviewed'] for row in rows)
