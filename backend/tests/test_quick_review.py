import json
from copy import deepcopy
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from backend.app import create_app
from backend.nom_dictionary import NomDictionary
from backend.ocr import KHNConfig
from backend.quick_review import (analyze_row, read_reference, ReferenceMatcher, fingerprint,
                                 tokens, KIEU_NAME)
from backend.tests.test_new_data import bundle, imported_page
from backend.alignment_review import paint


def dictionary(tmp_path):
    path = tmp_path / 'nomnaviet-readings.json'
    path.write_text(json.dumps({'trăm': [{'c': '𤾓'}], 'năm': [{'c': '𢆥'}],
                               'thiên': [{'c': '天'}], 'địa': [{'c': '地'}]}), encoding='utf8')
    return NomDictionary(tmp_path)


def row(source='𤾓𢆥', target='Trăm nămt,'):
    return {'id': 'r', 'sentence_id': 'Kieu.250.1', 'source': source, 'target': target,
            'marks': [], 'reviewed': True}


def ref(source='𤾓𢆥', target='Trăm năm,'):
    return {'source': source, 'target': target, 'position': 1, 'label': '1', 'note': ''}


def test_trailing_t_boundary_and_preserve_real_t(tmp_path):
    d = dictionary(tmp_path)
    before = row()
    cards, fixed, good = analyze_row(before, ref(), d, kieu=True, page_number=249)
    assert fixed == 0 and before['target'] == 'Trăm nămt,' and len(cards) == 1
    after = row()
    after['marks'] = [{'source_start': 1, 'source_end': 2, 'target_start': 5, 'target_end': 9, 'kind': 'mismatch'}]
    cards, fixed, good = analyze_row(after, ref(), d, kieu=True, page_number=250)
    assert (cards, fixed, good) == ([], 1, 2)
    assert after['target'] == 'Trăm năm,' and after['reviewed']
    assert paint(after['source'], after['marks'], 'source') == ['match', 'match']
    actual = row(target='Trăm một')
    analyze_row(actual, ref(target='Trăm một'), d, kieu=True, page_number=500)
    assert actual['target'] == 'Trăm một'
    another = row()
    analyze_row(another, None, d, kieu=False, page_number=500)
    assert another['target'] == 'Trăm nămt,'


def test_unequal_counts_and_missing_reference_are_full_line(tmp_path):
    d = dictionary(tmp_path)
    for r, reference in [(row(target='trăm năm nữa'), ref()), (row(), None)]:
        cards, fixed, good = analyze_row(r, reference, d, kieu=True, page_number=250)
        assert len(cards) == 1 and cards[0]['index'] is None and not fixed and not good
    missing = row(source='□𢆥', target='trăm năm')
    cards, _, good = analyze_row(missing, ref(source=''), d, kieu=True, page_number=250)
    assert len(cards) == 1 and cards[0]['index'] == 0 and good == 1


def test_reference_order_preserves_missing_and_duplicate_numbers(tmp_path):
    path = tmp_path / 'TruyenKieu.txt'
    path.write_text('Chữ Nôm\tQuốc ngữ\n1𤾓𢆥\nNAME?\n1天地\n\nTrăm năm\nThiếu dòng\nthiên địa\n', encoding='utf8')
    lines = read_reference(path)
    assert [r['position'] for r in lines] == [1, 2, 3]
    assert [r['label'] for r in lines] == ['1', '', '1']
    assert lines[1]['source'] == ''
    matcher = ReferenceMatcher(lines)
    assert matcher.match(row(target='Trăm năm'))['position'] == 1
    assert ReferenceMatcher([ref(), ref()]).match(row(target='Trăm năm')) is None


def test_codepoint_offsets_and_accents(tmp_path):
    parts = tokens('Năm, na\u0306m!', 'target')
    assert parts == [('Năm', 0, 3), ('na\u0306m', 5, 9)]
    assert tokens('𤾓𢆥', 'source') == [('𤾓', 0, 1), ('𢆥', 1, 2)]
    assert dictionary(tmp_path).matches('𢆥', 'NA\u0306M')


