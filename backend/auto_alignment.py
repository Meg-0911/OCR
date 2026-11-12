"""Prepare reviewable bilingual pairs and export boxes from saved OCR."""
import re
from uuid import uuid4

from .store import character_box_groups, ordered_boxes


def lines(text):
    return [line.strip() for line in (text or '').splitlines() if line.strip()]


def joined(text):
    return re.sub(r'\s+', '', text)


def source_groups(page):
    boxes = ordered_boxes(page['boxes'], 'ch', page['reading_direction'],
                          (page['width'], page['height']))
    return character_box_groups(boxes, page['reading_direction'])


def paired_spans(source_count, target_count):
    """Keep every OCR line while joining the longer side into the shorter side."""
    count = min(source_count, target_count)
    for index in range(count):
        source = (index * source_count // count, (index + 1) * source_count // count)
        target = (index * target_count // count, (index + 1) * target_count // count)
        yield source, target


def target_pages(source, pages):
    linked = [page for page in pages if (page['id'] in source['linked_page_ids'] or page['id'] == source['id'])
              and not page['ocr_skip'] and 'vi' in page['ocr_languages']]
    if source['linked_page_ids'] and linked:
        return sorted(linked, key=lambda page: page['number'])
    if 'vi' in source['ocr_languages']:
        return [source]
    return [page for page in pages if page['number'] == source['number']
            and page['id'] != source['id'] and not page['ocr_skip']
            and 'vi' in page['ocr_languages']]


def reference_for_page(text, number):
    markers = list(re.finditer(r'^\s*\*+\s*Page\s+(\d+)\s*\*+\s*$', text, re.I | re.M))
    if markers:
        for index, marker in enumerate(markers):
            if int(marker.group(1)) == number:
                return text[marker.end():markers[index + 1].start() if index + 1 < len(markers) else len(text)]
        return ''
    if '\f' in text:
        parts = text.split('\f')
        return parts[number - 1] if number <= len(parts) else ''
    return text


def page_rows(source, pages, book_name, reference=''):
    source_lines = lines(source['source_text']) or [
        ''.join(box['transcription'] for box in group) for group in source_groups(source)]
    targets = [(line, page['id'], index) for page in target_pages(source, pages)
               for index, line in enumerate(lines(page['target_text']))]
    if not targets and source['target_text']:
        targets = [(line, None, index) for index, line in enumerate(lines(source['target_text']))]
    if not targets and reference:
        targets = [(line, None, index) for index, line in
                   enumerate(lines(reference_for_page(reference, source['number'])))]
    if not source_lines or not targets:
        return []
    result = []
    for index, ((s0, s1), (t0, t1)) in enumerate(paired_spans(len(source_lines), len(targets)), 1):
        target_ids = {page_id for _, page_id, _ in targets[t0:t1]}
        result.append({
            'id': uuid4().hex,
            'sentence_id': f"{book_name}.{source['number']:03d}.{index}",
            'source': ''.join(source_lines[s0:s1]),
            'target': ' '.join(line for line, _, _ in targets[t0:t1]),
            'reviewed': False,
            'page_linked': bool(source['linked_page_ids']),
            'source_page_id': source['id'],
            'source_line_index': s0 if s1 - s0 == 1 else None,
            'target_page_id': next(iter(target_ids)) if len(target_ids) == 1 else None,
            'target_line_index': targets[t0][2] if t1 - t0 == 1 and len(target_ids) == 1
            and targets[t0][1] is not None else None,
            'marks': [],
        })
    return result


def boxes_for_rows(page, rows):
    """Match whole OCR lines to pairs; ambiguous geometry stays for manual review."""
    groups = source_groups(page)
    result = []
    cursor = 0
    axis = 'vertical' if page['reading_direction'] == 1 else 'horizontal'
    for row in rows:
        matched = []
        while cursor < len(groups) and len(joined(''.join(
                box['transcription'] for group in matched for box in group))) < len(joined(row['source'])):
            matched.append(groups[cursor])
            cursor += 1
        boxes = [box for group in matched for box in group]
        if not boxes or joined(''.join(box['transcription'] for box in boxes)) != joined(row['source']):
            continue
        x0 = min(point[0] for box in boxes for point in box['points'])
        y0 = min(point[1] for box in boxes for point in box['points'])
        x1 = max(point[0] for box in boxes for point in box['points'])
        y1 = max(point[1] for box in boxes for point in box['points'])
        box_id = uuid4().hex
        result.append({'id': box_id, 'transcription': row['source'],
                       'points': [[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                       'alignment_id': row['id'], 'box_axis': axis,
                       'export_group': box_id, 'export_order': len(result) + 1,
                       'export_character_order': 0})
    return result
