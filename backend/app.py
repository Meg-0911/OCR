import csv
import json
import math
import os
import re
import shutil
import sqlite3
import zipfile
import threading
from contextlib import asynccontextmanager
import asyncio
from pathlib import Path
from uuid import uuid4
from datetime import datetime, timezone
from typing import Literal

import pymupdf
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill
from pydantic import BaseModel, Field, field_validator

from .store import CATEGORIES, Store, label_groups
from .ocr import KHNConfig, KimHanNomOCR, OCRError, normalize_result
from .sources import source_files
from .dictionary import Dictionary
from .ocr_jobs import OCRJobs
from .vietnamese_ocr import create_vietnamese_ocr
from PIL import Image
from . import bilingual
from .han_layout import PIPELINE_VERSION
from .han_layout import jpeg_bytes
from .region_ocr import crop_selection

Category = Literal['ch', 'vi', 'both', 'intro', 'ref', 'toc', 'blank', 'misc']

def page_ocr_mode(category: str, default_mode: str = 'bilingual') -> str:
    if category == 'ch':
        return 'han'
    elif category == 'vi':
        return 'vi'
    elif category == 'both':
        return default_mode or 'bilingual'
    elif category in ('intro', 'ref', 'toc'):
        return 'han' if default_mode == 'han' else 'bilingual'
    return default_mode or 'bilingual'
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
    boxes: list[BoxInput] = Field(default_factory=list,max_length=5000)
    vi_boxes: list[BoxInput] | None = Field(default=None,max_length=5000)
    source_text: str | None = Field(default=None,max_length=200000)
    target_text: str | None = Field(default=None,max_length=200000)
    done: bool = False
    category: Category
    version: int = Field(ge=0)
    reading_direction: Literal[1, 2] = 1
    ocr_skip: bool | None = None


class PagePatch(BaseModel):
    source_text: str | None = Field(default=None,max_length=200000)
    target_text: str | None = Field(default=None,max_length=200000)
    boxes: list[BoxInput] | None = Field(default=None,max_length=5000)
    vi_boxes: list[BoxInput] | None = Field(default=None,max_length=5000)
    category: Category | None = None
    reading_direction: Literal[1,2] | None = None
    ocr_skip: bool | None = None
    ocr_languages: list[Literal['han','vi']] | None = Field(default=None,min_length=1,max_length=2)
    source_regions: list[tuple[float,float,float,float]] | None = Field(default=None,max_length=100)
    target_regions: list[tuple[float,float,float,float]] | None = Field(default=None,max_length=100)

    @field_validator('source_regions','target_regions')
    @classmethod
    def valid_regions(cls,regions):
        return validate_regions(regions)


class PagePlan(BaseModel):
    page_id: str
    category: Category
    ocr_skip: bool = False


class BookPlan(BaseModel):
    pages: list[PagePlan] = Field(max_length=20000)


class SessionInput(BaseModel):
    page_id: str | None = None
    alignment_page: str | None = None
    view: Literal['overview','library','review','alignment','export'] = 'review'
    workflow_step: Literal[1,2,3,4] = 1


class ImportInput(BaseModel):
    filename: str


class TextSourceInput(BaseModel):
    filename: str = Field(min_length=1,max_length=255)
    text: str = Field(max_length=2000000)


def validate_regions(regions):
    for region in regions or []:
        left,top,right,bottom=region
        if not all(math.isfinite(value) for value in region) or not 0<=left<right<=1 or not 0<=top<bottom<=1:
            raise ValueError('Vùng mẫu phải có diện tích dương và tọa độ chuẩn hóa từ 0 đến 1.')
    return regions


class LayoutInput(BaseModel):
    source_regions: list[tuple[float,float,float,float]] = Field(default_factory=list,max_length=100)
    target_regions: list[tuple[float,float,float,float]] = Field(default_factory=list,max_length=100)
    reading_direction: Literal[1,2] | None = None

    @field_validator('source_regions','target_regions')
    @classmethod
    def valid_regions(cls,regions):
        return validate_regions(regions)


class OCRSettings(BaseModel):
    font_type: Literal[0,1,2] = 0
    shared_reading_area: bool = False
    ocr_id: Literal[1, 2, 3, 4] = 1
    lang_type: Literal[0, 1, 2] = 2
    reading_direction: Literal[1, 2] = 1
    epitaph: Literal[0, 1] = 0
    tag: str | None = Field(default=None, max_length=200)
    mode: Literal['han','vi','bilingual'] = 'han'
    vi_psm: Literal[3,6,11] = 11
    source_regions: list[tuple[float,float,float,float]] | None = Field(default=None,max_length=100)
    target_regions: list[tuple[float,float,float,float]] | None = Field(default=None,max_length=100)

    @field_validator('source_regions','target_regions')
    @classmethod
    def valid_regions(cls,regions):
        return validate_regions(regions)


