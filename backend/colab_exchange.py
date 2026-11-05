"""Offline, version-checked Vietnamese GPU exchange with the local workspace."""
import hashlib
import io
import json
import math
import zipfile
from datetime import datetime, timezone
from uuid import uuid4

from PIL import Image
from . import bilingual
from .vietocr import CACHE_KEY

SCHEMA = 'nom-workspace-vietocr-1'


def export_bundle(store, book_id, render, settings_for_page):
    manifest = {'schema': SCHEMA, 'bundle_id': uuid4().hex, 'book_id': book_id,
                'layout': store.book_layout(book_id), 'pages': []}
    stream = io.BytesIO()
    with store.lock, zipfile.ZipFile(stream, 'w', zipfile.ZIP_DEFLATED) as archive:
        for page in store.pages(book_id):
            if page['status'] == 'done' or page['ocr_skip'] or page['category'] in ('blank', 'misc') or 'vi' not in page['ocr_languages']:
                continue
            content = render(page).read_bytes()
            with Image.open(io.BytesIO(content)) as image:
                width, height = image.size
            settings = settings_for_page(page)
            settings['vi_engine'] = CACHE_KEY
            cached = store.latest_ocr(page['id']) or {}
            han = page['boxes'] if page['category'] != 'vi' else []
            if not han:
                han = cached.get('boxes', [])
            entry = {'page_id': page['id'], 'version': page['version'],
                     'width': width, 'height': height, 'page_width': page['width'], 'page_height': page['height'],
                     'image': 'images/' + page['id'] + '.jpg',
                     'sha256': hashlib.sha256(content).hexdigest(), 'settings': settings,
                     'target_regions': settings.get('target_regions'), 'han_boxes': han}
            # Mask coordinates in saved results use the workspace dimensions.
            entry['han_boxes'] = [{**b, 'points': [[x * width / page['width'], y * height / page['height']]
                                                 for x, y in b['points']]} for b in han]
            manifest['pages'].append(entry)
            archive.writestr(entry['image'], content)
        if not manifest['pages']:
            raise ValueError('Không có trang Quốc ngữ chưa duyệt. Kiểm tra phân loại/ngôn ngữ của trang.')
        archive.writestr('manifest.json', json.dumps(manifest, ensure_ascii=False))
    # Persist the authoritative version/settings locally; never trust uploaded metadata.
    store.save_session('colab:' + manifest['bundle_id'], manifest)
    return stream.getvalue()


def validate_boxes(boxes, width, height):
    if not isinstance(boxes, list) or not boxes or len(boxes) > 5000:
        raise ValueError('Kết quả phải có 1–5000 box; trang rỗng cần kiểm tra lại.')
    result = []
    for box in boxes:
        text, points = box.get('transcription'), box.get('points')
        if not isinstance(text, str) or not text.strip() or len(text) > 30000:
            raise ValueError('Nội dung box không hợp lệ.')
        if not isinstance(points, list) or len(points) != 4:
            raise ValueError('Box phải có bốn điểm.')
        if any(len(p) != 2 or any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in p)
               or not (0 <= p[0] <= width and 0 <= p[1] <= height) for p in points):
            raise ValueError('Box vượt kích thước ảnh hoặc chứa tọa độ không hợp lệ.')
        turns = []
        for i in range(4):
            a, b, c = points[i], points[(i+1)%4], points[(i+2)%4]
            turns.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
        if not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
            raise ValueError('Box phải là tứ giác lồi có diện tích.')
        result.append({'id': 'vi-' + uuid4().hex, 'transcription': text, 'points': points})
    return result


