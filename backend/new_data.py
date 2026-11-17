"""Replace results of mandatory PDF books with complete aligned input snapshots."""
import hashlib
import io
import json
import math
import re
import shutil
import threading
import unicodedata
from collections import defaultdict
from pathlib import Path
from uuid import uuid4, uuid5, NAMESPACE_URL

import pymupdf
from openpyxl import load_workbook
from PIL import Image

from .alignment_review import source_glyph

FORMAT = 'mandatory-book-phrases-v3'


def book_key(name):
    name = re.sub(r'\.(pdf|xlsx)$', '', name, flags=re.I)
    name = re.sub(r'[_\s-]+Y$', '', name, flags=re.I)
    return ' '.join(unicodedata.normalize('NFC', name).casefold().replace('_', ' ').split())


def correctness_bits(value, source):
    size = sum(source_glyph(char) for char in source)
    if value is None or value == '':
        return ''
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not value.is_integer():
            raise ValueError('Correctness phải là chuỗi nhị phân.')
        value = str(int(value)).zfill(size)
    value = str(value).strip()
    if len(value) != size or set(value) - {'0', '1'}:
        raise ValueError(f'Correctness phải có {size} bit, nhận được {value!r}.')
    return value


def read_workbook(path, allowed=None):
    result = []
    workbook = load_workbook(path, read_only=True, data_only=True)
    try:
        for sheet in workbook:
            iterator = sheet.iter_rows(values_only=True)
            headers = [str(value or '').strip().casefold() for value in next(iterator, ())]
            required = {'patch id', 'vietnamese', 'label', 'correctness'}
            if not required.issubset(headers):
                raise ValueError(f'{sheet.title}: thiếu cột {", ".join(sorted(required - set(headers)))}.')
            columns = {name: headers.index(name) for name in required}
            for number, values in enumerate(iterator, 2):
                if not any(value is not None for value in values):
                    continue
                fields = {name: values[index] if index < len(values) else None for name, index in columns.items()}
                patch = str(fields['patch id'] or '').strip()
                match = re.fullmatch(r'(.+)\.(\d+)\.(\d+)(?:\.(?:jpg|png))?', patch, re.I)
                if not match:
                    raise ValueError(f'{sheet.title}:{number}: Patch ID không hợp lệ: {patch!r}.')
                if allowed is not None and book_key(match[1]) not in allowed:
                    continue
                source = str(fields['label'] or '').strip()
                target = str(fields['vietnamese'] or '').strip()
                result.append({'patch_id': patch, 'book': match[1], 'page': int(match[2]),
                               'line': int(match[3]), 'source': source, 'target': target,
                               'correctness': correctness_bits(fields['correctness'], source)})
    finally:
        workbook.close()
    return result


def read_labels(path):
    if path is None:
        raise ValueError('Thiếu Label.txt cho sách khớp thư mục raw_data/.')
    result = {}
    with path.open(encoding='utf-8-sig') as stream:
        for number, line in enumerate(stream, 1):
            if not line.strip():
                continue
            name, separator, payload = line.rstrip('\r\n').partition('\t')
            if not separator:
                raise ValueError(f'{path.name}:{number}: thiếu dấu TAB giữa tên ảnh và JSON.')
            key = Path(name.replace('\\', '/')).name
            if key in result:
                raise ValueError(f'{path.name}:{number}: tên ảnh bị trùng: {key}.')
            result[key] = json.loads(payload)
    return result


def label_file(folder, filename):
    return next((path for path in (folder / 'images' / filename, folder / filename) if path.is_file()), None)


def validate_points(points, width, height):
    if not isinstance(points, list) or len(points) != 4:
        raise ValueError('Nhãn cần bốn điểm tọa độ.')
    for point in points:
        if not isinstance(point, (list, tuple)) or len(point) != 2 or not all(isinstance(value, (int, float)) for value in point):
            raise ValueError('Tọa độ nhãn không hợp lệ.')
        if not 0 <= point[0] <= width or not 0 <= point[1] <= height:
            raise ValueError('Nhãn vượt ngoài ảnh gốc. Giữ ảnh cùng kích thước với dữ liệu nhãn.')
    turns = [(points[(i+1)%4][0]-points[i][0])*(points[(i+2)%4][1]-points[(i+1)%4][1])
             -(points[(i+1)%4][1]-points[i][1])*(points[(i+2)%4][0]-points[(i+1)%4][0]) for i in range(4)]
    if not (all(turn > 0 for turn in turns) or all(turn < 0 for turn in turns)):
        raise ValueError('Box dòng phải là tứ giác lồi có diện tích lớn hơn 0.')
    return points


