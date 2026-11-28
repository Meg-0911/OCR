"""Reference-assisted, persistent review. Geometry is never regenerated here."""
import csv
import hashlib
import json
import re
import threading
from collections import defaultdict
from copy import deepcopy
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from .alignment_links import attach_refs
from .alignment_review import source_glyph
from .nom_dictionary import NomDictionary, key

KIEU_NAME = 'TruyenKieuBanDuyMinhThi1872AnChiPhienAmChuGiaiVaThaoLuan_NguyenDu'


def is_kieu(book):
    return book['name'] == KIEU_NAME


def tokens(text, side):
    if side == 'source':
        return [(c, i, i + 1) for i, c in enumerate(text) if source_glyph(c)]
    # Retain original code-point offsets, including combining accents.
    return [(m[0], m.start(), m.end()) for m in re.finditer(r'[^\W\d_]+(?:[\u0300-\u036f]+[^\W\d_]*)*', text)]


def text_key(text, side):
    return ' '.join(key(t[0]) for t in tokens(text, side))


def read_reference(path):
    text = path.read_text(encoding='utf-8-sig')
    if text.startswith('Thứ tự\t'):
        return [{'position': int(r['Thứ tự']), 'label': r['Số dòng gốc'],
                 'source': r['Chữ Nôm'], 'target': r['Quốc ngữ'], 'note': r['Ghi chú']}
                for r in csv.DictReader(text.splitlines(), delimiter='\t')]
    lines = text.splitlines()
    first_vi = next(i for i, line in enumerate(lines) if line.startswith('Trăm năm'))
    nom = [line.strip() for line in lines[1:first_vi] if line.strip()]
    vi = [line.strip() for line in lines[first_vi:] if line.strip()]
    if len(nom) != len(vi):
        raise ValueError('Hai phần của TruyenKieu.txt không cùng số dòng; cần kiểm tra nguồn.')
    result = []
    for i, (source, target) in enumerate(zip(nom, vi), 1):
        match = re.match(r'^(\d+)(.*)$', source)
        result.append({'position': i, 'label': match[1] if match else '',
                       'source': match[2] if match else '', 'target': target,
                       'note': '' if match else 'Nguồn Nôm lỗi NAME?; không suy đoán chữ.'})
    return result


class ReferenceMatcher:
    def __init__(self, lines):
        self.lines = lines
        self.keys = [{side: text_key(row[side], side) for side in ('source', 'target')} for row in lines]
        self.words = defaultdict(set)
        self.exact = defaultdict(set)
        for i, row in enumerate(self.keys):
            for side in ('source', 'target'):
                if row[side]:
                    self.exact[side, row[side]].add(i)
                for word in set(row[side].split()):
                    self.words[side, word].add(i)

    def match(self, row):
        keys = {side: text_key(row[side], side) for side in ('source', 'target')}
        candidates = set()
        votes = defaultdict(int)
        for side in keys:
            candidates.update(self.exact.get((side, keys[side]), ()))
            for word in set(keys[side].split()):
                for i in self.words.get((side, word), ()):
                    votes[i] += 1
        candidates.update(sorted(votes, key=votes.get, reverse=True)[:32])
        ranked = []
        for i in candidates:
            scores = {s: SequenceMatcher(None, keys[s], self.keys[i][s], autojunk=False).ratio()
                      if keys[s] and self.keys[i][s] else 0 for s in keys}
            # Either script can anchor a line; corroboration breaks repeated-line ties.
            score = max(scores.values()) * .75 + min(scores.values()) * .25
            ranked.append((score, i))
        ranked.sort(reverse=True)
        if not ranked or ranked[0][0] < .70 or len(ranked) > 1 and ranked[0][0] - ranked[1][0] < .045:
            return None
        return {**self.lines[ranked[0][1]], 'confidence': round(ranked[0][0], 3)}


