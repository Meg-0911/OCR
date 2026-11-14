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
    if page.get('ocr_granularity') == 'phrase':
        return [[box] for box in boxes]
    return character_box_groups(boxes, page['reading_direction'])


def index_pages(pages):
    by_id = {}
    by_number = {}
    order = {}
    for index, page in enumerate(pages):
        by_id[page['id']] = page
        by_number.setdefault(page['number'], []).append(page)
        order[page['id']] = index
    return by_id, by_number, order


def target_pages(source, pages, indexes=None):
    by_id, by_number, order = indexes or index_pages(pages)
    linked_ids = [source['id'], *source['linked_page_ids']]
    linked = [by_id[page_id] for page_id in linked_ids if page_id in by_id
              and not by_id[page_id]['ocr_skip'] and 'vi' in by_id[page_id]['ocr_languages']]
    if source['linked_page_ids'] and linked:
        return sorted(linked, key=lambda page: (page['number'], order[page['id']]))
    if 'vi' in source['ocr_languages']:
        return [source]
    return [page for page in by_number.get(source['number'], [])
            if page['id'] != source['id'] and not page['ocr_skip']
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


def page_rows(source, pages, book_name, reference='', indexes=None):
    source_lines = ([box['transcription'].strip() for group in source_groups(source)
                     for box in group if box['transcription'].strip()]
                    if source.get('ocr_granularity') == 'phrase' else lines(source['source_text'])) or [
        ''.join(box['transcription'] for box in group) for group in source_groups(source)]
    targets = [(line, page['id'], index) for page in target_pages(source, pages, indexes)
               for index, line in enumerate(lines(page['target_text']))]
    if not targets and source['target_text']:
        targets = [(line, None, index) for index, line in enumerate(lines(source['target_text']))]
    if not targets and reference:
        targets = [(line, None, index) for index, line in
                   enumerate(lines(reference_for_page(reference, source['number'])))]
    if not source_lines:
        return []
    result = []
    for index, source_line in enumerate(source_lines):
        target = targets[index] if index < len(targets) else None
        target_text, target_page_id, target_line_index = target if target else ('', None, None)
        result.append({
            'id': uuid4().hex,
            'sentence_id': f"{book_name}.{source['number']:03d}.{index + 1}",
            'source': source_line,
            'target': target_text,
            'reviewed': False,
            'page_linked': bool(source['linked_page_ids']),
            'source_page_id': source['id'],
            'source_line_index': index,
            'target_page_id': target_page_id,
            'target_line_index': target_line_index if target_page_id is not None else None,
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
