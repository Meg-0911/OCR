import pytest
import pymupdf
from pydantic import ValidationError
from fastapi.testclient import TestClient

from backend.app import PageInput, PagePatch, create_app
from backend.ocr import KHNConfig
from backend.store import ordered_boxes


def box(id, order):
    return {
        'id': id,
        'transcription': '字',
        'points': [[0, 0], [10, 0], [10, 10], [0, 10]],
        'review_order': order,
    }


def test_order_conflict_is_saved_as_patch_but_blocks_completion():
    boxes = [box('a', 1), box('b', 1)]
    assert len(PagePatch(boxes=boxes).boxes) == 2
    with pytest.raises(ValidationError, match='Số thứ tự box OCR'):
        PageInput(boxes=boxes, category='ch', version=0, done=True)
    with pytest.raises(ValidationError, match='Số thứ tự box OCR'):
        PageInput(boxes=[box('a', None)], category='ch', version=0, done=True)
    assert PageInput(boxes=[box('a', 2), box('b', 1)], category='ch', version=0, done=True)


def test_review_order_controls_persisted_nom_sequence():
    first = box('left', 1)
    second = box('right', 2)
    second['points'] = [[20, 0], [30, 0], [30, 10], [20, 10]]
    assert [item['id'] for item in ordered_boxes([first, second], 'ch', 1)] == ['left', 'right']


def test_conflicting_order_remains_saved_after_failed_completion(tmp_path):
    folder = tmp_path / 'backend/data/raw_data'
    folder.mkdir(parents=True)
    with pymupdf.open() as document:
        document.new_page(width=100, height=100)
        document.save(folder / 'Book.pdf')
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book = client.get('/api/workspace').json()['books'][0]
        page = client.get(f"/api/books/{book['id']}/pages").json()[0]
        url = f"/api/pages/{page['id']}"
        updated = client.patch(url, json={'category': 'ch', 'boxes': [box('a', 1), box('b', 1)]})
        assert updated.status_code == 200
        saved = updated.json()
        assert [item['review_order'] for item in saved['boxes']] == [1, 1]
        result = client.put(url, json={
            'version': saved['version'], 'category': 'ch', 'done': True,
            'boxes': saved['boxes'],
        })
        assert result.status_code == 422
        retained = client.get(f"/api/books/{book['id']}/pages").json()[0]
        assert retained['status'] == 'pending'
        assert [item['review_order'] for item in retained['boxes']] == [1, 1]


def test_editing_alignment_boxes_does_not_unfinish_ocr_review(tmp_path):
    folder = tmp_path / 'backend/data/raw_data'
    folder.mkdir(parents=True)
    with pymupdf.open() as document:
        document.new_page(width=100, height=100)
        document.save(folder / 'Book.pdf')
    with TestClient(create_app(tmp_path, ocr_config=KHNConfig())) as client:
        book = client.get('/api/workspace').json()['books'][0]
        page = client.get(f"/api/books/{book['id']}/pages").json()[0]
        url = f"/api/pages/{page['id']}"
        confirmed = client.put(url, json={
            'version': page['version'], 'category': 'ch', 'done': True,
            'boxes': [box('a', 1)], 'source_text': '字', 'ocr_granularity': 'character',
        })
        assert confirmed.status_code == 200
        assert confirmed.json()['status'] == 'done'
        aligned = client.patch(url, json={'export_boxes': [{
            'id': 'sentence-box', 'transcription': '字',
            'points': [[0, 0], [10, 0], [10, 10], [0, 10]],
            'export_group': 'sentence-box', 'export_order': 1,
            'export_character_order': 0, 'alignment_id': 'sentence-1',
            'box_axis': 'vertical',
        }]})
        assert aligned.status_code == 200
        assert aligned.json()['status'] == 'done'
        assert aligned.json()['export_boxes'][0]['box_axis'] == 'vertical'