class OCRInput(OCRSettings):
    version: int = Field(ge=0)
    force: bool = False
    reuse_saved_settings: bool = False


class RegionOCRInput(BaseModel):
    box: BoxInput
    language: Literal['han','vi']
    reading_direction: Literal[1,2] = 2


class OCRBookInput(OCRSettings):
    start_page: int = Field(default=1, ge=1)
    end_page: int | None = Field(default=None, ge=1)
    include_unclassified: bool = False
    apply_texts: bool = True


class WorkflowInput(OCRSettings):
    mode: Literal['bilingual','han','vi'] = 'bilingual'
    plan: list[PagePlan] = Field(default_factory=list,max_length=20000)


class AlignmentInput(BaseModel):
    id: str = Field(min_length=1, max_length=100)
    sentence_id: str = Field(min_length=1, max_length=300)
    source: str = Field(max_length=100000)
    target: str = Field(max_length=100000)
    reviewed: bool = False


class AlignmentsInput(BaseModel):
    rows: list[AlignmentInput] = Field(max_length=50000)


def create_app(root: Path | None = None, *, ocr_config: KHNConfig | None = None, ocr_transport=None, vi_provider=None):
    root = (root or Path(os.environ.get('CORPUS_ROOT', Path(__file__).resolve().parents[1]))).resolve()
    store = Store(root)
    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(jobs.close)

    app = FastAPI(title='Nôm · Local Corpus Workbench', version='0.1.0', lifespan=lifespan)
    app.state.store = store
    config = ocr_config if ocr_config is not None else KHNConfig.from_env(root / 'backend' / '.env')
    ocr = KimHanNomOCR(config, transport=ocr_transport)
    vietnamese=vi_provider or create_vietnamese_ocr(root)
    raw_folder = store.data / 'raw_data'
    source_errors = []
    dictionary = Dictionary(store.data / 'dictionaries')
    ocr_locks = {}
    ocr_lock_guard = threading.Lock()

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
        if any(b['filename'].casefold() == filename.casefold() for b in store.books()):
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
        destination = raw_folder / filename
        copy_source = source.resolve() != destination.resolve()
        if copy_source and destination.exists():
            raise HTTPException(409, 'File nguồn đã tồn tại. Quét lại thư mục để mở sách, không ghi đè PDF.')
        try:
            if copy_source:
                shutil.copyfile(source, destination)
            with store.db() as db:
                db.execute('INSERT INTO books VALUES (?,?,?,?,?,?)', (book_id, Path(filename).stem, filename, str(destination.relative_to(root)), 0, datetime.now(timezone.utc).isoformat()))
                for i,(width,height) in enumerate(dimensions, start=1):
                    db.execute('INSERT INTO pages (id,book_id,number,category,width,height) VALUES (?,?,?,?,?,?)', (uuid4().hex, book_id, i, 'both', width, height))
        except Exception:
            if copy_source:
                destination.unlink(missing_ok=True)
            raise
        store.sync_labels(book_id)
        return next(b for b in store.books() if b['id'] == book_id)

    def sync_sources():
        with store.lock:
            source_errors.clear()
            known = {b['filename'].casefold():b for b in store.books()}
            for source in source_files(raw_folder, '.pdf'):
                existing = known.get(source.name.casefold())
                if existing:
                    # Repair paths from workspaces moved into backend/data/.
                    with store.db() as db:
                        db.execute('UPDATE books SET source=? WHERE id=?', (str(source.relative_to(root)), existing['id']))
                    continue
                try:
                    book = import_pdf(source, source.name)
                    known[source.name.casefold()] = book
                except HTTPException as error:
                    source_errors.append({'filename':source.name, 'message':str(error.detail)})

    def text_sources(book_id):
        with store.db() as db:
            return {row['language']:{'filename':row['filename'],'text':row['text']} for row in
                    db.execute('SELECT * FROM book_text_sources WHERE book_id=?',(book_id,))}

    def book_summary(book):
        reference=text_sources(book['id']).get('vi')
        return book | {'reference_file':reference['filename'] if reference else None}

    # Index every local PDF; no seeded data, fixed book count, copying or OCR calls.
    sync_sources()

    def rendered_image(page, high_resolution=False):
        book = require_book(page['book_id'])
        filename = f"{book['name']}.{page['number']:03d}.jpg"
        cache = store.data / 'processed_images' / book['id'] / filename
        if high_resolution:
            cache = store.local / 'ocr-images' / book['id'] / filename
        with store.lock:
            if not cache.exists():
                cache.parent.mkdir(parents=True, exist_ok=True)
                with pymupdf.open(root / book['source']) as document:
                    pdf_page = document[page['number']-1]
                    scale = min(4 if high_resolution and pdf_page.get_images() else 1.5, (3200 if high_resolution else 2400) / max(pdf_page.rect.width,pdf_page.rect.height))
                    pix = pdf_page.get_pixmap(matrix=pymupdf.Matrix(scale,scale), colorspace=pymupdf.csRGB, alpha=False)
                    temporary = cache.with_suffix('.tmp')
                    temporary.write_bytes(pix.tobytes('jpeg', jpg_quality=92))
                    os.replace(temporary, cache)
            category_image = store.book_dir(book['id']) / page['category'] / filename
            category_image.parent.mkdir(parents=True, exist_ok=True)
            if not high_resolution and not category_image.exists():
                shutil.copyfile(cache, category_image)
        return cache

    @app.get('/api/health')
    def health():
        return {'status':'ok', 'ocr':'configured' if config.ready else 'not_configured'}

    @app.get('/api/workspace')
    def workspace():
        return {
            'books': [book_summary(book) for book in store.books()],
            'pair_stats': store.pair_stats(),
            'ocr_ready': config.ready,
            'storage': 'backend/data/.workspace/workspace.sqlite3',
            'source_folder': 'backend/data/raw_data/',
            'source_errors': source_errors,
            'dictionary': dictionary.status(),
            'vietnamese_ocr': vietnamese.status(),
            'resume':store.session('current'),
        }

    @app.get('/api/dictionary/status')
    def dictionary_status():
        return dictionary.status()

    @app.get('/api/dictionary/lookup')
    def dictionary_lookup(character: str):
        try:
            return dictionary.lookup(character)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get('/api/dictionary/search')
    def dictionary_search(q: str):
        try:
            return dictionary.search(q)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get('/api/dictionary/reverse')
    def dictionary_reverse_search(q: str):
        try:
            return dictionary.reverse_search(q)
        except ValueError as error:
            raise HTTPException(422, str(error)) from None

    @app.get('/api/sources')
    def sources():
        known = {b['filename'].casefold():b['id'] for b in store.books()}
        return [{'name':p.name, 'bytes':p.stat().st_size, 'book_id':known.get(p.name.casefold()),
                 'reference_file':text_sources(known.get(p.name.casefold())).get('vi',{}).get('filename')}
                for p in source_files(raw_folder, '.pdf')]

    @app.post('/api/sources/sync')
    def refresh_sources():
        sync_sources()
        return workspace()

    @app.get('/api/books/{book_id}/text-sources')
    def get_text_sources(book_id: str):
        require_book(book_id)
        return text_sources(book_id)

    @app.put('/api/books/{book_id}/text-sources/{language}')
    def save_text_source(book_id: str,language: Literal['han','vi'],data: TextSourceInput):
        require_book(book_id)
        if not data.filename.lower().endswith('.txt') or not data.text.strip():
            raise HTTPException(422,'Chọn tệp TXT UTF-8 có nội dung.')
        with store.lock,store.db() as db:
            db.execute('INSERT INTO book_text_sources VALUES (?,?,?,?) ON CONFLICT(book_id,language) DO UPDATE SET filename=excluded.filename,text=excluded.text',
                       (book_id,language,Path(data.filename).name,data.text.lstrip('\ufeff')))
        return text_sources(book_id)

    @app.get('/api/books/{book_id}/reference')
    def reference_text(book_id: str):
        require_book(book_id)
        return text_sources(book_id).get('vi')

    @app.get('/api/books/{book_id}/layout')
    def get_layout(book_id: str):
        require_book(book_id)
        return store.book_layout(book_id)

    @app.put('/api/books/{book_id}/layout')
    def save_layout(book_id: str,data: LayoutInput):
        require_book(book_id)
        profile=data.model_dump(exclude_none=True)
        with store.lock:
            previous=store.book_layout(book_id)
            if 'reading_direction' not in profile and 'reading_direction' in previous:
                profile['reading_direction']=previous['reading_direction']
            with store.db() as db:
                db.execute('INSERT INTO book_layouts VALUES (?,?) ON CONFLICT(book_id) DO UPDATE SET profile=excluded.profile',
                           (book_id,json.dumps(profile)))
                changed=[key for key in ('source_regions','target_regions') if json.dumps(previous[key])!=json.dumps(profile[key])]
                direction_changed=profile.get('reading_direction',2)!=previous.get('reading_direction',2)
                if changed or direction_changed:
                    inherited='1=1' if direction_changed else ' OR '.join(key+' IS NULL' for key in changed)
                    db.execute("UPDATE pages SET status='pending',version=version+1 WHERE book_id=? AND ocr_skip=0 AND category!='blank' AND ("+inherited+')',(book_id,))
            store.sync_labels(book_id)
        return profile

    @app.post('/api/books/import', status_code=201)
    def import_source(data: ImportInput):
        name = validate_filename(data.filename)
        source = raw_folder / name
        if not source.is_file() or source.resolve().parent != raw_folder.resolve():
            raise HTTPException(404, 'Không tìm thấy nguồn PDF trong backend/data/raw_data/.')
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
                        raise HTTPException(413, 'PDF vượt giới hạn 150 MB. Đặt file trong backend/data/raw_data/ rồi quét lại thư mục.')
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
        original = rendered_image(page,high_resolution=not thumbnail)
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
            if any(x>page['width'] or y>page['height'] for box in [*data.boxes,*(data.vi_boxes or [])] for x,y in box.points):
                raise HTTPException(422, 'Box vượt ra ngoài kích thước ảnh.')
            if len({b.id for b in data.boxes}) != len(data.boxes):
                raise HTTPException(422, 'ID box bị trùng.')
            source_text=page['source_text'] if data.source_text is None else data.source_text
            target_text=page['target_text'] if data.target_text is None else data.target_text
            if data.done and ('□' in source_text or any('□' in box.transcription for box in data.boxes)):
                raise HTTPException(422,'Còn ký tự □ chưa nhận dạng. Sửa các ô này trước khi hoàn thành trang.')
            if data.done and any(not box.transcription.strip() for box in data.boxes):
                raise HTTPException(422,'Còn box chưa có chữ. Điền ký tự trước khi hoàn thành trang.')
            if data.done and not page['ocr_skip'] and page['category']!='blank':
                with store.db() as db:
                    active=db.execute("SELECT 1 FROM ocr_job_pages p JOIN ocr_jobs j ON j.id=p.job_id WHERE p.page_id=? AND p.status IN ('pending','running') AND j.status IN ('running','pausing')",(page_id,)).fetchone()
                if active:
                    raise HTTPException(409,'Chờ OCR trang này hoàn tất trước khi xác nhận.')
            if data.done and not (page['ocr_skip'] if data.ocr_skip is None else data.ocr_skip) and data.category not in ('blank','misc'):
                languages = page['ocr_languages'] if data.category in ('intro','ref','toc') else (['han'] if data.category=='ch' else ['vi'] if data.category=='vi' else ['han','vi'])
                vi_boxes = data.vi_boxes if data.vi_boxes is not None else page['vi_boxes']
                if ('han' in languages and not data.boxes) or ('vi' in languages and not vi_boxes):
                    raise HTTPException(422, 'Trang cần box thật cho từng ngôn ngữ trước khi hoàn thành. Kiểm tra OCR hoặc vẽ box thủ công.')
            boxes = [b.model_dump(mode='json') for b in data.boxes]
            try:
                with store.db() as db:
                    result = db.execute('UPDATE pages SET boxes=?,status=?,category=?,reading_direction=?,source_text=?,target_text=?,vi_boxes=?,version=version+1 WHERE id=? AND version=?',
                        (json.dumps(boxes,ensure_ascii=False),'done' if data.done else 'pending',data.category,data.reading_direction,
                         source_text,target_text,json.dumps([b.model_dump() for b in data.vi_boxes],ensure_ascii=False) if data.vi_boxes is not None else json.dumps(page['vi_boxes'],ensure_ascii=False),page_id,data.version))
                    if result.rowcount != 1:
                        raise HTTPException(409, 'Trang đã được cập nhật ở cửa sổ khác. Hãy tải lại trang trước khi lưu.')
                    edited=set(page['edited_fields'])
                    if data.source_text is not None and source_text!=page['source_text']:
                        edited.add('source_text')
                    if data.target_text is not None and target_text!=page['target_text']:
                        edited.add('target_text')
                    if boxes!=page['boxes']:
                        edited.add('boxes')
                    if data.vi_boxes is not None and [b.model_dump(mode='json') for b in data.vi_boxes]!=page['vi_boxes']:
                        edited.add('vi_boxes')
                    if data.category!=page['category']:
                        languages=['han'] if data.category=='ch' else ['vi'] if data.category=='vi' else ['han','vi'] if data.category=='both' else page['ocr_languages']
                        db.execute('UPDATE pages SET ocr_languages=? WHERE id=?',(json.dumps(languages),page_id))
                    db.execute('UPDATE pages SET edited_fields=? WHERE id=?',(json.dumps(sorted(edited)),page_id))
            except sqlite3.IntegrityError as error:
                raise HTTPException(409, 'Trang đã có trong nhóm này. Vui lòng chọn bản đã tồn tại.') from error
            updated = require_page(page_id)
            if data.ocr_skip is not None:
                with store.db() as db:
                    db.execute('UPDATE pages SET ocr_skip=? WHERE id=?',(int(data.ocr_skip),page_id))
                updated=require_page(page_id)
            rendered_image(updated)
            if page['category'] != updated['category']:
                old = store.book_dir(page['book_id']) / page['category'] / f"{require_book(page['book_id'])['name']}.{page['number']:03d}.jpg"
                old.unlink(missing_ok=True)
            store.propagate_placeholder_edits(page['book_id'],page['number'],page['source_text'],source_text)
            store.sync_labels(page['book_id'])
            return updated

    @app.patch('/api/pages/{page_id}')
    def patch_page(page_id: str,data: PagePatch):
        # Field-level autosave permits editing one language while the other finishes OCR.
        with store.lock:
            page=require_page(page_id)
            changes={key:value for key,value in data.model_dump(exclude_unset=True,mode='json').items() if value is not None or key in ('source_regions','target_regions')}
            if 'ocr_languages' in changes:
                languages=[language for language in ('han','vi') if language in changes['ocr_languages']]
                changes['ocr_languages']=json.dumps(languages)
                if page['category'] in ('ch','vi','both') and 'category' not in changes:
                    changes['category']='both' if len(languages)==2 else 'ch' if languages==['han'] else 'vi'
            elif changes.get('category') in ('ch','vi','both'):
                changes['ocr_languages']=json.dumps(['han'] if changes['category']=='ch' else ['vi'] if changes['category']=='vi' else ['han','vi'])
            elif 'category' in changes:
                changes['ocr_languages']=json.dumps(page['ocr_languages'])
            if not changes:
                return page
            edited=set(page['edited_fields'])
            edited.update(key for key in ('source_text','target_text','boxes','vi_boxes') if key in changes and changes[key]!=page[key])
            changes['edited_fields']=json.dumps(sorted(edited))
            for key in ('boxes','vi_boxes'):
                if key in changes:
                    if any(x>page['width'] or y>page['height'] for box in changes[key] for x,y in box['points']):
                        raise HTTPException(422,'Box vượt ra ngoài kích thước ảnh.')
                    changes[key]=json.dumps(changes[key],ensure_ascii=False)
            for key in ('source_regions','target_regions'):
                if key in changes and changes[key] is not None:
                    changes[key]=json.dumps(changes[key])
            if 'ocr_skip' in changes:
                changes['ocr_skip']=int(changes['ocr_skip'])
            try:
                with store.db() as db:
                    db.execute('UPDATE pages SET '+','.join(key+'=?' for key in changes)+",status='pending',version=version+1 WHERE id=?",(*changes.values(),page_id))
            except sqlite3.IntegrityError:
                raise HTTPException(409,'Trang đã có trong nhóm này.') from None
            if 'source_text' in changes:
                store.propagate_placeholder_edits(page['book_id'],page['number'],page['source_text'],changes['source_text'])
            store.sync_labels(page['book_id'])
            return require_page(page_id)

    @app.get('/api/books/{book_id}/session')
    def book_session(book_id: str):
        require_book(book_id)
        return store.session('book:'+book_id)

    @app.put('/api/books/{book_id}/session')
    def save_book_session(book_id: str,data: SessionInput):
        require_book(book_id)
        for page_id in (data.page_id,data.alignment_page):
            if page_id and require_page(page_id)['book_id']!=book_id:
                raise HTTPException(422,'Vị trí trang không thuộc sách.')
        state=data.model_dump()|{'book_id':book_id}
        store.save_session('book:'+book_id,state)
        store.save_session('current',state)
        return state

    @app.put('/api/books/{book_id}/plan')
    def save_book_plan(book_id: str,data: BookPlan):
        require_book(book_id)
        with store.lock:
            known={p['id'] for p in store.pages(book_id)}
            if len({p.page_id for p in data.pages})!=len(data.pages) or any(p.page_id not in known for p in data.pages):
                raise HTTPException(422,'Danh sách trang bị trùng hoặc không thuộc sách.')
            try:
                with store.db() as db:
                    for page in data.pages:
                        languages = (['han'] if page.category=='ch' else ['vi'] if page.category=='vi' else ['han','vi'] if page.category=='both' else None)
                        if languages is None:
                            db.execute("UPDATE pages SET category=?,ocr_skip=?,status='pending',version=version+1 WHERE id=? AND (category!=? OR ocr_skip!=?)",
                                       (page.category,int(page.ocr_skip),page.page_id,page.category,int(page.ocr_skip)))
                        else:
                            encoded=json.dumps(languages)
                            db.execute("UPDATE pages SET category=?,ocr_languages=?,ocr_skip=?,status='pending',version=version+1 WHERE id=? AND (category!=? OR ocr_skip!=? OR COALESCE(ocr_languages,'')!=?)",
                                       (page.category,encoded,int(page.ocr_skip),page.page_id,page.category,int(page.ocr_skip),encoded))
            except sqlite3.IntegrityError:
                raise HTTPException(409,'Trang bị trùng trong nhóm; giữ bản ngôn ngữ chính trước khi đổi nhãn.') from None
            store.sync_labels(book_id)
            store.sync_results(book_id,'save_page_plan')
        return store.pages(book_id)

    def recover_ocr(page_id):
        page = require_page(page_id)
        result = store.latest_ocr(page_id)
        if result:
            return result
        # Recover JSON files written by earlier versions of the workbench.
        folder = store.local / 'ocr' / page_id
        for path in sorted(folder.glob('*.json'), key=lambda p:p.stat().st_mtime, reverse=True):
            try:
                archive = json.loads(path.read_text(encoding='utf-8'))
                if archive.get('result'):
                    result=archive['result']
                    store.save_ocr(result,result['settings'],archive['created_at'])
                    return result
                result = normalize_result(archive['response'], page['width'], page['height']) | {
                    'page_id':page_id, 'version':archive['version'], 'result_id':path.stem,
                    'reading_direction':archive['settings']['reading_direction'], 'settings':archive['settings'],
                }
                store.save_ocr(result, archive['settings'], archive['created_at'])
                return result
            except (ValueError, KeyError, OCRError):
                continue
        return None

    @app.get('/api/pages/{page_id}/ocr')
    def latest_page_ocr(page_id: str):
        return recover_ocr(page_id)

    def effective_settings(book_id,data):
        settings=data.model_dump(exclude={'version','force','reuse_saved_settings','start_page','end_page','include_unclassified','apply_texts'})
        status=vietnamese.status()
        settings['vi_engine']=status.get('cache_key',status['engine'])
        layout=store.book_layout(book_id)
        if 'reading_direction' not in data.model_fields_set and layout.get('reading_direction'):
            settings['reading_direction']=layout['reading_direction']
            if 'ocr_id' not in data.model_fields_set:
                settings['ocr_id']=1
        for key in ('source_regions','target_regions'):
            if settings.get(key) is None:
                settings[key]=layout[key]
        if settings.get('shared_reading_area'):
            regions=list(dict.fromkeys(tuple(region) for key in ('source_regions','target_regions') for region in settings.get(key) or []))
            settings['source_regions']=regions
            settings['target_regions']=regions
        return json.loads(json.dumps(normalize_ocr_settings(settings)))

    def run_page_ocr(page_id: str, data: OCRInput, background=False, apply_texts=True):
        page = require_page(page_id)
        if page['ocr_skip'] or page['category']=='blank':
            raise HTTPException(422, 'Trang đã bỏ qua OCR.')
        if not background and page['version'] != data.version:
            raise HTTPException(409, 'Trang đã thay đổi. Hãy tải lại trước khi OCR.')
        cached = recover_ocr(page_id)
        settings=effective_settings(page['book_id'],data)
        saved_settings=cached.get('settings',{}) if data.reuse_saved_settings and cached else {}
        if saved_settings:
            keys=('ocr_id','lang_type','reading_direction','epitaph','tag','font_type','vi_psm',
                  'shared_reading_area','source_regions','target_regions')
            settings.update({key:saved_settings[key] for key in keys if key in saved_settings})
        settings=page_settings(page,settings,preserve_ocr_id=bool(saved_settings))
        folder = store.local / 'ocr' / page_id
        folder.mkdir(parents=True, exist_ok=True)
        def checkpoint(result,responses,result_id):
            created_at=datetime.now(timezone.utc).isoformat()
            archive=folder/f'{result_id}.json'; temporary=archive.with_suffix('.tmp')
            temporary.write_text(json.dumps({'page_id':page_id,'version':data.version,'created_at':created_at,
                'settings':settings,'responses':responses,'response':responses.get('han',[{}])[0],
                'result':result},ensure_ascii=False,indent=2),encoding='utf-8')
            os.replace(temporary,archive)
            if result is not None:
                store.save_ocr(result,settings,created_at)
                if background and apply_texts:
                    store.apply_ocr_texts(result)
        try:
            result=bilingual.recognize(page,settings,data.force,cached=cached,
                image_bytes=lambda:rendered_image(page,high_resolution=True).read_bytes(),han_provider=ocr,vi_provider=vietnamese,save=checkpoint,
                should_pause=(lambda: jobs.stopping.is_set() or (jobs.latest(page['book_id']) or {}).get('status')!='running') if background else None)
        except OCRError as error:
            raise HTTPException(error.status_code,str(error)) from None
        if not background and require_page(page_id)['version'] != data.version:
            raise HTTPException(409, 'Trang đã thay đổi trong lúc OCR. Kết quả gốc đã lưu trong backend/data/.workspace/ocr/; hãy tải lại trang.')
        return result

    @app.post('/api/pages/{page_id}/ocr')
    def recognize_page(page_id: str, data: OCRInput):
        with ocr_lock_guard:
            lock = ocr_locks.setdefault(page_id,threading.Lock())
        with lock:
            return run_page_ocr(page_id, data)

    @app.post('/api/pages/{page_id}/ocr-region')
    def recognize_region(page_id: str,data: RegionOCRInput):
        page=require_page(page_id)
        if page['ocr_skip'] or page['category']=='blank':
            raise HTTPException(422,'Trang đã bỏ qua OCR.')
        if any(x>page['width'] or y>page['height'] for x,y in data.box.points):
            raise HTTPException(422,'Box vượt ra ngoài kích thước ảnh.')
        with ocr_lock_guard:
            lock=ocr_locks.setdefault(page_id,threading.Lock())
        with lock:
            picture=Image.open(rendered_image(page,high_resolution=True))
            crop=crop_selection(picture,data.box.points,page['width'],page['height'])
            try:
                if data.language=='han':
                    saved=recover_ocr(page_id)
                    settings=(saved or {}).get('settings',{})
                    raw=ocr.recognize(jpeg_bytes(crop),
                        ocr_id=settings.get('ocr_id',1),lang_type=settings.get('lang_type',2),
                        reading_direction=data.reading_direction,epitaph=settings.get('epitaph',0),
                        tag=settings.get('tag'),font_type=settings.get('font_type',0))
                    lines=normalize_result(raw,crop.width,crop.height)['text_lines']
                else:
                    result=vietnamese.recognize(jpeg_bytes(crop),han_boxes=[],psm=6)
                    lines=result['text_lines']
            except OCRError as error:
                raise HTTPException(error.status_code,str(error)) from None
        text=('' if data.language=='han' else ' ').join(line.strip() for line in lines if line.strip())
        if not text:
            raise HTTPException(422,'Không nhận dạng được chữ trong box này. Chỉnh box hoặc nhập chữ thủ công.')
        # No page/result/checkpoint writes: the caller keeps this in its unsaved draft.
        return {'box_id':data.box.id,'language':data.language,'text':text}

    def recognize_for_job(page_id,data):
        with ocr_lock_guard:
            lock=ocr_locks.setdefault(page_id,threading.Lock())
        with lock:
            result=run_page_ocr(page_id,OCRInput(**data),background=True,apply_texts=data.get('apply_texts',True))
            if data.get('apply_texts',True):
                store.apply_ocr_texts(result)
        return result

    def normalize_ocr_settings(settings,preserve_ocr_id=False):
        ocr_id=settings.get('ocr_id',1)
        return {**settings,'ocr_id':ocr_id if preserve_ocr_id or ocr_id!=4 else 1,'font_type':settings.get('font_type',0),'pipeline_version':PIPELINE_VERSION}

    def page_settings(page,settings,preserve_ocr_id=False):
        settings=normalize_ocr_settings(settings,preserve_ocr_id)
        mode=page_ocr_mode(page['category'],settings.get('mode','bilingual'))
        if page['ocr_languages'] != ['han','vi']:
            mode='han' if page['ocr_languages']==['han'] else 'vi'
        overrides={key:page[key] for key in ('source_regions','target_regions') if page.get(key) is not None}
        if settings.get('shared_reading_area') and overrides:
            regions=[] if any(not value for value in overrides.values()) else [list(region) for region in dict.fromkeys(tuple(region) for value in overrides.values() for region in value)]
            overrides={'source_regions':regions,'target_regions':regions}
        return {**settings,'mode':mode,**overrides}

    jobs = OCRJobs(store, recognize_for_job,
                   lambda page,settings:bilingual.needs_ocr(page,page_settings(page,settings),recover_ocr(page['id'])))
    app.state.ocr_jobs = jobs

    @app.get('/api/books/{book_id}/ocr-job')
    def latest_book_job(book_id: str):
        require_book(book_id)
        return jobs.latest(book_id)

    @app.post('/api/books/{book_id}/ocr-job')
    def start_book_job(book_id: str, data: OCRBookInput):
        require_book(book_id)
        selected=[p for p in store.pages(book_id) if p['status']!='done' and not p['ocr_skip'] and p['category']!='blank' and p['number']>=data.start_page and (data.end_page is None or p['number']<=data.end_page)]
        modes=[page_settings(p,{'mode':data.mode})['mode'] for p in selected]
        if any(mode!='vi' for mode in modes) and not config.ready:
            raise HTTPException(503, 'Thiếu KHN_token trong backend/.env.')
        if any(mode!='han' for mode in modes) and not vietnamese.status()['ready']:
            raise HTTPException(503,'Chưa cài OCR Quốc ngữ. Cài backend/requirements.txt, chạy '+vietnamese.status()['setup']+' rồi thử lại.')
        max_page = max(p['number'] for p in store.pages(book_id))
        end_page = data.end_page or max_page
        if not data.start_page <= end_page <= max_page:
            raise HTTPException(422, 'Phạm vi trang không hợp lệ.')
        # Include legacy JSON checkpoints before selecting pages to skip.
        for page in store.pages(book_id):
            recover_ocr(page['id'])
        try:
            return jobs.start(book_id, effective_settings(book_id,data) | {'apply_texts':data.apply_texts},
                              data.start_page,end_page,data.include_unclassified)
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

    @app.post('/api/books/{book_id}/workflow')
    def start_workflow(book_id: str,data: WorkflowInput):
        save_book_plan(book_id,BookPlan(pages=data.plan))
        current=jobs.latest(book_id)
        if current and current['status'] in ('running','pausing'):
            return current
        options=data.model_dump(exclude={'plan'},exclude_unset=True)|{'mode':data.mode}
        return start_book_job(book_id,OCRBookInput(**options,include_unclassified=True,apply_texts=True))

    @app.post('/api/ocr-jobs/{job_id}/{action}')
    def control_book_job(job_id: str, action: Literal['pause','resume']):
        if not jobs.get(job_id):
            raise HTTPException(404, 'Không tìm thấy tác vụ OCR.')
        try:
            result=jobs.pause(job_id) if action=='pause' else jobs.resume(job_id)
            store.sync_results(result['book_id'],'ocr_'+action)
            return result
        except ValueError as error:
            raise HTTPException(409, str(error)) from None

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
        valid_images = {p['number'] for p in store.pages(book_id)
                        if not p['ocr_skip'] and p['category'] not in ('blank','misc') and 'han' in p['ocr_languages']}
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
        store.sync_results(book_id,'save_alignments')
        return rows

    @app.get('/api/books/{book_id}/export')
    def export(book_id: str, format: Literal['csv','xlsx','labels']='csv'):
        book = require_book(book_id)
        folder = store.data / 'output_alignment' / book_id
        folder.mkdir(exist_ok=True)
        if format == 'labels':
            store.sync_labels(book_id)
            pages=store.pages(book_id)
            path = folder / f"{book['name']}_{format}.zip"
            temporary = path.with_suffix('.zip.tmp')
            with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for category in CATEGORIES:
                    if category == 'both':
                        continue
                    archive.writestr(f"{book['name']}/{category}/", b'')
                    if category not in ('blank','misc','both'):
                        for name in ('Label.txt','fileState.txt'):
                            archive.write(store.book_dir(book_id)/category/name, f"{book['name']}/{category}/{name}")
                for page in pages:
                    original=rendered_image(page)
                    image_name=f"{book['name']}.{page['number']:03d}.jpg"
                    for category in label_groups(page):
                        archive.write(original,f"{book['name']}/{category}/{image_name}")
            os.replace(temporary,path)
        else:
            rows = get_alignments(book_id)
            if not rows:
                raise HTTPException(400,'Chưa có cặp căn chỉnh. Hãy tạo và lưu các cặp trước khi xuất.')
            if any(not row['source'].strip() or not row['target'].strip() for row in rows):
                raise HTTPException(400,'Còn cặp căn chỉnh thiếu một vế. Hãy sửa hoặc gộp cặp trước khi xuất.')
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
                for column,width in zip('ABCD',(45,48,65,85)):
                    sheet.column_dimensions[column].width = width
                sheet.freeze_panes = 'A2'
                workbook.save(path)
        return FileResponse(path,filename=path.name)

    @app.get('/api/books/{book_id}/results/{filename}')
    def result_file(book_id: str,filename: Literal['summary.json','pages.json','alignments.json','pairs.csv','events.jsonl']):
        require_book(book_id)
        store.sync_results(book_id)
        path=store.data/'output_alignment'/book_id/filename
        if not path.is_file():
            raise HTTPException(404,'Chưa có sự kiện để tải.')
        return FileResponse(path,filename=filename)

    dist = root / 'frontend' / 'dist'
    if dist.exists():
        app.mount('/',StaticFiles(directory=dist,html=True),name='web')
    return app
