import csv
import io
import json
import math
import os
import re
import shutil
import sqlite3
import zipfile
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from typing import Literal

import pymupdf
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel, Field, field_validator

from .demo import manuscript
from .store import CATEGORIES, Store, ordered_boxes

Category = Literal['ch', 'vi', 'intro', 'ref', 'toc', 'blank', 'misc']
MAX_UPLOAD = 150 * 1024 * 1024
EXPORT_COLUMNS = ['img_id', 'sentence_id', 'SinoNom_Char', 'ChuQN_txt']


class BoxInput(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    transcription: str = Field(max_length=30000)
    points: list[tuple[float, float]] = Field(min_length=4, max_length=4)

    @field_validator('points')
    @classmethod
    def valid_points(cls, points):
        if any(not math.isfinite(x) or not math.isfinite(y) or x < 0 or y < 0 for x,y in points):
            raise ValueError('Tọa độ phải là số hữu hạn, không âm.')
        # Reject zero-area and self-intersecting polygons.
        turns = []
        for i in range(4):
            a,b,c = points[i], points[(i+1)%4], points[(i+2)%4]
            turns.append((b[0]-a[0])*(c[1]-b[1])-(b[1]-a[1])*(c[0]-b[0]))
        if not (all(t > 0 for t in turns) or all(t < 0 for t in turns)):
            raise ValueError('Box phải là tứ giác lồi có diện tích lớn hơn 0.')
        return points


class PageInput(BaseModel):
    boxes: list[BoxInput] = Field(max_length=5000)
    done: bool = False
    category: Category
    version: int = Field(ge=0)


class ImportInput(BaseModel):
    filename: str


class AlignmentInput(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    sentence_id: str = Field(min_length=1, max_length=300)
    source: str = Field(max_length=100000)
    target: str = Field(max_length=100000)
    reviewed: bool = False


class AlignmentsInput(BaseModel):
    rows: list[AlignmentInput] = Field(max_length=50000)


def create_app(root: Path | None = None):
    root = (root or Path(os.environ.get('CORPUS_ROOT', Path(__file__).resolve().parents[1]))).resolve()
    store = Store(root)
    app = FastAPI(title='Nôm · Local Corpus Workbench', version='0.1.0')
    app.state.store = store

    def require_book(book_id):
        book = store.book(book_id)
        if not book:
            raise HTTPException(404, 'Không tìm thấy sách.')
        return book

    def require_page(page_id):
        page = store.page(page_id)
        if not page:
            raise HTTPException(404, 'Không tìm thấy trang.')
        return page

    def validate_filename(name):
        if not name or any(c in name for c in ('/', '\\', '\t', '\r', '\n', '\x00', ':', '<', '>', '"', '|', '?', '*')) or Path(name).suffix.lower() != '.pdf':
            raise HTTPException(400, 'Tên nguồn phải là tên file PDF, không chứa đường dẫn.')
        return name

    def import_pdf(source: Path, filename: str):
        validate_filename(filename)
        if any(b['filename'] == filename and not b['demo'] for b in store.books()):
            raise HTTPException(409, 'Sách này đã có trong tủ sách. Hãy mở sách hiện có để tiếp tục.')
        try:
            # Opening from bytes avoids leaked native file handles on malformed PDFs
            # on Windows, so the upload can always be cleaned up after an error.
            with pymupdf.open(stream=source.read_bytes(), filetype='pdf') as document:
                if document.needs_pass or not document.is_pdf or not len(document):
                    raise ValueError('PDF rỗng hoặc được bảo vệ bằng mật khẩu.')
                dimensions = []
                for page in document:
                    scale = min(1.5, 2400 / max(page.rect.width, page.rect.height))
                    dimensions.append((math.ceil(page.rect.width * scale), math.ceil(page.rect.height * scale)))
        except Exception as error:
            raise HTTPException(400, 'Không đọc được PDF hợp lệ, không có mật khẩu.') from error
        book_id = uuid4().hex
        folder = store.data / 'raw_data' / book_id
        folder.mkdir(parents=True)
        destination = folder / filename
        try:
            shutil.copyfile(source, destination)
            with store.db() as db:
                db.execute('INSERT INTO books VALUES (?,?,?,?,?,?)', (book_id, Path(filename).stem, filename, str(destination.relative_to(root)), 0, datetime.now(timezone.utc).isoformat()))
                for i,(width,height) in enumerate(dimensions, start=1):
                    db.execute('INSERT INTO pages (id,book_id,number,category,width,height) VALUES (?,?,?,?,?,?)', (uuid4().hex, book_id, i, 'misc', width, height))
        except Exception:
            destination.unlink(missing_ok=True)
            folder.rmdir()
            raise
        store.sync_labels(book_id)
        return next(b for b in store.books() if b['id'] == book_id)

    def rendered_image(page):
        book = require_book(page['book_id'])
        filename = f"{book['name']}.{page['number']:03d}.jpg"
        cache = store.data / 'processed_images' / book['id'] / filename
        with store.lock:
            if not cache.exists():
                cache.parent.mkdir(parents=True, exist_ok=True)
                with pymupdf.open(root / book['source']) as document:
                    pdf_page = document[page['number']-1]
                    scale = min(1.5, 2400 / max(pdf_page.rect.width,pdf_page.rect.height))
                    pix = pdf_page.get_pixmap(matrix=pymupdf.Matrix(scale,scale), colorspace=pymupdf.csRGB, alpha=False)
                    temporary = cache.with_suffix('.tmp')
                    temporary.write_bytes(pix.tobytes('jpeg', jpg_quality=92))
                    os.replace(temporary, cache)
            category_image = store.book_dir(book['id']) / page['category'] / filename
            category_image.parent.mkdir(parents=True, exist_ok=True)
            if not category_image.exists():
                shutil.copyfile(cache, category_image)
        return cache

    @app.get('/api/health')
    def health():
        return {'status':'ok', 'ocr':'not_configured'}

    @app.get('/api/workspace')
    def workspace():
        return {
            'books': store.books(),
            'pair_stats': store.pair_stats(),
            'ocr_ready': False,
            'storage': 'data/.workspace/workspace.sqlite3',
        }

    @app.get('/api/sources')
    def sources():
        folder = root / 'data'
        return [{'name':p.name,'bytes':p.stat().st_size} for p in sorted(folder.glob('*')) if p.is_file() and p.suffix.lower()=='.pdf'] if folder.exists() else []

    @app.post('/api/books/import', status_code=201)
    def import_source(data: ImportInput):
        name = validate_filename(data.filename)
        source = root / 'data' / name
        if not source.is_file() or source.resolve().parent != (root/'data').resolve():
            raise HTTPException(404, 'Không tìm thấy nguồn PDF trong data/.')
        return import_pdf(source,name)

    @app.post('/api/books/upload', status_code=201)
    def upload(file: UploadFile):
        filename = validate_filename(file.filename or '')
        temporary = store.local / f'upload-{uuid4().hex}.pdf'
        size = 0
        try:
            with temporary.open('wb') as output:
                while chunk := file.file.read(1024*1024):
                    size += len(chunk)
                    if size > MAX_UPLOAD:
                        raise HTTPException(413, 'PDF vượt giới hạn 150 MB. Với sách lớn, đặt file trong data/ rồi chọn nhập từ máy.')
                    output.write(chunk)
            return import_pdf(temporary, filename)
        finally:
            temporary.unlink(missing_ok=True)
            file.file.close()

    @app.get('/api/books/{book_id}/pages')
    def pages(book_id: str):
        require_book(book_id)
        return store.pages(book_id)

    @app.get('/api/pages/{page_id}/image')
    def image(page_id: str, thumbnail: bool = False):
        page = require_page(page_id)
        if require_book(page['book_id'])['demo']:
            return Response(manuscript(page['category'],page['number']),media_type='image/svg+xml')
        original = rendered_image(page)
        if thumbnail:
            thumb = original.with_suffix('.thumb.jpg')
            with store.lock:
                if not thumb.exists():
                    pix = pymupdf.Pixmap(str(original))
                    shrink = max(0, math.floor(math.log2(max(pix.width/160, pix.height/220))))
                    if shrink:
                        pix.shrink(shrink)
                    thumb.write_bytes(pix.tobytes('jpeg', jpg_quality=75))
            return FileResponse(thumb,media_type='image/jpeg')
        return FileResponse(original,media_type='image/jpeg')

    @app.put('/api/pages/{page_id}')
    def save_page(page_id: str, data: PageInput):
        with store.lock:
            page = require_page(page_id)
            if any(x>page['width'] or y>page['height'] for box in data.boxes for x,y in box.points):
                raise HTTPException(422, 'Box vượt ra ngoài kích thước ảnh.')
            if len({b.id for b in data.boxes}) != len(data.boxes):
                raise HTTPException(422, 'ID box bị trùng.')
            if data.done and data.category in ('ch','vi','intro','ref','toc') and (not data.boxes or any(not b.transcription.strip() for b in data.boxes)):
                raise HTTPException(422, 'Cần nhập văn bản cho các vùng trước khi hoàn thành.')
            boxes = [b.model_dump() for b in data.boxes]
            try:
                with store.db() as db:
                    result = db.execute('UPDATE pages SET boxes=?,status=?,category=?,version=version+1 WHERE id=? AND version=?', (json.dumps(boxes,ensure_ascii=False),'done' if data.done else 'pending',data.category,page_id,data.version))
                    if result.rowcount != 1:
                        raise HTTPException(409, 'Trang đã được cập nhật ở cửa sổ khác. Hãy tải lại trang trước khi lưu.')
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, 'Trang đã có trong nhóm này. Vui lòng chọn bản đã tồn tại.') from error
            updated = require_page(page_id)
            if not require_book(page['book_id'])['demo']:
                rendered_image(updated)
                if page['category'] != updated['category']:
                    old = store.book_dir(page['book_id']) / page['category'] / f"{require_book(page['book_id'])['name']}.{page['number']:03d}.jpg"
                    old.unlink(missing_ok=True)
            store.sync_labels(page['book_id'])
            return updated

    @app.post('/api/pages/{page_id}/duplicate')
    def duplicate_page(page_id: str):
        with store.lock:
            page = require_page(page_id)
            if page['category'] not in ('ch','vi'):
                raise HTTPException(400, 'Chọn nhóm Hán Nôm hoặc Quốc ngữ trước khi tạo bản song ngữ.')
            category = 'vi' if page['category']=='ch' else 'ch'
            new_id = uuid4().hex
            with store.db() as db:
                if db.execute('SELECT 1 FROM pages WHERE book_id=? AND number=? AND category=?',(page['book_id'],page['number'],category)).fetchone():
                    raise HTTPException(409, 'Trang đã có bản ở nhóm ngôn ngữ còn lại.')
                db.execute('INSERT INTO pages (id,book_id,number,category,width,height) VALUES (?,?,?,?,?,?)',(new_id,page['book_id'],page['number'],category,page['width'],page['height']))
            if not require_book(page['book_id'])['demo']:
                rendered_image(require_page(new_id))
            store.sync_labels(page['book_id'])
            return require_page(new_id)

    @app.get('/api/books/{book_id}/alignments')
    def get_alignments(book_id: str):
        require_book(book_id)
        with store.db() as db:
            row = db.execute('SELECT rows FROM alignments WHERE book_id=?',(book_id,)).fetchone()
        return json.loads(row['rows']) if row else []

    @app.put('/api/books/{book_id}/alignments')
    def save_alignments(book_id: str, data: AlignmentsInput):
        book = require_book(book_id)
        ids = [r.sentence_id for r in data.rows]
        if len(ids) != len(set(ids)) or len({r.id for r in data.rows}) != len(data.rows):
            raise HTTPException(422,'ID câu hoặc ID hàng bị trùng.')
        valid_images = {p['number'] for p in store.pages(book_id) if p['category']=='ch'}
        for row in data.rows:
            match = re.fullmatch(re.escape(book['name'])+r'\.(\d{3,})\.([1-9]\d*)',row.sentence_id)
            if not match or int(match[1]) not in valid_images:
                raise HTTPException(422,'sentence_id phải trỏ tới trang Hán Nôm có thật: <Tên sách>.<trang ít nhất 3 số>.<câu từ 1>.')
        rows = [r.model_dump() for r in data.rows]
        counters = {}
        for row in rows:
            prefix = row['sentence_id'].rsplit('.', 1)[0]
            counters[prefix] = counters.get(prefix, 0) + 1
            row['sentence_id'] = f"{prefix}.{counters[prefix]}"
        with store.db() as db:
            db.execute('INSERT INTO alignments VALUES (?,?) ON CONFLICT(book_id) DO UPDATE SET rows=excluded.rows',(book_id,json.dumps(rows,ensure_ascii=False)))
        return rows

    @app.get('/api/books/{book_id}/export')
    def export(book_id: str, format: Literal['csv','xlsx','labels']='csv'):
        book = require_book(book_id)
        folder = store.data / 'output_alignment' / book_id
        folder.mkdir(exist_ok=True)
        if format == 'labels':
            store.sync_labels(book_id)
            content = io.BytesIO()
            with zipfile.ZipFile(content,'w',zipfile.ZIP_DEFLATED) as archive:
                for category in CATEGORIES:
                    if category in ('blank','misc'):
                        continue
                    for name in ('Label.txt','fileState.txt'):
                        archive.write(store.book_dir(book_id)/category/name, f"{book['name']}/{category}/{name}")
            path = folder / f"{book['name']}_labels.zip"
            path.write_bytes(content.getvalue())
        else:
            rows = get_alignments(book_id)
            if not rows:
                raise HTTPException(400,'Chưa có cặp căn chỉnh. Hãy tạo và lưu các cặp trước khi xuất.')
            values = [[r['sentence_id'].rsplit('.',1)[0]+'.jpg',r['sentence_id'],r['source'],r['target']] for r in rows]
            path = folder / f"{book['name']}.{format}"
            if format == 'csv':
                with path.open('w',encoding='utf-8-sig',newline='') as output:
                    writer = csv.writer(output)
                    writer.writerow(EXPORT_COLUMNS)
                    writer.writerows(values)
            else:
                workbook = Workbook()
                sheet = workbook.active
                sheet.title = 'Alignment'
                sheet.append(EXPORT_COLUMNS)
                for cell in sheet[1]:
                    cell.font = Font(bold=True,color='FFFFFF')
                    cell.fill = PatternFill('solid',fgColor='234D42')
                for values_row in values:
                    sheet.append(values_row)
                    for cell in sheet[sheet.max_row]:
                        # Export source text verbatim, never execute spreadsheet formulas.
                        cell.data_type = 's'
                    # Dictionary integration is pending: all pairs are unverified, red.
                    for cell in sheet[sheet.max_row][2:]:
                        cell.font = Font(name='Arial',color='C43838')
                for column,width in zip('ABCD',(45,48,65,85)):
                    sheet.column_dimensions[column].width = width
                sheet.freeze_panes = 'A2'
                workbook.save(path)
        return FileResponse(path,filename=path.name)

    dist = root / 'frontend' / 'dist'
    if dist.exists():
        app.mount('/',StaticFiles(directory=dist,html=True),name='web')
    return app
