"""Validate pair-to-box coverage before packaging reviewed OCR labels."""
from copy import deepcopy
from .alignment_links import ref_text, locate
from .alignment_review import export_text


def select_label_pages(pages, rows):
    selected = {page['id']: {**deepcopy(page), 'export_boxes': [], 'vi_boxes': []} for page in pages}
    by_id = {page['id']: page for page in pages}
    target_coverage = {}
    source_coverage = {}
    source_used = set()
    for row in rows:
        number = int(row['sentence_id'].rsplit('.', 2)[1])
        sources = [page for page in pages if page['id'] == row.get('source_page_id')] if row.get('source_page_id') else [
            page for page in pages if page['number'] == number and 'han' in page['ocr_languages']]
        matches = [(page, box) for page in sources for box in page['export_boxes']
                   if box.get('alignment_id') == row['id']]
        if not matches:
            matches = [(page, box) for page in sources for box in page['export_boxes']
                       if not box.get('alignment_id') and export_text(box['transcription'], 'source')[0] == export_text(row['source'], 'source')[0]]
            if len(matches) != 1:
                matches = []
        if not matches or export_text(''.join(box['transcription'] for _, box in matches), 'source')[0] != export_text(row['source'], 'source')[0]:
            raise ValueError(f"{row['sentence_id']}: thiếu box Nôm khớp nội dung cặp. Vẽ/gán box trước khi xuất.")
        for page, box in matches:
            key = page['id'], box['id']
            if key in source_used:
                raise ValueError(f"{row['sentence_id']}: một box Nôm đang gắn vào nhiều cặp.")
            source_used.add(key)
            selected[page['id']]['export_boxes'].append(box)
        for page in sources:
            refs = row.get('source_refs') or locate(row['source'], page['boxes'], row.get('source_line_index'))
            text = ref_text(refs, page['boxes']) if refs else None
            if row.get('source_refs') and (text is None or export_text(text, 'source')[0] != export_text(row['source'], 'source')[0]):
                raise ValueError(f"{row['sentence_id']}: liên kết box Nôm không khớp nội dung. Kiểm tra lại vùng chữ trước khi xuất.")
            if text is not None and export_text(text, 'source')[0] == export_text(row['source'], 'source')[0]:
                for ref in refs:
                    source_coverage.setdefault((page['id'], ref['box_id']), set()).update(range(ref['start'], ref['end']))
        target_page = by_id.get(row.get('target_page_id'))
        if target_page is None and len(sources) == 1:
            target_page = sources[0]
        if target_page is None or not target_page['vi_boxes']:
            continue  # Text-only translations have no OCR geometry to export.
        refs = row.get('target_refs') or locate(row['target'], target_page['vi_boxes'], row.get('target_line_index'))
        text = ref_text(refs, target_page['vi_boxes']) if refs else None
        if text is None or export_text(text, 'target')[0] != export_text(row['target'], 'target')[0]:
            raise ValueError(f"{row['sentence_id']}: liên kết box Quốc ngữ không khớp. Kiểm tra trang và dòng đối chiếu.")
        for ref in refs:
            coverage = target_coverage.setdefault((target_page['id'], ref['box_id']), set())
            positions = set(range(ref['start'], ref['end']))
            box = next(box for box in target_page['vi_boxes'] if box['id'] == ref['box_id'])
            if any(export_text(box['transcription'][index], 'target')[0] for index in coverage & positions):
                raise ValueError(f"{row['sentence_id']}: cùng đoạn chữ Quốc ngữ đang gắn vào nhiều cặp. Kiểm tra lại cách ghép.")
            coverage.update(positions)
    for page in pages:
        for box in page['vi_boxes']:
            coverage = target_coverage.get((page['id'], box['id']))
            if not coverage:
                continue
            required = {index for index, char in enumerate(box['transcription']) if export_text(char, 'target')[0]}
            if not required <= coverage:
                raise ValueError(f"Trang {page['number']}: box Quốc ngữ chứa cả phần chưa được chọn. Xác nhận đủ các cặp của box hoặc tách box trước khi xuất.")
            selected[page['id']]['vi_boxes'].append(box)
        current = selected[page['id']]
        current['boxes'] = current['vi_boxes'] if page['category'] == 'vi' else current['export_boxes']
        source_total = {box['id'] for box in page['export_boxes'] if export_text(box['transcription'], 'source')[0]}
        target_total = {box['id'] for box in page['vi_boxes'] if export_text(box['transcription'], 'target')[0]}
        source_complete = all(
            {index for index, char in enumerate(box['transcription']) if export_text(char, 'source')[0]}
            <= source_coverage.get((page['id'], box['id']), set()) for box in page['boxes']
        ) if 'han' in page['ocr_languages'] else True
        current['export_complete'] = (bool(source_total or target_total)
            and source_complete
            and source_total == {box['id'] for box in current['export_boxes']}
            and target_total == {box['id'] for box in current['vi_boxes']})
    return list(selected.values())