def fingerprint(row):
    value = {k: row.get(k) for k in ('id', 'source', 'target', 'marks', 'source_page_id',
                                    'target_page_id', 'source_refs', 'target_refs')}
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def remap_marks(row, side, start, end, replacement):
    """Keep existing color ranges attached when a token changes length."""
    delta = len(replacement) - (end - start)
    for mark in row.get('marks', []):
        left, right = mark[side + '_start'], mark[side + '_end']
        if left >= end:
            left += delta
        elif left > start:
            left = start
        if right >= end:
            right += delta
        elif right > start:
            right = start + len(replacement)
        mark[side + '_start'], mark[side + '_end'] = left, right
    row[side] = row[side][:start] + replacement + row[side][end:]
    row['marks'] = [m for m in row.get('marks', []) if all(m[s + '_end'] > m[s + '_start'] for s in ('source', 'target'))]


def paint_slot(row, source_range, target_range, kind):
    if source_range[1] <= source_range[0] or target_range[1] <= target_range[0]:
        return
    row.setdefault('marks', []).append(dict(source_start=source_range[0], source_end=source_range[1],
                                           target_start=target_range[0], target_end=target_range[1], kind=kind))


def analyze_row(row, reference, dictionary, *, kieu, page_number):
    cards, corrected, matched = [], 0, 0
    source, target = tokens(row['source'], 'source'), tokens(row['target'], 'target')
    rs = tokens(reference['source'], 'source') if reference else []
    rt = tokens(reference['target'], 'target') if reference else []
    # A missing/ambiguous line or unequal counts requires the entire line, never shifted 1:1.
    reason = ('Thiếu Hán Nôm hoặc Quốc ngữ; cần kiểm tra liên kết dòng' if not source or not target else
              'Không xác định chắc dòng tham khảo' if kieu and not reference else
              'Số chữ khác nhau / nguồn có dị bản' if not source or not target or len(source) != len(target) or
              reference and (len(target) != len(rt) or rs and len(source) != len(rs)) else '')
    if reason:
        return [make_card(row, None, reference, reason)], 0, 0
    # The trailing-t repair is strictly reference-backed and only from page 250.
    if kieu and page_number > 249:
        for token, expected in reversed(list(zip(target, rt))):
            if key(token[0]) == key(expected[0]) + 't':
                remap_marks(row, 'target', token[1], token[2], token[0][:-1])
                corrected += 1
        target = tokens(row['target'], 'target')
    for i, (han, vi) in enumerate(zip(source, target)):
        if kieu:
            vi_equal = key(vi[0]) == key(rt[i][0])
            # A valid alternative Nôm spelling must have the reference reading in the Nôm index.
            han_equal = bool(rs and han[0] == rs[i][0]) or dictionary.matches(han[0], rt[i][0])
            good = vi_equal and han_equal
        else:
            good = dictionary.matches(han[0], vi[0])
        if good:
            paint_slot(row, han[1:], vi[1:], 'match')
            matched += 1
        else:
            reason = 'Khác nguồn tham khảo' if kieu else 'Cần đối chiếu âm Quốc ngữ trong từ điển Nôm'
            if kieu and not rs:
                reason = 'Nguồn thiếu chữ Nôm; cần tra cứu'
            cards.append(make_card(row, i, reference, reason))
    return cards, corrected, matched


def make_card(row, index, reference, reason):
    ranges = {}
    for side in ('source', 'target'):
        parts = tokens(row[side], side)
        ranges[side] = list(parts[index][1:]) if index is not None else [0, len(row[side])]
    return {'row_id': row['id'], 'index': index, 'reference': reference, 'reason': reason,
            'ranges': ranges, 'sentence_id': row['sentence_id']}


