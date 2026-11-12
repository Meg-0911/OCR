import csv
import json

from fastapi.testclient import TestClient
from openpyxl import load_workbook

from backend.app import create_app
from backend.tests.test_book_workflow import workspace, finish, HAN_BOX, VI_BOX


def test_page_links_preserve_ocr_and_export_source_image_id(tmp_path):
    app, client, book, pages, _, _, _ = workspace(tmp_path, count=2)
    book_id = book['id']
    first, second = pages
    plan = [{'page_id': first['id'], 'category': 'ch'},
            {'page_id': second['id'], 'category': 'vi'}]
    job = client.post(f'/api/books/{book_id}/workflow', json={'plan': plan}).json()
    finish(app, job)
    before = client.get(f'/api/books/{book_id}/pages').json()
    assert client.put(f"/api/pages/{first['id']}", json={
        'version': before[0]['version'], 'category': 'ch', 'boxes': before[0]['boxes'], 'done': True,
    }).status_code == 200
    assert client.put(f"/api/pages/{second['id']}", json={
        'version': before[1]['version'], 'category': 'vi', 'vi_boxes': [VI_BOX], 'done': True,
    }).status_code == 200
    saved = client.get(f'/api/books/{book_id}/pages').json()
    checkpoints = [client.get(f"/api/pages/{page['id']}/ocr").json() for page in pages]

    linked = client.put(f"/api/pages/{first['id']}/links", json={
        'linked_page_ids': [second['id']],
    })
    assert linked.status_code == 200, linked.text
    linked_pages = linked.json()
    assert linked_pages[0]['linked_page_ids'] == [second['id']]
    assert linked_pages[1]['linked_page_ids'] == [first['id']]
    for old, current in zip(saved, linked_pages):
        assert current['status'] == old['status'] == 'done'
        assert current['version'] == old['version']
        assert current['boxes'] == old['boxes']
        assert current['vi_boxes'] == old['vi_boxes']
    assert [client.get(f"/api/pages/{page['id']}/ocr").json() for page in pages] == checkpoints

    assert client.put(f"/api/pages/{first['id']}/links", json={
        'linked_page_ids': [first['id']],
    }).status_code == 422
    assert client.put(f"/api/pages/{first['id']}/links", json={
        'linked_page_ids': ['other-book-page'],
    }).status_code == 422

    sentence_id = f"{book['name']}.{first['number']:03d}.1"
    row = {'id': 'linked-1', 'sentence_id': sentence_id, 'source': '天地',
           'target': 'Thiên địa', 'source_page_id': first['id'], 'source_line_index': 0,
           'target_page_id': second['id'], 'target_line_index': 0, 'page_linked': True}
    response = client.put(f'/api/books/{book_id}/alignments', json={'rows': [row]})
    assert response.status_code == 200, response.text
    output = tmp_path / 'backend/data/output_alignment' / book_id
    alignment = json.loads((output / 'alignments.json').read_text(encoding='utf-8'))[0]
    assert alignment['target_page_id'] == second['id']
    assert alignment['sentence_id'] == sentence_id
    assert json.loads((output / 'pages.json').read_text(encoding='utf-8'))[0]['linked_page_ids'] == [second['id']]
    with (output / 'pairs.csv').open(encoding='utf-8-sig', newline='') as stream:
        values = list(csv.reader(stream))
    assert values[1][:2] == [f"{book['name']}.{first['number']:03d}.jpg", sentence_id]
    assert client.get(f'/api/books/{book_id}/export?format=csv').status_code == 200
    assert client.get(f'/api/books/{book_id}/export?format=xlsx').status_code == 200
    sheet = load_workbook(output / f"{book['name']}.xlsx").active
    assert [cell.value for cell in sheet[1]] == ['img_id', 'sentence_id', 'SinoNom_Char', 'ChuQN_txt']
    assert [sheet['A2'].value, sheet['B2'].value] == [
        f"{book['name']}.{first['number']:03d}.jpg", sentence_id,
    ]
    app.state.ocr_jobs.close()
    with TestClient(create_app(tmp_path)) as reopened:
        reopened_pages = reopened.get(f'/api/books/{book_id}/pages').json()
        assert reopened_pages[0]['linked_page_ids'] == [second['id']]
        assert reopened.get(f'/api/books/{book_id}/alignments').json()[0]['target_page_id'] == second['id']

    removed = client.put(f"/api/pages/{second['id']}/links", json={'linked_page_ids': []})
    assert removed.status_code == 200
    assert all(not page['linked_page_ids'] for page in removed.json())


def test_linked_page_can_confirm_unequal_language_box_counts(tmp_path):
    app, client, book, pages, _, _, _ = workspace(tmp_path, count=1)
    page = pages[0]
    current = client.get(f"/api/books/{book['id']}/pages").json()[0]
    response = client.put(f"/api/pages/{page['id']}", json={
        'version': current['version'], 'category': 'both', 'boxes': [HAN_BOX],
        'vi_boxes': [VI_BOX, {**VI_BOX, 'id': 'second-vi'}], 'done': True,
    })
    assert response.status_code == 200, response.text
    assert response.json()['status'] == 'done'
    app.state.ocr_jobs.close()