def test_empty_side_explains_missing_content_before_reference(tmp_path):
    cards, _, _ = analyze_row(row('粥', ''), None, dictionary(tmp_path), kieu=True, page_number=250)
    assert 'Thiếu Hán Nôm hoặc Quốc ngữ' in cards[0]['reason']


@pytest.mark.parametrize('preserve', ['', 'target', 'marks', 'refs', 'manual', 'no_history', 'different_frame'])
@pytest.mark.parametrize('rotated', [False, True])
def test_quick_queue_reconciles_confirmed_deleted_ocr_noise(tmp_path, preserve, rotated):
    from backend.tests.test_new_data import raw_book
    from backend.tests.test_ocr_box_deletion import setup_page
    raw_book(tmp_path, count=1)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, page, original = setup_page(client)
        rows = deepcopy(original)
        orphan = rows[1]
        orphan.update(reviewed=True, target='', marks=[], page_linked=True)
        orphan.pop('source_refs', None)
        orphan.pop('target_refs', None)
        if preserve == 'target':
            orphan['target'] = 'huyền hoàng'
        elif preserve == 'marks':
            orphan['marks'] = [{'source_start': 0, 'source_end': 1, 'target_start': 0, 'target_end': 1, 'kind': 'match'}]
        elif preserve == 'refs':
            orphan['source_refs'] = [{'box_id': page['boxes'][1]['id'], 'start': 0, 'end': 2}]
        elif preserve == 'manual':
            orphan['page_linked'] = False
        keep = [page['boxes'][0], page['boxes'][2]]
        ocr_boxes = deepcopy(page['boxes'])
        if rotated:
            ocr_boxes[1]['points'] = [[10,80],[80,70],[90,85],[20,95]]
        if preserve == 'different_frame':
            ocr_boxes[1]['points'] = [[x+5,y+5] for x,y in ocr_boxes[1]['points']]
        service = app.state.quick_review
        with app.state.store.db() as db:
            if preserve != 'no_history':
                db.execute('INSERT INTO ocr_results VALUES (?,?,?,?,?,?)',
                           ('original', page['id'], 1, '{}', json.dumps({'boxes': ocr_boxes}), 'now'))
            db.execute('UPDATE alignments SET rows=? WHERE book_id=?', (json.dumps(rows), book['id']))
            db.execute('UPDATE pages SET boxes=?,source_text=?,version=version+1 WHERE id=?',
                       (json.dumps(keep), '\n'.join(b['transcription'] for b in keep), page['id']))
            for i, r in enumerate(rows):
                card = {'row_id': r['id'], 'index': None, 'ranges': {'source': [0, len(r['source'])], 'target': [0, len(r['target'])]},
                        'fingerprint': fingerprint(r), 'sentence_id': r['sentence_id']}
                db.execute('INSERT INTO quick_cards VALUES (?,?,?,?,?)',
                           (str(i), book['id'], r['id'], json.dumps(card), 'done' if i == 0 else 'pending'))
        status = service.status(book['id'])
        assert status['counts']['done'] == 1
        assert status['counts']['pending'] == (2 if preserve else 1)
        assert status['card']['row_id'] == (rows[1] if preserve else rows[2])['id']
        saved = app.state.store.alignment_rows(book['id'])
        assert [r['id'] for r in saved] == [r['id'] for r in (rows if preserve else [rows[0], rows[2]])]
        current = client.get(f"/api/pages/{page['id']}").json()
        assert current['boxes'] == keep
        assert [r['source'] for r in current['review_rows']] == [r['source'] for r in saved]
        assert service.status(book['id'])['card']['id'] == status['card']['id']