def phrase_box(record, points, row_id, order):
    glyphs = [index for index, char in enumerate(record['source']) if source_glyph(char)]
    marks = [{'start': index, 'end': index + 1, 'kind': 'match' if bit == '1' else 'mismatch'}
             for index, bit in zip(glyphs, record['correctness'])]
    horizontal = max(p[0] for p in points)-min(p[0] for p in points) >= max(p[1] for p in points)-min(p[1] for p in points)
    group = f'new-line-{row_id}'
    return {'id': group, 'transcription': record['source'], 'points': points,
            'review_order': order, 'review_kind': 'match' if marks else 'unknown', 'review_marks': marks,
            'alignment_id': row_id, 'export_group': group, 'export_order': order,
            'export_character_order': 0, 'box_axis': 'horizontal' if horizontal else 'vertical'}


class NewData:
    def __init__(self, store):
        self.store = store
        self.sync_lock = threading.Lock()
        self.before_replace = lambda book_id: None

    def image(self, page_id):
        with self.store.db() as db:
            row = db.execute('SELECT image_path FROM new_data_pages WHERE page_id=?', (page_id,)).fetchone()
        return self.store.root / row['image_path'].replace('\\', '/') if row else None

    def summary(self, book_id):
        with self.store.db() as db:
            return dict(db.execute('''SELECT COUNT(DISTINCT p.id) AS new_data_pages,
                COUNT(r.patch_id) AS new_data_lines FROM pages p
                JOIN new_data_pages n ON n.page_id=p.id
                LEFT JOIN new_data_rows r ON r.page_id=p.id WHERE p.book_id=?''', (book_id,)).fetchone())

    def sync(self, errors):
        with self.sync_lock:
            self._sync(errors)

    def _sync(self, errors):
        store = self.store
        books = defaultdict(list)
        for book in store.books():
            books[book_key(book['filename'])].append(book)
        roots = [path for path in (store.data / 'new', store.root / 'data' / 'new') if path.is_dir()]
        records, folders, failed = defaultdict(dict), defaultdict(list), set()
        for root in roots:
            for folder in root.iterdir():
                if folder.is_dir() and book_key(folder.name) in books and (folder / 'images').is_dir():
                    folders[book_key(folder.name)].append(folder)
            for path in sorted(root.rglob('*.xlsx')):
                if path.name.casefold() == 'ned_summary.xlsx' or path.name.startswith('~$'):
                    continue
                key = book_key(path.name)
                candidates = {name for name in books if key == name or key.startswith(name + '.')}
                if not candidates:
                    continue  # Extra shared material is intentionally outside this workspace.
                try:
                    staged = defaultdict(dict)
                    for record in read_workbook(path, candidates):
                        name = book_key(record['book'])
                        identity = record['page'], record['line']
                        old = staged[name].get(identity) or records[name].get(identity)
                        if old and old != record:
                            raise ValueError(f"Patch ID trùng với nội dung khác: {record['patch_id']}.")
                        staged[name][identity] = record
                    for name, rows in staged.items():
                        records[name].update(rows)
                except Exception as error:
                    failed.update(candidates)
                    errors.append({'filename': str(path.relative_to(store.root)), 'message': str(error)})
        for name, incoming in records.items():
            if name in failed:
                continue
            try:
                if len(books[name]) != 1 or len(folders[name]) != 1:
                    raise ValueError('Cần đúng một PDF bắt buộc và một thư mục new khớp toàn bộ tên sách.')
                snapshot = self.prepare(books[name][0], folders[name][0], incoming)
                with store.db() as db:
                    old = db.execute('SELECT fingerprint,revision FROM new_data_books WHERE book_id=?', (snapshot['book']['id'],)).fetchone()
                if old and old['fingerprint'] == snapshot['fingerprint']:
                    with store.lock:
                        assets = self.materialize_images(snapshot, old['revision'])
                        with store.db() as db:
                            for number, path in assets.items():
                                db.execute('UPDATE new_data_pages SET image_path=? WHERE page_id IN (SELECT id FROM pages WHERE book_id=? AND number=?)',
                                           (path, snapshot['book']['id'], number))
                    continue
                self.before_replace(snapshot['book']['id'])
                self.replace(snapshot)
            except Exception as error:
                errors.append({'filename': books[name][0]['filename'], 'message': str(error)})

    def prepare(self, book, folder, incoming):
        store = self.store
        labels = read_labels(label_file(folder, 'Label.txt'))
        images = defaultdict(list)
        for path in (folder / 'images').iterdir():
            if (path.suffix.casefold() in ('.jpg', '.jpeg', '.png') and path.is_file()
                    and (match := re.fullmatch(r'(.+)\.(\d+)', path.stem))
                    and book_key(match[1]) == book_key(book['filename'])):
                images[int(match[2])].append(path)
        with pymupdf.open(store.data / 'raw_data' / book['filename']) as pdf:
            dimensions = [(math.ceil(page.rect.width * min(1.5, 2400 / max(page.rect.width, page.rect.height))),
                           math.ceil(page.rect.height * min(1.5, 2400 / max(page.rect.width, page.rect.height)))) for page in pdf]
        pages = defaultdict(list)
        for record in incoming.values():
            if not 1 <= record['page'] <= len(dimensions):
                raise ValueError(f"{record['patch_id']}: số trang nằm ngoài PDF bắt buộc ({len(dimensions)} trang).")
            pages[record['page']].append(record)
        prepared, signature = {}, []
        for number, rows in sorted(pages.items()):
            rows.sort(key=lambda row: row['line'])
            if len(images[number]) != 1:
                raise ValueError(f'Thiếu hoặc trùng ảnh trang {number:03d}; chưa thay kết quả cuốn này.')
            image = images[number][0]
            if image.name not in labels:
                raise ValueError(f'Thiếu nhãn dòng cho {image.name}.')
            with Image.open(image) as picture:
                width, height = picture.size
            points = []
            for record in rows:
                if record['line'] >= len(labels[image.name]):
                    raise ValueError(f"{record['patch_id']}: không có box dòng tương ứng (đếm từ 0).")
                points.append(validate_points(labels[image.name][record['line']]['points'], width, height))
            prepared[number] = {'rows': rows, 'points': points, 'width': width, 'height': height,
                                'image': image.relative_to(store.root).as_posix()}
            with image.open('rb') as stream:
                digest = hashlib.file_digest(stream, 'sha256').hexdigest()
            prepared[number]['digest'] = digest
            signature.append([number, rows, points, width, height, image.name, digest])
        fingerprint = hashlib.sha256(json.dumps([FORMAT, dimensions, signature], ensure_ascii=False, sort_keys=True).encode()).hexdigest()
        return {'book': book, 'dimensions': dimensions, 'pages': prepared, 'fingerprint': fingerprint}

    def materialize_images(self, snapshot, revision):
        """The active book reads immutable images, never files being copied into new/."""
        store = self.store
        folder = store.local / 'book-assets' / snapshot['book']['id'] / revision
        if not folder.resolve().is_relative_to(store.data.resolve()):
            raise ValueError('Thư mục ảnh không thuộc workspace.')
        folder.mkdir(parents=True, exist_ok=True)
        assets = {}
        for number, page in snapshot['pages'].items():
            destination = folder / f'{number:03d}.jpg'
            if not destination.is_file():
                content = (store.root / page['image']).read_bytes()
                if hashlib.sha256(content).hexdigest() != page['digest']:
                    raise ValueError('Ảnh nguồn thay đổi trong khi đồng bộ. Chép xong toàn bộ dữ liệu rồi quét lại.')
                temporary = destination.with_suffix('.tmp')
                if Path(page['image']).suffix.lower() in ('.jpg', '.jpeg'):
                    temporary.write_bytes(content)
                else:
                    with Image.open(io.BytesIO(content)) as picture:
                        picture.convert('RGB').save(temporary, format='JPEG', quality=95)
                temporary.replace(destination)
            assets[number] = destination.relative_to(store.root).as_posix()
        return assets

    def clear_cache(self, book_id, page_ids):
        store = self.store
        targets = [store.book_dir(book_id), store.data / 'processed_images' / book_id,
                   store.data / 'output_alignment' / book_id, store.local / 'ocr-images' / book_id,
                   *[store.local / 'ocr' / page_id for page_id in page_ids]]
        for target in targets:
            resolved = target.resolve()
            if not resolved.is_relative_to(store.data.resolve()) or resolved == store.data.resolve():
                raise ValueError('Đường dẫn cache nằm ngoài thư mục dữ liệu của workspace.')
            if target.is_dir():
                shutil.rmtree(target)
        # A previously generated combined ZIP must never survive a replacement.
        (store.data / 'output_alignment' / 'tat-ca-ket-qua.zip').unlink(missing_ok=True)

    def replace(self, snapshot):
        store, book = self.store, snapshot['book']
        book_id, revision = book['id'], uuid4().hex
        dump = lambda value: json.dumps(value, ensure_ascii=False)
        with store.lock:
            assets = self.materialize_images(snapshot, revision)
            with store.db() as db:
                old_pages = [dict(row) for row in db.execute('SELECT id,number,category,version FROM pages WHERE book_id=?', (book_id,))]
                old_ids = [page['id'] for page in old_pages]
                identities = {}
                for page in sorted(old_pages, key=lambda page: page['category'] not in ('ch', 'both')):
                    identities.setdefault(page['number'], page)
                for table in ('new_data_rows', 'new_data_pages', 'reference_allocations', 'ocr_results'):
                    db.execute(f'DELETE FROM {table} WHERE page_id IN (SELECT id FROM pages WHERE book_id=?)', (book_id,))
                db.execute('DELETE FROM ocr_job_pages WHERE job_id IN (SELECT id FROM ocr_jobs WHERE book_id=?)', (book_id,))
                db.execute('DELETE FROM page_links WHERE book_id=?', (book_id,))
                for table in ('ocr_jobs', 'alignments', 'book_layouts', 'book_text_sources'):
                    db.execute(f'DELETE FROM {table} WHERE book_id=?', (book_id,))
                db.execute('DELETE FROM pages WHERE book_id=?', (book_id,))
                for session in db.execute('SELECT key,value FROM ui_sessions').fetchall():
                    value = json.loads(session['value'])
                    if session['key'] == 'book:' + book_id or (isinstance(value, dict) and value.get('book_id') == book_id):
                        db.execute('DELETE FROM ui_sessions WHERE key=?', (session['key'],))
                alignments = []
                for number, (width, height) in enumerate(snapshot['dimensions'], 1):
                    previous = identities.get(number)
                    page_id = previous['id'] if previous else uuid4().hex
                    version = max((page['version'] for page in old_pages if page['number'] == number), default=-1) + 1
                    page = snapshot['pages'].get(number)
                    if not page:
                        db.execute('''INSERT INTO pages (id,book_id,number,category,width,height,ocr_skip,ocr_languages,version)
                            VALUES (?,?,?,'misc',?,?,1,'[]',?)''', (page_id, book_id, number, width, height, version))
                        continue
                    rows, boxes = [], []
                    for index, (record, points) in enumerate(zip(page['rows'], page['points'])):
                        row_id = uuid5(NAMESPACE_URL, f"{book_id}:{number}:{record['line']}").hex
                        rows.append({'id': row_id, 'sentence_id': f"{book['name']}.{number:03d}.{record['line']+1}",
                                     'source': record['source'], 'target': record['target'], 'reviewed': False,
                                     'source_page_id': page_id, 'source_line_index': index, 'marks': []})
                        if record['source']:
                            boxes.append(phrase_box(record, points, row_id, len(boxes)+1))
                    direction = 1 if sum(box['box_axis'] == 'vertical' for box in boxes) > len(boxes)/2 else 2
                    db.execute('''INSERT INTO pages (id,book_id,number,category,width,height,boxes,export_boxes,
                        source_text,target_text,target_origin,reading_direction,reading_direction_override,
                        ocr_granularity,status,ocr_languages,version) VALUES (?,?,?,'ch',?,?,?,?,?,?,'new_data',?,?,'phrase','pending','["han"]',?)''',
                        (page_id, book_id, number, page['width'], page['height'], dump(boxes), dump(boxes),
                         '\n'.join(row['source'] for row in rows), '\n'.join(row['target'] for row in rows),
                         direction, direction, version))
                    db.execute('INSERT INTO new_data_pages VALUES (?,?,?)', (page_id, assets[number], snapshot['fingerprint']))
                    for record, row in zip(page['rows'], rows):
                        db.execute('INSERT INTO new_data_rows VALUES (?,?,?,?)', (page_id, record['patch_id'], row['id'], dump(record)))
                    alignments.extend(rows)
                db.execute('INSERT INTO alignments VALUES (?,?)', (book_id, dump(alignments)))
                db.execute('INSERT INTO new_data_books VALUES (?,?,?) ON CONFLICT(book_id) DO UPDATE SET fingerprint=excluded.fingerprint,revision=excluded.revision',
                           (book_id, snapshot['fingerprint'], revision))
            self.clear_cache(book_id, old_ids)
            store.sync_labels(book_id)
