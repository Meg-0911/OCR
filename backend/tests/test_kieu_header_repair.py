from copy import deepcopy

import pytest

from tools.repair_kieu_header_pairs import plan_repair


def fixture():
    def box(id, text, y):
        return {'id': id, 'transcription': text, 'points': [[0,y],[10,y],[10,y+10],[0,y+10]]}
    source_boxes = [box('a', '天地', 20), box('b', '玄黃', 40)]
    noise = box('noise', '加啦咖', 0)
    target_boxes = [box('vi-a', 'thiên địa', 20), box('vi-b', 'huyền hoàng', 40)]
    header = 'Truyện Kiều - bản Duy Minh Thị 18T2'
    rows = [{'id': f'r{i}', 'sentence_id': f'Kieu.352.{i+1}', 'source': s, 'target': t,
             'source_page_id': 's', 'source_line_index': i, 'target_page_id': 't',
             'target_line_index': max(0, i-1), 'reviewed': True, 'page_linked': True, 'marks': []}
            for i, (s, t) in enumerate([('天地',header),('加啦咖','thiên địa'),('玄黃','huyền hoàng')])]
    rows[2]['marks'] = [{'source_start': 0, 'source_end': 1, 'target_start': 0, 'target_end': 5, 'kind': 'mismatch'}]
    exports = [{**b, 'alignment_id': r['id']} for b, r in zip([source_boxes[0],noise,source_boxes[1]], rows)]
    pages = [{'id': 's', 'number': 352, 'boxes': source_boxes, 'export_boxes': exports},
             {'id': 't', 'number': 353, 'vi_boxes': target_boxes}]
    originals = {'s': {'boxes': [source_boxes[0], noise, source_boxes[1]]},
                 't': {'vi_text_lines': [header,'thiên địa','huyền hoàng']}}
    return rows, pages, originals


def test_repair_preserves_colors_ids_and_geometry_and_is_idempotent():
    rows, pages, originals = fixture()
    before = deepcopy((rows, pages))
    repaired, updated, changed, removed = plan_repair(rows, pages, originals, set())
    assert changed == {'r0'} and removed == {'r1'}
    assert [r['id'] for r in repaired] == ['r0','r2']
    assert [r['target'] for r in repaired] == ['thiên địa','huyền hoàng']
    assert repaired[1]['marks'] == rows[2]['marks']
    assert all(r['reviewed'] for r in repaired)
    assert updated[0]['boxes'] == pages[0]['boxes'] and updated[1]['vi_boxes'] == pages[1]['vi_boxes']
    assert (rows, pages) == before
    assert plan_repair(repaired, updated, originals, set())[2:] == (set(), set())


@pytest.mark.parametrize('edit', ['color', 'decision', 'text', 'geometry', 'order', 'target_ocr'])
def test_repair_rejects_ambiguous_or_manually_edited_data(edit):
    rows, pages, originals = fixture()
    protected = set()
    if edit == 'color': rows[0]['marks'] = [{'kind': 'mismatch'}]
    if edit == 'decision': protected.add('r0')
    if edit == 'text': rows[1]['target'] = 'người dùng đã sửa'
    if edit == 'geometry': originals['s']['boxes'][1]['points'] = [[0,0]] * 4
    if edit == 'order': pages[0]['boxes'].reverse()
    if edit == 'target_ocr': pages[1]['vi_boxes'][0]['transcription'] = 'khác'
    with pytest.raises(ValueError):
        plan_repair(rows, pages, originals, protected)