def test_persistent_decisions_conflicts_and_geometry(tmp_path):
    bundle(tmp_path, records=[(0, '天地', 'thiên sai', '00'), (1, '天地', 'lệch sai', '00')])
    folder = tmp_path / 'backend/data/dictionaries'
    folder.mkdir(exist_ok=True)
    dictionary(folder)
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, = client.get('/api/workspace').json()['books']
        book_id = book['id']
        service = app.state.quick_review
        page = imported_page(client, book)
        points = [b['points'] for b in page['boxes']]
        service.scan(book_id)
        assert service.job(book_id)['status'] == 'completed'
        status = service.status(book_id)
        assert status['counts']['pending'] == 3
        card = status['card']
        original_card_id = card['id']
        assert card['source'] == '地' and card['target'] == 'sai' and not card['stale']
        endpoint = f'/api/books/{book_id}/quick-review'
        response = client.post(endpoint + f"/{card['id']}/decide", json={
            'action': 'match', 'fingerprint': card['fingerprint'], 'target': 'địa'})
        assert response.status_code == 200, response.text
        after = imported_page(client, book)
        assert [b['points'] for b in after['boxes']] == points
        assert not any(r['reviewed'] for r in app.state.store.alignment_rows(book_id))
        assert service.status(book_id)['counts']['done'] == 1
        service.scan(book_id)
        assert service.status(book_id)['counts']['done'] == 1  # no reappearance on rescan
        response = client.post(endpoint + '/undo')
        assert response.status_code == 200, response.text
        assert app.state.store.alignment_rows(book_id)[0]['target'] == 'thiên sai'
        assert service.status(book_id)['counts']['pending'] == 3
        card = service.status(book_id)['card']
        assert not card['stale'] and card['id'] == original_card_id
        service.scan(book_id)
        assert service.status(book_id)['counts']['pending'] == 3
        before_back_test = deepcopy(app.state.store.alignment_rows(book_id))
        first = service.status(book_id)['card']
        service.decide(book_id, first['id'], 'defer', first['fingerprint'])
        second = service.status(book_id)['card']
        assert second['id'] != first['id']
        service.decide(book_id, second['id'], 'mismatch', second['fingerprint'])
        assert service.status(book_id)['can_undo']
        service.undo(book_id)
        assert service.status(book_id)['card']['id'] == second['id']
        service.undo(book_id)
        assert service.status(book_id)['card']['id'] == first['id']
        assert service.status(book_id)['card']['state'] == 'pending'
        assert app.state.store.alignment_rows(book_id) == before_back_test
        assert not service.status(book_id)['can_undo']
        card = service.status(book_id)['card']
        saved = app.state.store.alignment_rows(book_id)
        next(r for r in saved if r['id'] == card['row_id'])['target'] = 'ai sửa'
        with app.state.store.db() as db:
            db.execute('UPDATE alignments SET rows=? WHERE book_id=?', (json.dumps(saved), book_id))
        response = client.post(endpoint + f"/{card['id']}/decide", json={'action': 'match', 'fingerprint': card['fingerprint']})
        assert response.status_code == 409
        assert service.status(book_id)['card']['stale']


def test_confirm_kieu_is_scoped_and_backs_up(tmp_path):
    from tools.confirm_kieu import confirm
    bundle(tmp_path, records=[(0, '天地', 'thiên địa', '11')])
    app = create_app(tmp_path, ocr_config=KHNConfig())
    with TestClient(app) as client:
        book, = client.get('/api/workspace').json()['books']
        store = app.state.store
        with store.db() as db:
            db.execute('UPDATE books SET name=? WHERE id=?', (KIEU_NAME, book['id']))
            db.execute("INSERT INTO books(id,name,filename,created_at) VALUES ('other','Other','Other.pdf','now')")
            db.execute("INSERT INTO pages(id,book_id,number,category) VALUES ('other-page','other',1,'ch')")
            db.execute("INSERT INTO alignments VALUES ('other',?)", (json.dumps([row() | {'reviewed': False}]),))
        report = confirm(tmp_path, True)
        assert Path(report['backup']).exists()
        assert all(r['reviewed'] for r in store.alignment_rows(book['id']))
        assert all(p['status'] == 'done' for p in store.pages(book['id']))
        assert not store.alignment_rows('other')[0]['reviewed']
        assert store.page('other-page')['status'] == 'pending'