class QuickReview:
    def __init__(self, store):
        self.store = store
        self.dictionary = NomDictionary(store.data / 'dictionaries')
        self.threads = {}
        self.guard = threading.Lock()
        self.exports = {}
        self.export_errors = {}
        with store.db() as db:
            db.executescript('''
              CREATE TABLE IF NOT EXISTS quick_jobs(book_id TEXT PRIMARY KEY, payload TEXT NOT NULL);
              CREATE TABLE IF NOT EXISTS quick_cards(id TEXT PRIMARY KEY, book_id TEXT NOT NULL,
                row_id TEXT NOT NULL, payload TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending');
              CREATE INDEX IF NOT EXISTS quick_cards_book ON quick_cards(book_id,state);
              CREATE TABLE IF NOT EXISTS quick_decisions(id INTEGER PRIMARY KEY, book_id TEXT NOT NULL,
                row_id TEXT NOT NULL, before_row TEXT NOT NULL, after_hash TEXT NOT NULL,
                card TEXT NOT NULL, created_at TEXT NOT NULL, undone INTEGER NOT NULL DEFAULT 0);
            ''')
            for row in db.execute('SELECT * FROM quick_jobs').fetchall():
                payload = json.loads(row['payload'])
                if payload.get('status') == 'running':
                    payload.update(status='interrupted', error='Phiên quét bị ngắt. Bấm quét để tiếp tục; quyết định đã lưu vẫn được giữ.')
                    db.execute('UPDATE quick_jobs SET payload=? WHERE book_id=?', (json.dumps(payload), row['book_id']))

    def job(self, book_id):
        with self.store.db() as db:
            row = db.execute('SELECT payload FROM quick_jobs WHERE book_id=?', (book_id,)).fetchone()
        return json.loads(row[0]) if row else {'status': 'idle'}

    def set_job(self, book_id, payload):
        with self.store.db() as db:
            db.execute('INSERT INTO quick_jobs VALUES (?,?) ON CONFLICT(book_id) DO UPDATE SET payload=excluded.payload',
                       (book_id, json.dumps(payload, ensure_ascii=False)))

    def start(self, book_id):
        with self.guard:
            if self.threads.get(book_id) and self.threads[book_id].is_alive():
                return self.job(book_id)
            self.set_job(book_id, {'status': 'running', 'processed': 0})
            thread = threading.Thread(target=self.scan, args=(book_id,), daemon=True)
            self.threads[book_id] = thread
            thread.start()
        return self.job(book_id)

    def scan(self, book_id):
        try:
            with self.store.lock:
                self.store.reconcile_deleted_source_boxes(book_id)
                book = self.store.book(book_id)
                pages = self.store.pages(book_id)
                original = attach_refs(self.store.alignment_rows(book_id), pages)
                described = {r['id']: r for r in self.store.describe_alignments(book_id)}
                versions = {p['id']: p['version'] for p in pages}
            if not self.dictionary.index:
                raise ValueError('Chưa cài từ điển Nôm. Chạy python -m backend.setup_nom_dictionary rồi khởi động lại backend.')
            kieu = is_kieu(book)
            matcher = ReferenceMatcher(read_reference(self.store.root / 'TruyenKieu.txt')) if kieu else None
            rows = deepcopy(original)
            cards, corrected, matched, skipped = [], 0, 0, 0
            with self.store.db() as db:
                decisions = {r['row_id']: r['after_hash'] for r in db.execute(
                    'SELECT row_id,after_hash FROM quick_decisions WHERE book_id=? AND undone=0 ORDER BY id', (book_id,))}
                old_cards = [dict(r) for r in db.execute('SELECT * FROM quick_cards WHERE book_id=?', (book_id,))]
            old_by_row = defaultdict(list)
            old_by_id = {c['id']: c for c in old_cards}
            for card in old_cards:
                old_by_row[card['row_id']].append(card)
            for n, row in enumerate(rows):
                info = described.get(row['id'], {})
                if info.get('duplicate_of') or info.get('review_state') == 'excluded':
                    skipped += 1
                    continue
                if decisions.get(row['id']) == fingerprint(row):
                    cards.extend(old_by_row[row['id']])
                    continue
                page_number = int(row['sentence_id'].rsplit('.', 2)[1])
                reference = matcher.match(row) if matcher else None
                found, repaired, good = analyze_row(row, reference, self.dictionary, kieu=kieu, page_number=page_number)
                corrected += repaired
                matched += good
                # Compact repeated overlays from earlier scans without losing last-write color order.
                seen = set()
                row['marks'] = list(reversed([m for m in reversed(row.get('marks', []))
                    if (signature := tuple(m.items())) not in seen and not seen.add(signature)]))
                for card in found:
                    card['fingerprint'] = fingerprint(row)
                    card['page_number'] = page_number
                    card_id = hashlib.sha256(f"{book_id}:{row['id']}:{card['index']}".encode()).hexdigest()[:32]
                    old_card = old_by_id.get(card_id)
                    state = (old_card['state'] if old_card and json.loads(old_card['payload']).get('fingerprint') == card['fingerprint'] else 'pending')
                    cards.append({'id': card_id, 'book_id': book_id, 'row_id': row['id'],
                                  'payload': json.dumps(card, ensure_ascii=False), 'state': state})
                if n % 100 == 0:
                    self.set_job(book_id, {'status': 'running', 'processed': n, 'total': len(rows)})
            with self.store.lock:
                if self.store.book(book_id)['alignment_version'] != book['alignment_version'] or any(
                    versions.get(p['id']) != p['version'] for p in self.store.pages(book_id, include_export_boxes=False)
                ):
                    raise ValueError('Dữ liệu đã đổi trong lúc quét. Bấm quét lại để dùng bản mới; chưa áp dụng kết quả cũ.')
                self.save_rows(book_id, original, rows)
                saved = {r['id']: r for r in rows}
                for card in cards:
                    payload = json.loads(card['payload'])
                    payload['fingerprint'] = fingerprint(saved[card['row_id']])
                    card['payload'] = json.dumps(payload, ensure_ascii=False)
                with self.store.db() as db:
                    db.execute('DELETE FROM quick_cards WHERE book_id=?', (book_id,))
                    db.executemany('INSERT INTO quick_cards VALUES (:id,:book_id,:row_id,:payload,:state)', cards)
            self.set_job(book_id, {'status': 'completed', 'processed': len(rows), 'total': len(rows),
                                  'matched': matched, 'corrected': corrected, 'skipped': skipped,
                                  'cards': len(cards), 'mode': 'reference' if kieu else 'dictionary',
                                  'finished_at': datetime.now(timezone.utc).isoformat()})
        except Exception as error:
            self.set_job(book_id, {'status': 'failed', 'error': str(error)})

    def save_rows(self, book_id, before, rows, *, publish=True):
        # Existing propagation preserves box coordinates and stable row IDs.
        self.store.sync_alignment_edits(book_id, before, rows)
        if publish:
            self.store.sync_labels(book_id)
        else:
            self.store.prepare_label_checkpoint(book_id)
            # SQLite is already saved. Batch costly XLSX/label projection while the user reviews.
            with self.guard:
                if old := self.exports.get(book_id):
                    old.cancel()
                timer = threading.Timer(12, self.publish, args=(book_id,))
                timer.daemon = True
                self.exports[book_id] = timer
                timer.start()

    def publish(self, book_id):
        try:
            self.store.sync_labels(book_id)
            self.export_errors.pop(book_id, None)
        except Exception as error:
            self.export_errors[book_id] = 'Đã lưu quyết định trong SQLite, nhưng chưa cập nhật tệp xuất: ' + str(error)

    def close(self):
        for thread in list(self.threads.values()):
            thread.join()
        for book_id, timer in list(self.exports.items()):
            timer.cancel()
            if timer.is_alive():
                timer.join()
            self.publish(book_id)

    def status(self, book_id, include_deferred=False):
        with self.store.lock:
            if self.job(book_id).get('status') != 'running' and self.store.reconcile_deleted_source_boxes(book_id):
                self.store.sync_labels(book_id)
            rows = {row['id']: row for row in self.store.alignment_rows(book_id)}
            with self.store.db() as db:
                # Deleted OCR rows must not leave an uneditable card at the front.
                obsolete = [(record['id'],) for record in db.execute(
                    'SELECT id,row_id FROM quick_cards WHERE book_id=?', (book_id,)) if record['row_id'] not in rows]
                db.executemany('DELETE FROM quick_cards WHERE id=?', obsolete)
                counts = dict(db.execute('SELECT state,count(*) FROM quick_cards WHERE book_id=? GROUP BY state', (book_id,)).fetchall())
                can_undo = db.execute('SELECT 1 FROM quick_decisions WHERE book_id=? AND undone=0 LIMIT 1', (book_id,)).fetchone() is not None
                states = ('pending', 'deferred') if include_deferred else ('pending',)
                record = db.execute('SELECT * FROM quick_cards WHERE book_id=? AND state IN (' +
                                    ','.join('?' for _ in states) + ') ORDER BY rowid LIMIT 1', (book_id, *states)).fetchone()
            card = None
            if record:
                card = json.loads(record['payload'])
                card.update(id=record['id'], state=record['state'])
                row = rows.get(record['row_id'])
                if row:
                    card['row'] = row
                    card['stale'] = fingerprint(row) != card['fingerprint']
                    for side in ('source', 'target'):
                        a, b = card['ranges'][side]
                        card[side] = row[side][a:b]
                    index = card['index']
                    ref = card.get('reference')
                    for side in ('source', 'target'):
                        parts = tokens(ref[side], side) if ref else []
                        card['expected_' + side] = (parts[index][0] if index is not None and index < len(parts)
                                                    else ref[side] if ref and index is None else '')
                    query = card['expected_target'] or card['target']
                    card['query'] = query if index is not None else ''
                else:
                    card['stale'] = True
            return {'job': self.job(book_id), 'counts': counts, 'card': card, 'can_undo': can_undo,
                    'dictionary_ready': bool(self.dictionary.index), 'is_kieu': is_kieu(self.store.book(book_id)),
                    'export_error': self.export_errors.get(book_id)}

    def decide(self, book_id, card_id, action, expected, source=None, target=None):
        if self.job(book_id)['status'] == 'running':
            raise ValueError('Đợi quét xong trước khi lưu quyết định.')
        with self.store.lock:
            with self.store.db() as db:
                record = db.execute('SELECT * FROM quick_cards WHERE id=? AND book_id=?', (card_id, book_id)).fetchone()
            if not record or record['state'] == 'done':
                raise ValueError('Thẻ đã được xử lý. Tải lại hàng đợi.')
            card = json.loads(record['payload'])
            before = self.store.alignment_rows(book_id)
            rows = deepcopy(before)
            row = next((r for r in rows if r['id'] == card['row_id']), None)
            if not row or fingerprint(row) != expected or expected != card['fingerprint']:
                raise ValueError('Chữ hoặc màu đã thay đổi ở màn hình khác. Quét lại trước khi duyệt.')
            if action == 'defer':
                with self.store.db() as db:
                    db.execute('INSERT INTO quick_decisions(book_id,row_id,before_row,after_hash,card,created_at) VALUES (?,?,?,?,?,?)',
                               (book_id, row['id'], json.dumps(row, ensure_ascii=False), fingerprint(row),
                                json.dumps({**dict(record), 'action': 'defer'}, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
                    # Put it at the end so "include deferred" never traps the user on one card.
                    db.execute('DELETE FROM quick_cards WHERE id=?', (card_id,))
                    db.execute('INSERT INTO quick_cards VALUES (?,?,?,?,?)',
                               (card_id, book_id, card['row_id'], record['payload'], 'deferred'))
                return
            if action not in ('match', 'mismatch', 'unknown'):
                raise ValueError('Quyết định không hợp lệ.')
            old_row = deepcopy(row)
            with self.store.db() as db:
                row_cards = [dict(r) for r in db.execute('SELECT * FROM quick_cards WHERE book_id=? AND row_id=?',
                                                       (book_id, row['id']))]
            ranges = deepcopy(card['ranges'])
            changes = {}
            for side, replacement in (('source', source), ('target', target)):
                if replacement is None:
                    continue
                if not replacement.strip() or len(replacement) > 30000:
                    raise ValueError('Nội dung thay thế không được rỗng hoặc quá dài.')
                if side == 'source' and card['index'] is not None and len(tokens(replacement, side)) != 1:
                    raise ValueError('Thẻ 1–1 chỉ thay một chữ Nôm; dùng màn hình căn chỉnh để đổi số chữ.')
                if side == 'target' and card['index'] is not None and len(tokens(replacement, side)) != 1:
                    raise ValueError('Thẻ 1–1 chỉ thay một âm Quốc ngữ.')
                start, end = ranges[side]
                remap_marks(row, side, start, end, replacement)
                ranges[side][1] = start + len(replacement)
                changes[side] = (start, end, len(replacement) - (end - start))
            paint_slot(row, ranges['source'], ranges['target'], action)
            if not row['source'].strip() or not row['target'].strip():
                raise ValueError('Dòng thiếu một vế. Bổ sung nội dung hoặc mở căn chỉnh đầy đủ; có thể để sau.')
            self.save_rows(book_id, before, rows, publish=False)
            # Propagation may advance refs. Use the actual saved row for all subsequent cards.
            row = next(r for r in rows if r['id'] == card['row_id'])
            digest = fingerprint(row)
            with self.store.db() as db:
                db.execute('INSERT INTO quick_decisions(book_id,row_id,before_row,after_hash,card,created_at) VALUES (?,?,?,?,?,?)',
                           (book_id, row['id'], json.dumps(old_row, ensure_ascii=False), digest,
                            json.dumps({**dict(record), 'row_cards': row_cards}, ensure_ascii=False), datetime.now(timezone.utc).isoformat()))
                db.execute("UPDATE quick_cards SET state='done' WHERE id=?", (card_id,))
                for other in db.execute('SELECT * FROM quick_cards WHERE book_id=? AND row_id=?', (book_id, row['id'])).fetchall():
                    payload = json.loads(other['payload'])
                    payload['fingerprint'] = digest
                    for side, (a, b, delta) in changes.items():
                        left, right = payload['ranges'][side]
                        if left >= b:
                            left += delta
                            right += delta
                        elif left == a and right == b:
                            right += delta
                        payload['ranges'][side] = [left, right]
                    db.execute('UPDATE quick_cards SET payload=? WHERE id=?', (json.dumps(payload, ensure_ascii=False), other['id']))

    def undo(self, book_id):
        if self.job(book_id)['status'] == 'running':
            raise ValueError('Đợi quét xong trước khi hoàn tác.')
        with self.store.lock:
            with self.store.db() as db:
                decision = db.execute('SELECT * FROM quick_decisions WHERE book_id=? AND undone=0 ORDER BY id DESC LIMIT 1', (book_id,)).fetchone()
            if not decision:
                raise ValueError('Chưa có quyết định để hoàn tác.')
            before = self.store.alignment_rows(book_id)
            current = next((r for r in before if r['id'] == decision['row_id']), None)
            if not current or fingerprint(current) != decision['after_hash']:
                raise ValueError('Dòng đã thay đổi sau quyết định này; không thể hoàn tác đè lên chỉnh sửa mới.')
            record = json.loads(decision['card'])
            if record.get('action') == 'defer':
                with self.store.db() as db:
                    db.execute('UPDATE quick_decisions SET undone=1 WHERE id=?', (decision['id'],))
                    self.restore_front_card(db, record, current)
                return
            restored = json.loads(decision['before_row'])
            # Use current refs so reverse text propagation can locate the edited range.
            for side in ('source', 'target'):
                if current.get(side + '_refs'):
                    restored[side + '_refs'] = current[side + '_refs']
            rows = [restored if r['id'] == restored['id'] else r for r in deepcopy(before)]
            self.save_rows(book_id, before, rows, publish=False)
            with self.store.db() as db:
                db.execute('UPDATE quick_decisions SET undone=1 WHERE id=?', (decision['id'],))
                db.execute('DELETE FROM quick_cards WHERE book_id=? AND row_id=?', (book_id, restored['id']))
                for old_card in record.get('row_cards', [record]):
                    payload = json.loads(old_card['payload'])
                    payload['fingerprint'] = fingerprint(restored)
                    db.execute('INSERT INTO quick_cards VALUES (?,?,?,?,?)',
                               (old_card['id'], book_id, restored['id'], json.dumps(payload, ensure_ascii=False), old_card['state']))
                self.restore_front_card(db, record, restored)

    @staticmethod
    def restore_front_card(db, record, row):
        """Back must actually display the undone card, even when deferred cards are hidden."""
        payload = json.loads(record['payload'])
        payload['fingerprint'] = fingerprint(row)
        first = db.execute('SELECT COALESCE(MIN(rowid),0)-1 FROM quick_cards').fetchone()[0]
        db.execute('DELETE FROM quick_cards WHERE id=?', (record['id'],))
        db.execute('INSERT INTO quick_cards(rowid,id,book_id,row_id,payload,state) VALUES (?,?,?,?,?,?)',
                   (first, record['id'], record['book_id'], row['id'], json.dumps(payload, ensure_ascii=False), 'pending'))