def import_bundle(store, book_id, content):
    with zipfile.ZipFile(io.BytesIO(content)) as archive:
        info = archive.getinfo('results.json')
        if info.file_size > 30 * 1024 * 1024:
            raise ValueError('results.json quá lớn.')
        payload = json.loads(archive.read(info))
    if payload.get('schema') != SCHEMA:
        raise ValueError('Sai định dạng gói kết quả.')
    manifest = store.session('colab:' + str(payload.get('bundle_id', '')))
    if not manifest or manifest['book_id'] != book_id:
        raise ValueError('Gói không được xuất từ quyển sách/workspace này.')
    if manifest['layout'] != store.book_layout(book_id):
        raise ValueError('Vùng mẫu của quyển đã thay đổi. Xuất gói mới.')
    expected = {p['page_id']: p for p in manifest['pages']}
    seen, prepared = set(), []
    for record in payload.get('pages', []):
        pid = record.get('page_id')
        if pid not in expected or pid in seen:
            raise ValueError('Trang không thuộc gói hoặc bị trùng.')
        seen.add(pid)
        entry = expected[pid]
        if record.get('sha256') != entry['sha256']:
            raise ValueError('Ảnh đầu vào không khớp gói đã xuất.')
        boxes = validate_boxes(record.get('boxes'), entry['width'], entry['height'])
        boxes = [{**b, 'points': [[x * entry['page_width'] / entry['width'], y * entry['page_height'] / entry['height']]
                                  for x, y in b['points']]} for b in boxes]
        prepared.append((entry, boxes))
    if not prepared:
        raise ValueError('Không có trang thành công để nhập; xem errors.json trên Colab.')
    now = datetime.now(timezone.utc).isoformat()
    # Validate all pages before any write; SQL transaction also checks active OCR jobs.
    with store.lock, store.db() as db:
        for entry, boxes in prepared:
            page = store.page(entry['page_id'])
            if not page or page['version'] != entry['version'] or page['status'] == 'done' or page['ocr_skip']:
                raise ValueError('Trang đã thay đổi sau khi xuất. Xuất gói mới để tránh ghi đè chỉnh sửa.')
            active = db.execute("SELECT 1 FROM ocr_job_pages p JOIN ocr_jobs j ON j.id=p.job_id WHERE p.page_id=? AND j.status IN ('running','pausing')", (page['id'],)).fetchone()
            if active:
                raise ValueError('Dừng và chờ OCR local hoàn tất trước khi nhập kết quả.')
        for entry, boxes in prepared:
            page = store.page(entry['page_id'])
            settings = entry['settings']
            result = dict(store.latest_ocr(page['id']) or {})
            previous_completed = result.get('cached_languages', result.get('completed_languages', []))
            result.update(page_id=page['id'], version=page['version'], result_id=uuid4().hex,
                          settings=settings, requested_languages=['vi'], completed_languages=['vi'],
                          vi_boxes=boxes, vi_text_lines=[b['transcription'] for b in boxes],
                          target_origin='VietOCR CUDA / Colab', cached=False,
                          reading_direction=page['reading_direction'])
            result.setdefault('boxes', [])
            result.setdefault('text_lines', [])
            result.setdefault('warnings', ['Quốc ngữ do VietOCR CUDA đọc; cần kiểm tra trước khi duyệt.'])
            result['cached_languages'] = list(dict.fromkeys(previous_completed + ['vi']))
            result['language_settings'] = {**result.get('language_settings', {}), 'vi': bilingual.signature(settings, 'vi')}
            db.execute('INSERT INTO ocr_results VALUES (?,?,?,?,?,?)',
                       (result['result_id'], page['id'], page['version'], json.dumps(settings), json.dumps(result, ensure_ascii=False), now))
            # Import is an explicit replacement of the Vietnamese draft only.
            db.execute("UPDATE pages SET vi_boxes=?,target_text=?,target_origin=?,status='pending',version=version+1 WHERE id=?",
                       (json.dumps(boxes, ensure_ascii=False), '\n'.join(result['vi_text_lines']), result['target_origin'], page['id']))
    store.sync_labels(book_id)
    return {'imported': len(prepared), 'exported': len(expected), 'pending_review': True}
