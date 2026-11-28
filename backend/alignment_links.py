"""Stable character ranges connecting saved pairs to OCR boxes."""
from copy import deepcopy
from difflib import SequenceMatcher


def matches_export_frame(points, exported):
    """Sentence exports enclose rotated OCR polygons in an axis-aligned frame."""
    if points == exported:
        return True
    if not points:
        return False
    xs, ys = zip(*points)
    return exported == [[min(xs), min(ys)], [max(xs), min(ys)],
                        [max(xs), max(ys)], [min(xs), max(ys)]]


def ref_text(refs, boxes):
    indexed = {box['id']: box for box in boxes}
    parts = []
    for ref in refs:
        box = indexed.get(ref['box_id'])
        if box is None or not 0 <= ref['start'] < ref['end'] <= len(box['transcription']):
            return None
        parts.append(box['transcription'][ref['start']:ref['end']])
    return ''.join(parts)


def locate(text, boxes, preferred=None):
    """Use a legacy index only when its text agrees; never guess an ambiguous match."""
    if not text:
        return []
    matches = []
    for index, box in enumerate(boxes):
        value = box['transcription']
        start = value.find(text)
        if start < 0 or value.find(text, start + 1) >= 0:
            continue
        refs = [{'box_id': box['id'], 'start': start, 'end': start + len(text)}]
        if index == preferred and value.strip() == text.strip():
            return refs
        matches.append(refs)
    if len(matches) == 1:
        return matches[0]
    if not matches and ''.join(box['transcription'] for box in boxes) == text:
        return [{'box_id': box['id'], 'start': 0, 'end': len(box['transcription'])}
                for box in boxes if box['transcription']]
    return []


def attach_refs(rows, pages):
    """Annotate legacy rows without changing their IDs, order, text or confirmation."""
    by_id = {page['id']: page for page in pages}
    result = deepcopy(rows)
    for row in result:
        for side, key in (('source', 'boxes'), ('target', 'vi_boxes')):
            page = by_id.get(row.get(side + '_page_id'))
            if not page or row.get(side + '_refs'):
                continue
            boxes = page[key]
            assigned = [box for box in boxes if box.get('alignment_id') == row['id']]
            if assigned and ''.join(box['transcription'] for box in assigned) == row[side]:
                refs = [{'box_id': box['id'], 'start': 0, 'end': len(box['transcription'])}
                        for box in assigned if box['transcription']]
            else:
                refs = locate(row[side], boxes, row.get(side + '_line_index'))
                if not refs and side == 'source':
                    from .auto_alignment import source_groups
                    candidates = [group for group in source_groups(page)
                                  if ''.join(box['transcription'] for box in group).strip() == row[side].strip()]
                    if len(candidates) == 1:
                        refs = [{'box_id': box['id'], 'start': 0, 'end': len(box['transcription'])}
                                for box in candidates[0] if box['transcription']]
            if refs:
                row[side + '_refs'] = refs
    return result


def replace_ranges(boxes, edits):
    """Apply disjoint edits against one snapshot and return offsets for remaining links."""
    result = deepcopy(boxes)
    indexed = {box['id']: box for box in result}
    grouped = {}
    for refs, before, after in edits:
        if not refs or ref_text(refs, boxes) != before:
            continue
        # A multi-box phrase can be shortened without moving its geometry.
        cursor = 0
        for index, ref in enumerate(refs):
            size = ref['end'] - ref['start']
            value = after[cursor:] if index == len(refs) - 1 else after[cursor:cursor + size]
            cursor += size
            grouped.setdefault(ref['box_id'], []).append((ref['start'], ref['end'], value))
    accepted = {}
    for box_id, changes in grouped.items():
        changes = sorted(set(changes))
        if any(a[1] > b[0] for a, b in zip(changes, changes[1:])):
            continue  # Shared/overlapping phrases require an explicit range, not last-write-wins.
        box = indexed[box_id]
        for start, end, value in reversed(changes):
            # An edit can cover an entire phrase even when only one glyph changed.
            # Keep existing judgments on equal characters, including outside the edit.
            colors = [box.get('review_kind') or 'match'] * len(box['transcription'])
            for mark in box.get('review_marks', []):
                colors[mark['start']:mark['end']] = [mark['kind']] * (mark['end'] - mark['start'])
            replacement_colors = ['unknown'] * len(value)
            for operation, left, right, new_left, new_right in SequenceMatcher(
                    None, box['transcription'][start:end], value, autojunk=False).get_opcodes():
                if operation == 'equal':
                    replacement_colors[new_left:new_right] = colors[start+left:start+right]
            colors[start:end] = replacement_colors
            box['transcription'] = box['transcription'][:start] + value + box['transcription'][end:]
            marks = []
            for index, kind in enumerate(colors):
                if marks and marks[-1]['kind'] == kind:
                    marks[-1]['end'] = index + 1
                else:
                    marks.append({'start': index, 'end': index + 1, 'kind': kind})
            box['review_marks'] = marks
        accepted[box_id] = changes
    return result, accepted


def advance_refs(refs, changes):
    advanced = []
    for ref in refs:
        start, end = ref['start'], ref['end']
        for left, right, value in changes.get(ref['box_id'], []):
            delta = len(value) - (right - left)
            if right <= ref['start']:
                start += delta
                end += delta
            elif left >= ref['start'] and right <= ref['end']:
                end += delta
            elif left < ref['end'] and right > ref['start']:
                return []
        if end > start:
            advanced.append({**ref, 'start': start, 'end': end})
    return advanced
