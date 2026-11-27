"""Repair the two legacy Kieu header shifts, with evidence checks and a backup."""
import argparse
import hashlib
import json
import sqlite3
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from backend.alignment_links import ref_text
from backend.export_labels import select_label_pages
from backend.quick_review import KIEU_NAME, ReferenceMatcher, fingerprint, make_card, read_reference


def plan_repair(rows, pages, originals, protected):
    rows, pages = deepcopy(rows), deepcopy(pages)
    changed, removed = set(), set()
    for number in (352, 354):
        source = next((p for p in pages if p['number'] == number), None)
        if not source:
            continue
        local = sorted([r for r in rows if r.get('source_page_id') == source['id']],
                       key=lambda r: int(r['sentence_id'].rsplit('.', 1)[1]))
        if not local or not local[0]['target'].startswith('Truyện Kiều - bản '):
            continue
        target = next(p for p in pages if p['id'] == local[0]['target_page_id'])
        old_targets = originals[target['id']]['vi_text_lines']
        live_targets = [b['transcription'] for b in target['vi_boxes']]
        live_sources = [b['transcription'] for b in source['boxes']]
        if (len(set(live_sources)) != len(live_sources) or len(local) != len(live_sources) + 1
                or len(live_sources) != len(live_targets) or old_targets[1:] != live_targets
                or local[0]['target'] != old_targets[0]):
            raise ValueError(f'Trang {number}: không chứng minh được lệch một tiêu đề.')
        noise = [r for r in local if r['source'] not in live_sources]
        if len(noise) != 1:
            raise ValueError(f'Trang {number}: dòng Nôm thừa không duy nhất.')
        noise, = noise
        export = next((b for b in source['export_boxes'] if b.get('alignment_id') == noise['id']), None)
        live_ids = {b['id'] for b in source['boxes']}
        if (not export or noise.get('source_refs') or not noise.get('page_linked')
                or not any(b['id'] not in live_ids and b['transcription'] == noise['source']
                           and b['points'] == export['points'] for b in originals[source['id']]['boxes'])):
            raise ValueError(f'Trang {number}: không xác minh được box Nôm đã xóa.')
        surviving = [r for r in local if r['id'] != noise['id']]
        if [r['source'] for r in surviving] != live_sources:
            raise ValueError(f'Trang {number}: thứ tự Nôm đã được sửa riêng.')
        affected = [noise] + [r for r, text in zip(surviving, live_targets) if r['target'] != text]
        for row in affected:
            old_index = local.index(row)
            if (row['id'] in protected or row.get('marks') or not row.get('page_linked')
                    or row['target'] != old_targets[old_index]
                    or row.get('target_page_id') != target['id']):
                raise ValueError(f"{row['sentence_id']}: có chỉnh sửa riêng; không tự ghi đè.")
        for index, row in enumerate(surviving):
            if row in affected:
                box = target['vi_boxes'][index]
                row.update(target=box['transcription'], target_line_index=index,
                           target_refs=[{'box_id': box['id'], 'start': 0, 'end': len(box['transcription'])}])
                assert ref_text(row['target_refs'], target['vi_boxes']) == row['target']
                changed.add(row['id'])
            row['source_line_index'] = index
        removed.add(noise['id'])
        source['export_boxes'] = [b for b in source['export_boxes'] if b.get('alignment_id') != noise['id']]
        for index, box in enumerate(source['export_boxes'], 1):
            box['export_order'] = index
    return [r for r in rows if r['id'] not in removed], pages, changed, removed


def repair(root, apply=False):
    path = root / 'backend/data/.workspace/workspace.sqlite3'
    with sqlite3.connect(path, timeout=30) as db:
        db.row_factory = sqlite3.Row
        book, = db.execute('SELECT id FROM books WHERE name=?', (KIEU_NAME,)).fetchall()
        book_id = book['id']
        original_payload = db.execute('SELECT rows FROM alignments WHERE book_id=?', (book_id,)).fetchone()[0]
        before = json.loads(original_payload)
        pages = [dict(p) for p in db.execute('SELECT * FROM pages WHERE book_id=?', (book_id,))]
        versions = {p['id']: p['version'] for p in pages}
        for page in pages:
            for field in ('boxes', 'vi_boxes', 'export_boxes', 'ocr_languages'):
                page[field] = json.loads(page[field]) or []
        originals = {p['id']: json.loads(db.execute('SELECT result FROM ocr_results WHERE page_id=? '
                    'ORDER BY created_at DESC,rowid DESC LIMIT 1', (p['id'],)).fetchone()[0])
                     for p in pages if p['number'] in (352, 353, 354, 355)}
        protected = {r[0] for r in db.execute('SELECT row_id FROM quick_decisions WHERE book_id=?', (book_id,))}
        protected.update(r[0] for r in db.execute("SELECT row_id FROM quick_cards WHERE book_id=? AND state!='pending'", (book_id,)))
        rows, updated_pages, changed, removed = plan_repair(before, pages, originals, protected)
        # Keep the strict export gate: the entire book must pass before saving.
        select_label_pages(updated_pages, [r for r in rows if r.get('reviewed') and r['source'].strip() and r['target'].strip()])
        report = {'changed_pairs': [r['sentence_id'] for r in rows if r['id'] in changed],
                  'removed_noise': [r['sentence_id'] for r in before if r['id'] in removed], 'export_validation': 'passed'}
        if not apply or not (changed or removed):
            return report
        folder = path.parent / 'backups'
        folder.mkdir(exist_ok=True)
        backup = folder / ('before-kieu-header-repair-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S') + '.sqlite3')
        with sqlite3.connect(backup) as dest:
            db.backup(dest)
        matcher = ReferenceMatcher(read_reference(root / 'TruyenKieu.txt'))
        db.execute('BEGIN IMMEDIATE')
        latest_protected = {r[0] for r in db.execute('SELECT row_id FROM quick_decisions WHERE book_id=?', (book_id,))}
        latest_protected.update(r[0] for r in db.execute(
            "SELECT row_id FROM quick_cards WHERE book_id=? AND state!='pending'", (book_id,)))
        job = db.execute('SELECT payload FROM quick_jobs WHERE book_id=?', (book_id,)).fetchone()
        if latest_protected & (changed | removed) or job and json.loads(job[0]).get('status') == 'running':
            raise ValueError('Đang quét hoặc vừa có quyết định mới; chưa thay đổi dữ liệu.')
        if original_payload != db.execute('SELECT rows FROM alignments WHERE book_id=?', (book_id,)).fetchone()[0] or any(
                versions[p['id']] != p['version'] for p in db.execute('SELECT id,version FROM pages WHERE book_id=?', (book_id,))):
            raise ValueError('Dữ liệu vừa đổi; chạy lại bản xem trước.')
        db.execute('UPDATE alignments SET rows=? WHERE book_id=?', (json.dumps(rows, ensure_ascii=False), book_id))
        for old, page in zip(pages, updated_pages):
            if page['export_boxes'] != old['export_boxes']:
                db.execute('UPDATE pages SET export_boxes=?,version=version+1 WHERE id=?',
                           (json.dumps(page['export_boxes'], ensure_ascii=False), page['id']))
        for row_id in changed | removed:
            db.execute('DELETE FROM quick_cards WHERE book_id=? AND row_id=?', (book_id, row_id))
        for row in rows:
            if row['id'] not in changed:
                continue
            card = make_card(row, None, matcher.match(row), 'Đã sửa liên kết tiêu đề cũ; cần đối chiếu dòng')
            card.update(fingerprint=fingerprint(row), page_number=int(row['sentence_id'].rsplit('.', 2)[1]))
            card_id = hashlib.sha256(f"{book_id}:{row['id']}:None".encode()).hexdigest()[:32]
            db.execute('INSERT INTO quick_cards VALUES (?,?,?,?,?)',
                       (card_id, book_id, row['id'], json.dumps(card, ensure_ascii=False), 'pending'))
        db.commit()
        report['backup'] = str(backup)
        return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apply', action='store_true')
    options = parser.parse_args()
    print(json.dumps(repair(Path(__file__).resolve().parents[1], options.apply), ensure_ascii=False, indent=2))
