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
from fastapi import BackgroundTasks, FastAPI, HTTPException, UploadFile
from fastapi.responses import FileResponse, RedirectResponse
from starlette.background import BackgroundTask
from pydantic import BaseModel, Field, field_validator, model_validator, model_serializer

from .store import CATEGORIES, Store, box_text_lines, source_box_text_lines, label_groups, label_boxes
from .ocr import KHNConfig, KimHanNomOCR, OCRError, normalize_result
from .han_ocr import HanFallbackConfig, PPOCRv5, HanOCRWithFallback
from .sources import source_files
from .dictionary import Dictionary
from .alignment_review import export_text
from .ocr_jobs import OCRJobs


from .vietnamese_ocr import create_vietnamese_ocr
from PIL import Image
from . import bilingual
from .han_layout import PIPELINE_VERSION
from .han_layout import jpeg_bytes
from .region_ocr import crop_selection
from .auto_alignment import index_pages, page_rows as automatic_page_rows, boxes_for_rows
from .new_data import NewData
from .alignment_links import attach_refs, ref_text
from .alignment_output import prepared_rows, write_alignment
from .export_labels import select_label_pages
from .alignment_merge import merge_rows
from .quick_review import QuickReview


Category = Literal['ch', 'vi', 'both', 'intro', 'ref', 'toc', 'blank', 'misc']


class QuickDecisionInput(BaseModel):
    action: Literal['match', 'mismatch', 'unknown', 'defer']
    fingerprint: str = Field(min_length=64, max_length=64)
    source: str | None = Field(default=None, max_length=30000)
    target: str | None = Field(default=None, max_length=30000)


class BoxReviewRange(BaseModel):
    start: int = Field(ge=0)
    end: int = Field(ge=1)
    kind: Literal['match', 'mismatch', 'unknown']

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
    review_kind: Literal['match','mismatch','unknown'] | None = None
    review_marks: list[BoxReviewRange] = Field(default_factory=list, max_length=30000)
    review_order: int | None = Field(default=None, ge=1)
    export_group: str | None = Field(default=None, min_length=1, max_length=100)
    export_order: int | None = Field(default=None, ge=1)
    export_character_order: int | None = Field(default=None, ge=0)
    alignment_id: str | None = Field(default=None, min_length=1, max_length=100)
    box_axis: Literal['vertical','horizontal'] | None = None

    @model_serializer(mode='wrap')
    def serialize_box(self, handler):
        value = handler(self)
        if not value.get('review_marks'):
            value.pop('review_marks', None)
        return value

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

    @model_validator(mode='after')
    def valid_review_marks(self):
        if any(mark.end > len(self.transcription) or mark.end <= mark.start for mark in self.review_marks):
            raise ValueError('Pháº§n tÃ´ mÃ u pháº£i náº±m trong box OCR.')
        return self


def validate_export_order(boxes):
    tagged = [box for box in boxes if box.export_group is not None]
    if not tagged:
        if any(
            box.export_order is not None or box.export_character_order is not None or box.alignment_id is not None
            for box in boxes
        ):
            raise ValueError('Thông tin thứ tự/gán cặp nhãn thiếu nhóm box.')
        return boxes
    if any(
        box.export_order is not None or box.export_character_order is not None
        for box in boxes if box.export_group is None
    ):
        raise ValueError('Box mới không được khai báo thứ tự khi chưa có nhóm.')
    if any(box.export_order is None or box.export_character_order is None for box in tagged):
        raise ValueError('Mỗi box nhãn phải có nhóm và thứ tự hợp lệ.')
    groups = {}
    for box in tagged:
        members = groups.setdefault(box.export_group, [])
        members.append(box)
    ordered_groups = []
    for group, members in groups.items():
        group_orders = {box.export_order for box in members}
        character_orders = [box.export_character_order for box in members]
        if (
            len(group_orders) != 1 or len(set(character_orders)) != len(members)
        ):
            raise ValueError(f'Thứ tự ký tự trong nhóm nhãn {group} không hợp lệ.')
        ordered_groups.append((group_orders.pop(), group, sorted(members, key=lambda box: box.export_character_order)))
    group_order_values = [order for order, _, _ in ordered_groups]
    if len(set(group_order_values)) != len(group_order_values):
        raise ValueError('Số thứ tự box nhãn bị trùng.')
    ordered_groups.sort(key=lambda item: item[0])
    next_order = len(ordered_groups)
    for index, (_, _, members) in enumerate(ordered_groups, 1):
        alignment_ids = {box.alignment_id for box in members}
        if len(alignment_ids) != 1:
            raise ValueError('Các ký tự trong cùng box phải gắn với cùng một cặp căn chỉnh.')
        for character_order, box in enumerate(members):
            box.export_order = index
            box.export_character_order = character_order
    assignments = [
        (order, members[0].alignment_id)
        for order, _, members in ordered_groups
        if members[0].alignment_id is not None
    ]
    assigned_ids = [alignment_id for _, alignment_id in assignments]
    if len(set(assigned_ids)) != len(assigned_ids):
        raise ValueError('Một cặp căn chỉnh chỉ được gán cho một box.')
    for box in boxes:
        if box.export_group is not None:
            continue
        group = box.id
        if group in groups:
            group = uuid4().hex
        next_order += 1
        box.export_group = group
        box.export_order = next_order
        box.export_character_order = 0
        box.alignment_id = None
    return boxes


class PageInput(BaseModel):
    input_revision: str | None = None
    boxes: list[BoxInput] = Field(default_factory=list,max_length=5000)
    vi_boxes: list[BoxInput] | None = Field(default=None,max_length=5000)
    export_boxes: list[BoxInput] | None = Field(default=None,max_length=5000)
    source_text: str | None = Field(default=None,max_length=200000)
    target_text: str | None = Field(default=None,max_length=200000)
    done: bool = False
    category: Category
    version: int = Field(ge=0)
    reading_direction: Literal[1, 2] = 2
    ocr_skip: bool | None = None
    ocr_granularity: Literal['character','phrase'] | None = None

    @model_validator(mode='after')
    def valid_export_order(self):
        orders = [box.review_order for box in self.boxes]
        if any('review_order' in box.model_fields_set for box in self.boxes) and sorted(orders, key=lambda value: value or 0) != list(range(1, len(orders) + 1)):
            raise ValueError('Số thứ tự box OCR phải liên tục từ 1 và không được trùng.')
        validate_export_order(self.boxes)
        if self.vi_boxes is not None:
            validate_export_order(self.vi_boxes)
        if self.export_boxes is not None:
            validate_export_order(self.export_boxes)
        return self


class PagePatch(BaseModel):
    version: int | None = None
    input_revision: str | None = None
    source_text: str | None = Field(default=None,max_length=200000)
    target_text: str | None = Field(default=None,max_length=200000)
    boxes: list[BoxInput] | None = Field(default=None,max_length=5000)
    vi_boxes: list[BoxInput] | None = Field(default=None,max_length=5000)
    export_boxes: list[BoxInput] | None = Field(default=None,max_length=5000)
    category: Category | None = None
    reading_direction: Literal[1,2] | None = None
    reading_direction_override: Literal[1,2] | None = None
    ocr_skip: bool | None = None
    ocr_languages: list[Literal['han','vi']] | None = Field(default=None,min_length=1,max_length=2)
    ocr_granularity: Literal['character','phrase'] | None = None
    source_regions: list[tuple[float,float,float,float]] | None = Field(default=None,max_length=100)
    target_regions: list[tuple[float,float,float,float]] | None = Field(default=None,max_length=100)

    @field_validator('source_regions','target_regions')
    @classmethod
    def valid_regions(cls,regions):
        return validate_regions(regions)

    @model_validator(mode='after')
    def valid_export_order(self):
        for boxes in (self.boxes, self.vi_boxes, self.export_boxes):
            if boxes is not None:
                validate_export_order(boxes)
        return self


class PagePlan(BaseModel):
    page_id: str
    category: Category
    ocr_skip: bool = False


class BookPlan(BaseModel):
    input_revision: str | None = None
    pages: list[PagePlan] = Field(max_length=20000)


class PageLinksInput(BaseModel):
    input_revision: str | None = None
    linked_page_ids: list[str] = Field(default_factory=list,max_length=20000)


class SessionInput(BaseModel):
    input_revision: str | None = None
    page_id: str | None = None
    alignment_page: str | None = None
    view: Literal['overview','library','review','alignment','export','quick'] = 'review'
    workflow_step: Literal[1,2,3,4] = 1


class ImportInput(BaseModel):
    filename: str


class TextSourceInput(BaseModel):
    input_revision: str | None = None
    filename: str = Field(min_length=1,max_length=255)
    text: str = Field(max_length=2000000)


def validate_regions(regions):
    for region in regions or []:
        left,top,right,bottom=region
        if not all(math.isfinite(value) for value in region) or not 0<=left<right<=1 or not 0<=top<bottom<=1:
            raise ValueError('Vùng mẫu phải có diện tích dương và tọa độ chuẩn hóa từ 0 đến 1.')
    return regions


class LayoutInput(BaseModel):
    input_revision: str | None = None
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
    reading_direction: Literal[1, 2] = 2
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
    input_revision: str | None = None
    start_page: int = Field(default=1, ge=1)
    end_page: int | None = Field(default=None, ge=1)
    include_unclassified: bool = False
    apply_texts: bool = True


class WorkflowInput(OCRSettings):
    input_revision: str | None = None
    mode: Literal['bilingual','han','vi'] = 'bilingual'
    plan: list[PagePlan] = Field(default_factory=list,max_length=20000)


class ReviewMark(BaseModel):
    source_start: int = Field(ge=0)
    source_end: int = Field(ge=0)
    target_start: int = Field(ge=0)
    target_end: int = Field(ge=0)
    kind: Literal['match', 'mismatch', 'unknown']


class BoxReference(BaseModel):
    box_id: str = Field(min_length=1, max_length=100)
    start: int = Field(ge=0)
    end: int = Field(gt=0)

    @model_validator(mode='after')
    def valid_range(self):
        if self.end <= self.start:
            raise ValueError('Phạm vi chữ trong box không hợp lệ.')
        return self


class AlignmentInput(BaseModel):
    alignment_version: int | None = None
    id: str = Field(min_length=1, max_length=100)
    sentence_id: str = Field(min_length=1, max_length=300)
    source: str = Field(max_length=100000)
    target: str = Field(max_length=100000)
    reviewed: bool = False
    page_linked: bool = False
    source_page_id: str | None = None
    source_line_index: int | None = Field(default=None,ge=0)
    target_page_id: str | None = None
    target_line_index: int | None = Field(default=None,ge=0)
    source_refs: list[BoxReference] = Field(default_factory=list, max_length=5000)
    target_refs: list[BoxReference] = Field(default_factory=list, max_length=5000)
    marks: list[ReviewMark] = Field(default_factory=list, max_length=1000)

    @model_validator(mode='after')
    def valid_page_provenance(self):
        if self.source_line_index is not None and not self.source_page_id:
            raise ValueError('Dòng Hán Nôm cần ID trang nguồn.')
        if self.target_line_index is not None and not self.target_page_id:
            raise ValueError('Dòng Quốc ngữ cần ID trang nguồn.')
        return self


class AlignmentsInput(BaseModel):
    alignment_version: int | None = None
    rows: list[AlignmentInput] = Field(max_length=50000)
    input_revision: str | None = None
    base_rows: list[AlignmentInput] | None = Field(default=None, max_length=50000)


def create_app(root: Path | None = None, *, ocr_config: KHNConfig | None = None, ocr_transport=None, vi_provider=None, han_fallback_provider=None):
    root = (root or Path(os.environ.get('CORPUS_ROOT', Path(__file__).resolve().parents[1]))).resolve()
    store = Store(root)
    new_data = NewData(store)
    @asynccontextmanager
    async def lifespan(app):
        yield
        await asyncio.to_thread(jobs.close)
        await asyncio.to_thread(quick_review.close)

    app = FastAPI(title='Nôm · Local Corpus Workbench', version='0.1.0', lifespan=lifespan)
    app.state.store = store
    config = ocr_config if ocr_config is not None else KHNConfig.from_env(root / 'backend' / '.env')
    fallback = han_fallback_provider if han_fallback_provider is not None else PPOCRv5(HanFallbackConfig.from_env(root / 'backend' / '.env'))
    ocr = HanOCRWithFallback(KimHanNomOCR(config, transport=ocr_transport), fallback)
    vietnamese=vi_provider or create_vietnamese_ocr(root)
    raw_folder = store.data / 'raw_data'
    source_errors = []
    dictionary = Dictionary(store.data / 'dictionaries')
    quick_review = QuickReview(store)
    app.state.quick_review = quick_review
    ocr_locks = {}
    ocr_lock_guard = threading.Lock()

    def require_book(book_id):
        book = store.book(book_id)
        if not book or not book['source'] or not (raw_folder / book['filename']).is_file():
            raise HTTPException(404, 'Không tìm thấy sách.')
        return book

    def require_page(page_id):
        page = store.page(page_id)
        if not page:
            raise HTTPException(404, 'Không tìm thấy trang.')
        require_book(page['book_id'])
        return page

    def require_revision(book_id, revision):
        current = require_book(book_id)['input_revision']
        if current and current != revision:
            raise HTTPException(409, 'Bản dữ liệu đã thay đổi. Tải lại trước khi lưu; không ghi bản nháp cũ vào bản mới.')

    def validate_filename(name):
        if not name or any(c in name for c in ('/', '\\', '\t', '\r', '\n', '\x00', ':', '<', '>', '"', '|', '?', '*')) or Path(name).suffix.lower() != '.pdf':
            raise HTTPException(400, 'Tên nguồn phải là tên file PDF, không chứa đường dẫn.')
        return name

    def pdf_dimensions(source):
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
        return dimensions

    def import_pdf(source: Path, filename: str):
        validate_filename(filename)
        if any(b['filename'].casefold() == filename.casefold() for b in store.books()):
            raise HTTPException(409, 'Sách này đã có trong tủ sách. Hãy mở sách hiện có để tiếp tục.')
        dimensions = pdf_dimensions(source)
        book_id = uuid4().hex
        destination = raw_folder / filename
        copy_source = source.resolve() != destination.resolve()
        if copy_source and destination.exists():
            raise HTTPException(409, 'File nguồn đã tồn tại. Quét lại thư mục để mở sách, không ghi đè PDF.')
        try:
            if copy_source:
                shutil.copyfile(source, destination)
            with store.db() as db:
                db.execute('INSERT INTO books VALUES (?,?,?,?,?,?)', (book_id, Path(filename).stem, filename, destination.relative_to(root).as_posix(), 0, datetime.now(timezone.utc).isoformat()))
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
                        db.execute('UPDATE books SET source=? WHERE id=?', (source.relative_to(root).as_posix(), existing['id']))
                    continue
                try:
                    book = import_pdf(source, source.name)
                    known[source.name.casefold()] = book
                except HTTPException as error:
                    source_errors.append({'filename':source.name, 'message':str(error.detail)})
        new_data.sync(source_errors)

    def text_sources(book_id):
        with store.db() as db:
            return {row['language']:{'filename':row['filename'],'text':row['text']} for row in
                    db.execute('SELECT * FROM book_text_sources WHERE book_id=?',(book_id,))}

    def book_summary(book):
        reference=text_sources(book['id']).get('vi')
        imported = new_data.summary(book['id'])
        return book | {'reference_file':reference['filename'] if reference else None,
                       'has_new_data': bool(imported['new_data_pages']), **imported,
                       'has_pdf': bool(store.book(book['id'])['source']),
                       'pair_stats': store.pair_stats(book['id'])}

    # Index every local PDF; no seeded data, fixed book count, copying or OCR calls.
    sync_sources()

    def rendered_image(page, high_resolution=False):
        imported = new_data.image(page['id'])
        if imported:
            if not imported.is_file():
                raise HTTPException(404, 'Không còn ảnh dữ liệu mới. Khôi phục ảnh trong data/new rồi quét lại.')
            if imported.suffix.casefold() == '.png':
                cache = store.local / 'input-images' / f"{page['id']}-{imported.stat().st_mtime_ns}.jpg"
                if cache.is_file():
                    return cache
                with store.lock:
                    if not cache.is_file():
                        cache.parent.mkdir(parents=True, exist_ok=True)
                        with Image.open(imported) as picture:
                            picture.convert('RGB').save(cache, format='JPEG', quality=95)
                return cache
            return imported
        book = require_book(page['book_id'])
        filename = f"{book['name']}.{page['number']:03d}.jpg"
        cache = store.data / 'processed_images' / book['id'] / filename
        if high_resolution:
            cache = store.local / 'ocr-images' / book['id'] / filename
        category_image = store.book_dir(book['id']) / page['category'] / filename
        if cache.is_file() and (high_resolution or category_image.is_file()):
            return cache
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
            category_image.parent.mkdir(parents=True, exist_ok=True)
            if not high_resolution and not category_image.exists():
                shutil.copyfile(cache, category_image)
        return cache

    @app.get('/api/health')
    def health():
        return {'status':'ok', 'ocr':'configured' if ocr.ready else 'not_configured'}

    @app.get('/api/workspace')
    def workspace():
        with store.lock:
            return workspace_snapshot()

    def workspace_snapshot():
        return {
            'books': [book_summary(book) for book in store.books()],
            'pair_stats': store.pair_stats(),
            'ocr_ready': ocr.ready,
            'han_ocr': {'primary_ready': config.ready, 'fallback': fallback.status()},
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

    @app.get('/api/nom-dictionary/search')
    def nom_search(q: str = ''):
        if len(q) > 100:
            raise HTTPException(422, 'Từ khóa tối đa 100 ký tự.')
        return quick_review.dictionary.search(q)

    @app.get('/api/nom-dictionary/detail')
    def nom_detail(character: str):
        try:
            return quick_review.dictionary.detail(character)
        except Exception as error:
            raise HTTPException(502, 'Chưa lấy được nghĩa đầy đủ từ Nôm Na Việt. Bạn vẫn có thể dùng bảng âm cục bộ hoặc mở trang nguồn.') from error

    @app.get('/api/books/{book_id}/quick-review')
    def quick_status(book_id: str, include_deferred: bool = False):
        require_book(book_id)
        return quick_review.status(book_id, include_deferred)

    @app.post('/api/books/{book_id}/quick-review/scan')
    def quick_scan(book_id: str):
        require_book(book_id)
        return quick_review.start(book_id)

    @app.post('/api/books/{book_id}/quick-review/{card_id}/decide')
    def quick_decide(book_id: str, card_id: str, data: QuickDecisionInput):
        require_book(book_id)
        try:
            quick_review.decide(book_id, card_id, data.action, data.fingerprint, data.source, data.target)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {'saved': True}

    @app.post('/api/books/{book_id}/quick-review/undo')
    def quick_undo(book_id: str):
        require_book(book_id)
        try:
            quick_review.undo(book_id)
        except ValueError as error:
            raise HTTPException(409, str(error)) from error
        return {'saved': True}

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
            require_revision(book_id, data.input_revision)
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
        profile=data.model_dump(exclude_none=True, exclude={'input_revision'})
        with store.lock:
            require_revision(book_id, data.input_revision)
            previous=store.book_layout(book_id)
            if 'reading_direction' not in profile and 'reading_direction' in previous:
                profile['reading_direction']=previous['reading_direction']
            with store.db() as db:
                db.execute('INSERT INTO book_layouts VALUES (?,?) ON CONFLICT(book_id) DO UPDATE SET profile=excluded.profile',
                           (book_id,json.dumps(profile)))
                changed=[key for key in ('source_regions','target_regions') if json.dumps(previous[key])!=json.dumps(profile[key])]
                direction_changed=profile.get('reading_direction',2)!=previous.get('reading_direction',2)
                if changed or direction_changed:
                    inherited=' OR '.join([
                        *(["reading_direction_override IS NULL AND category!='vi'"] if direction_changed else []),
                        *(key+' IS NULL' for key in changed),
                    ])
                    db.execute("UPDATE pages SET reading_direction=CASE WHEN category='vi' THEN 2 WHEN reading_direction_override IS NULL THEN ? ELSE reading_direction END,status='pending',version=version+1 WHERE book_id=? AND ocr_skip=0 AND category!='blank' AND ("+inherited+')',
                               (profile.get('reading_direction',2),book_id))
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
    def pages(book_id: str, include_export_boxes: bool = True):
        require_book(book_id)
        return store.pages(book_id, include_export_boxes=include_export_boxes)

    @app.get('/api/pages/{page_id}')
    def get_page(page_id: str):
        return require_page(page_id)

    @app.get('/api/pages/{page_id}/image')
    def image(page_id: str, thumbnail: bool = False):
        # Images need location metadata, not OCR boxes or the book's alignment JSON.
        with store.db() as db:
            row = db.execute('SELECT id,book_id,number,category FROM pages WHERE id=?', (page_id,)).fetchone()
        if row is None:
            raise HTTPException(404, 'Không tìm thấy trang.')
        page = dict(row)
        require_book(page['book_id'])
        original = rendered_image(page,high_resolution=not thumbnail)
        if thumbnail:
            thumb = store.local / 'thumbnails' / f"{page_id}-{original.stat().st_mtime_ns}.jpg"
            if thumb.is_file():
                return FileResponse(thumb,media_type='image/jpeg')
            with store.lock:
                if not thumb.exists():
                    thumb.parent.mkdir(parents=True, exist_ok=True)
                    pix = pymupdf.Pixmap(str(original))
                    shrink = max(0, math.floor(math.log2(max(pix.width/160, pix.height/220))))
                    if shrink:
                        pix.shrink(shrink)
                    thumb.write_bytes(pix.tobytes('jpeg', jpg_quality=75))
            return FileResponse(thumb,media_type='image/jpeg')
        return FileResponse(original,media_type='image/jpeg')

    @app.put('/api/pages/{page_id}')
    def save_page(page_id: str, data: PageInput, background_tasks: BackgroundTasks):
        with store.lock:
            page = require_page(page_id)
            require_revision(page['book_id'], data.input_revision)
            if page['target_origin'] == 'new_data':
                data.ocr_granularity = 'phrase'
            page_boxes=[*data.boxes,*(data.vi_boxes or []),*(data.export_boxes or [])]
            if any(x>page['width'] or y>page['height'] for box in page_boxes for x,y in box.points):
                raise HTTPException(422, 'Box vượt ra ngoài kích thước ảnh.')
            if any(len({b.id for b in boxes}) != len(boxes) for boxes in (data.boxes,data.vi_boxes or [],data.export_boxes or [])):
                raise HTTPException(422, 'ID box bị trùng.')
            source_text=page['source_text'] if data.source_text is None else data.source_text
            target_text=page['target_text'] if data.target_text is None else data.target_text
            if data.boxes or page['boxes']:
                source_text='\n'.join(source_box_text_lines(
                    [box.model_dump(mode='json',exclude_none=True) for box in data.boxes],
                    page['reading_direction'],(page['width'],page['height']),
                    data.ocr_granularity or page['ocr_granularity'],
                ))
            target_boxes=([box.model_dump(mode='json',exclude_none=True) for box in data.vi_boxes]
                          if data.vi_boxes is not None else page['vi_boxes'])
            if target_boxes:
                target_text='\n'.join(box_text_lines(
                    target_boxes,
                    2,'vi',(page['width'],page['height']),
                ))
            if data.done and ('□' in source_text or any('□' in box.transcription for box in data.boxes)):
                raise HTTPException(422,'Còn ký tự □ chưa nhận dạng. Sửa các ô này trước khi hoàn thành trang.')
            if data.done and any(not box.transcription.strip() for box in data.boxes):
                raise HTTPException(422,'Còn box chưa có chữ. Điền ký tự trước khi hoàn thành trang.')
            if data.done and not page['ocr_skip'] and page['category']!='blank':
                with store.db() as db:
                    active=db.execute("SELECT 1 FROM ocr_job_pages p JOIN ocr_jobs j ON j.id=p.job_id WHERE p.page_id=? AND p.status IN ('pending','running') AND j.status IN ('running','pausing')",(page_id,)).fetchone()
                if active:
                    raise HTTPException(409,'Chờ OCR trang này hoàn tất trước khi xác nhận.')
            languages = page['ocr_languages'] if data.category in ('intro','ref','toc') else (['han'] if data.category=='ch' else ['vi'] if data.category=='vi' else ['han','vi'])
            if data.done and not (page['ocr_skip'] if data.ocr_skip is None else data.ocr_skip) and data.category not in ('blank','misc'):
                vi_boxes = data.vi_boxes if data.vi_boxes is not None else page['vi_boxes']
                if ('han' in languages and not data.boxes) or ('vi' in languages and not vi_boxes):
                    raise HTTPException(422, 'Trang cần box thật cho từng ngôn ngữ trước khi hoàn thành. Kiểm tra OCR hoặc vẽ box thủ công.')
                if 'han' in languages and not data.ocr_granularity and not page['ocr_granularity']:
                    raise HTTPException(422, 'Chọn OCR theo chữ hoặc theo cụm trước khi hoàn thành trang.')
                if 'han' in languages and (data.ocr_granularity or page['ocr_granularity']) == 'character' and any(len(box.transcription.strip()) != 1 for box in data.boxes):
                    raise HTTPException(422, 'OCR theo chữ cần mỗi box Hán Nôm chứa đúng một chữ. Hãy tách box hoặc chọn theo cụm.')
            boxes = [b.model_dump(mode='json',exclude_none=True) for b in data.boxes]
            export_boxes = [b.model_dump(mode='json',exclude_none=True) for b in data.export_boxes] if data.export_boxes is not None else None
            try:
                with store.db() as db:
                    updates=['boxes=?','status=?','category=?','reading_direction=?','source_text=?','target_text=?','vi_boxes=?','ocr_granularity=?']
                    values=[json.dumps(boxes,ensure_ascii=False),'done' if data.done else 'pending',data.category,2 if languages==['vi'] else page['reading_direction_override'] or data.reading_direction,
                            source_text,target_text,json.dumps([b.model_dump(exclude_none=True) for b in data.vi_boxes],ensure_ascii=False) if data.vi_boxes is not None else json.dumps(page['vi_boxes'],ensure_ascii=False),data.ocr_granularity or page['ocr_granularity']]
                    if languages==['vi']:
                        updates.append('reading_direction_override=?')
                        values.append(None)
                    if export_boxes is not None:
                        updates.append('export_boxes=?')
                        values.append(json.dumps(export_boxes,ensure_ascii=False))
                    values.extend((page_id,data.version))
                    result = db.execute('UPDATE pages SET '+','.join(updates)+',version=version+1 WHERE id=? AND version=?',values)
                    if result.rowcount != 1:
                        raise HTTPException(409, 'Trang đã được cập nhật ở cửa sổ khác. Hãy tải lại trang trước khi lưu.')
                    edited=set(page['edited_fields'])
                    if data.source_text is not None and source_text!=page['source_text']:
                        edited.add('source_text')
                    if data.target_text is not None and target_text!=page['target_text']:
                        edited.add('target_text')
                    if boxes!=page['boxes']:
                        edited.add('boxes')
                    if data.vi_boxes is not None and [b.model_dump(mode='json',exclude_none=True) for b in data.vi_boxes]!=page['vi_boxes']:
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
            deleted = store.sync_deleted_source_boxes(page, require_page(page_id))
            store.sync_alignment_page_text(page,source_text if deleted else page['source_text'],page['target_text'],source_text,target_text)
            store.prepare_label_checkpoint(page['book_id'])
            background_tasks.add_task(store.sync_labels, page['book_id'], checkpoint=False)
            return require_page(page_id)

    @app.patch('/api/pages/{page_id}')
    def patch_page(page_id: str,data: PagePatch, background_tasks: BackgroundTasks):
        # Field-level autosave permits editing one language while the other finishes OCR.
        with store.lock:
            page=require_page(page_id)
            require_revision(page['book_id'], data.input_revision)
            if data.version is not None and data.version != page['version']:
                raise HTTPException(409, 'Trang đã thay đổi ở màn hình khác. Tải bản đã lưu trước khi tiếp tục sửa.')
            changes={key:value for key,value in data.model_dump(exclude_unset=True,mode='json',exclude={'input_revision','version'}).items() if value is not None or key in ('source_regions','target_regions','reading_direction_override')}
            if page['target_origin'] == 'new_data' and 'ocr_granularity' in changes:
                changes['ocr_granularity'] = 'phrase'
            if 'ocr_languages' in changes:
                languages=[language for language in ('han','vi') if language in changes['ocr_languages']]
                changes['ocr_languages']=json.dumps(languages)
                if page['category'] in ('ch','vi','both') and 'category' not in changes:
                    changes['category']='both' if len(languages)==2 else 'ch' if languages==['han'] else 'vi'
            elif changes.get('category') in ('ch','vi','both'):
                changes['ocr_languages']=json.dumps(['han'] if changes['category']=='ch' else ['vi'] if changes['category']=='vi' else ['han','vi'])
            elif 'category' in changes:
                changes['ocr_languages']=json.dumps(page['ocr_languages'])
            effective_languages=json.loads(changes['ocr_languages']) if 'ocr_languages' in changes else page['ocr_languages']
            if effective_languages==['vi'] and changes.get('category',page['category']) not in ('blank','misc'):
                changes['reading_direction_override']=None
                changes['reading_direction']=2
            elif 'reading_direction_override' in changes:
                changes['reading_direction']=changes['reading_direction_override'] or store.book_layout(page['book_id']).get('reading_direction',2)
            effective_direction=changes.get('reading_direction',page['reading_direction'])
            source_boxes=changes.get('boxes',page['boxes'])
            if (source_boxes or 'boxes' in changes) and ('boxes' in changes or 'source_text' in changes or 'ocr_granularity' in changes):
                changes['source_text']='\n'.join(source_box_text_lines(
                    source_boxes,effective_direction,(page['width'],page['height']),
                    changes.get('ocr_granularity',page['ocr_granularity']),
                ))
            target_boxes=changes.get('vi_boxes',page['vi_boxes'])
            if target_boxes and ('vi_boxes' in changes or 'target_text' in changes):
                changes['target_text']='\n'.join(box_text_lines(
                    target_boxes,2,'vi',(page['width'],page['height']),
                ))
            if not changes:
                return page
            edited=set(page['edited_fields'])
            edited.update(key for key in ('source_text','target_text','boxes','vi_boxes') if key in changes and changes[key]!=page[key])
            changes['edited_fields']=json.dumps(sorted(edited))
            for key in ('boxes','vi_boxes','export_boxes'):
                if key in changes:
                    if any(x>page['width'] or y>page['height'] for box in changes[key] for x,y in box['points']):
                        raise HTTPException(422,'Box vượt ra ngoài kích thước ảnh.')
                    if len({box['id'] for box in changes[key]}) != len(changes[key]):
                        raise HTTPException(422,'ID box bị trùng.')
                    changes[key]=json.dumps(changes[key],ensure_ascii=False)
            for key in ('source_regions','target_regions'):
                if key in changes and changes[key] is not None:
                    changes[key]=json.dumps(changes[key])
            if 'ocr_skip' in changes:
                changes['ocr_skip']=int(changes['ocr_skip'])
            invalidates_review = any(key in changes for key in (
                'category','ocr_skip','ocr_languages','source_regions','target_regions',
            ))
            try:
                with store.db() as db:
                    status_update = ",status='pending'" if invalidates_review else ''
                    db.execute('UPDATE pages SET '+','.join(key+'=?' for key in changes)+status_update+",version=version+1 WHERE id=?",(*changes.values(),page_id))
            except sqlite3.IntegrityError:
                raise HTTPException(409,'Trang đã có trong nhóm này.') from None
            if 'source_text' in changes:
                store.propagate_placeholder_edits(page['book_id'],page['number'],page['source_text'],changes['source_text'])
            if data.boxes is not None:
                current = require_page(page_id)
                deleted = store.sync_deleted_source_boxes(page, current)
            else:
                deleted = False
            store.sync_alignment_page_text(page,changes.get('source_text',page['source_text']) if deleted else page['source_text'],page['target_text'],
                                           changes.get('source_text',page['source_text']),
                                           changes.get('target_text',page['target_text']))
            store.prepare_label_checkpoint(page['book_id'])
            background_tasks.add_task(store.sync_labels, page['book_id'], checkpoint=False)
            return require_page(page_id)

    @app.get('/api/books/{book_id}/session')
    def book_session(book_id: str):
        require_book(book_id)
        return store.session('book:'+book_id)

    @app.put('/api/books/{book_id}/session')
    def save_book_session(book_id: str,data: SessionInput):
        require_book(book_id)
        require_revision(book_id, data.input_revision)
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
            require_revision(book_id, data.input_revision)
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
                            db.execute("UPDATE pages SET category=?,ocr_languages=?,ocr_skip=?,reading_direction_override=CASE WHEN ?='vi' THEN NULL ELSE reading_direction_override END,reading_direction=CASE WHEN ?='vi' THEN 2 ELSE reading_direction END,status='pending',version=version+1 WHERE id=? AND (category!=? OR ocr_skip!=? OR COALESCE(ocr_languages,'')!=? OR (?='vi' AND (reading_direction_override IS NOT NULL OR reading_direction!=2)))",
                                       (page.category,encoded,int(page.ocr_skip),page.category,page.category,page.page_id,page.category,int(page.ocr_skip),encoded,page.category))
            except sqlite3.IntegrityError:
                raise HTTPException(409,'Trang bị trùng trong nhóm; giữ bản ngôn ngữ chính trước khi đổi nhãn.') from None
            store.sync_labels(book_id)
        return store.pages(book_id)

    @app.put('/api/pages/{page_id}/links')
    def save_page_links(page_id: str,data: PageLinksInput):
        page=require_page(page_id)
        require_revision(page['book_id'], data.input_revision)
        linked=set(data.linked_page_ids)
        if page_id in linked or len(linked)!=len(data.linked_page_ids):
            raise HTTPException(422,'Danh sách trang liên kết bị trùng hoặc chứa chính trang này.')
        with store.lock,store.db() as db:
            known={row['id'] for row in db.execute('SELECT id FROM pages WHERE book_id=?',(page['book_id'],))}
            if not linked<=known:
                raise HTTPException(422,'Trang liên kết phải thuộc cùng sách.')
            db.execute('DELETE FROM page_links WHERE book_id=? AND (page_a=? OR page_b=?)',
                       (page['book_id'],page_id,page_id))
            db.executemany('INSERT INTO page_links(book_id,page_a,page_b) VALUES (?,?,?)',
                           [(page['book_id'],*sorted((page_id,other))) for other in linked])
        store.sync_results(page['book_id'],'save_page_links')
        return store.pages(page['book_id'])

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
        settings=data.model_dump(exclude={'version','force','reuse_saved_settings','start_page','end_page','include_unclassified','apply_texts','input_revision'})
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
            return {'box_id':data.box.id,'language':data.language,'text':''}
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
        # The page's effective direction is user configuration (book default or
        # page override). Reused OCR settings must never replace it with an old value.
        overrides['reading_direction'] = 2 if mode=='vi' else page.get('reading_direction_override')
        if overrides['reading_direction'] is None:
            overrides['reading_direction'] = store.book_layout(page['book_id']).get(
                'reading_direction', 2,
            )
        return {**settings,'mode':mode,**overrides}

    jobs = OCRJobs(store, recognize_for_job,
                   lambda page,settings:not new_data.image(page['id']) and
                   bilingual.needs_ocr(page,page_settings(page,settings),recover_ocr(page['id'])))
    app.state.ocr_jobs = jobs

    def stop_replaced_book(book_id):
        current = jobs.latest(book_id)
        if current:
            if current['status'] in ('running', 'pausing'):
                jobs.pause(current['id'])
            future = jobs.futures.get(current['id'])
            if future:
                future.result()

    new_data.before_replace = stop_replaced_book

    @app.get('/api/books/{book_id}/ocr-job')
    def latest_book_job(book_id: str):
        require_book(book_id)
        return jobs.latest(book_id)

    @app.post('/api/books/{book_id}/ocr-job')
    def start_book_job(book_id: str, data: OCRBookInput):
        require_book(book_id)
        require_revision(book_id, data.input_revision)
        selected=[p for p in store.pages(book_id) if p['status']!='done' and not p['ocr_skip'] and p['category']!='blank' and not new_data.image(p['id']) and p['number']>=data.start_page and (data.end_page is None or p['number']<=data.end_page)]
        modes=[page_settings(p,{'mode':data.mode})['mode'] for p in selected]
        if any(mode!='vi' for mode in modes) and not ocr.ready:
            raise HTTPException(503, 'Thiếu KHN_token và PP-OCRv5 CPU chưa sẵn sàng. Cài backend/requirements-han-fallback.txt hoặc cấu hình KHN_token.')
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
        save_book_plan(book_id,BookPlan(pages=data.plan,input_revision=data.input_revision))
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
        with store.lock:
            deleted = store.reconcile_deleted_source_boxes(book_id)
            if store.reconcile_alignment_ocr(book_id) or deleted:
                store.sync_results(book_id,'reconcile_alignment_ocr')
        with store.db() as db:
            row = db.execute('SELECT rows FROM alignments WHERE book_id=?',(book_id,)).fetchone()
        return store.describe_alignments(book_id, json.loads(row['rows']) if row else [])

    @app.post('/api/books/{book_id}/alignments/prepare')
    def prepare_alignments(book_id: str):
        """Fill untouched OCR pages and their export boxes before human review."""
        book = require_book(book_id)
        with store.lock:
            deleted = store.reconcile_deleted_source_boxes(book_id)
            reconciled = store.reconcile_alignment_ocr(book_id)
            pages = store.pages(book_id)
            page_indexes = index_pages(pages)
            with store.db() as db:
                saved = db.execute('SELECT rows FROM alignments WHERE book_id=?', (book_id,)).fetchone()
            rows = json.loads(saved['rows']) if saved else []
            rows_by_page = {}
            book_prefix = f"{book['name']}."
            for row in rows:
                sentence_id = row['sentence_id']
                if not sentence_id.startswith(book_prefix):
                    continue
                page_number, separator, _ = sentence_id[len(book_prefix):].partition('.')
                if separator and len(page_number) >= 3 and page_number.isdigit():
                    rows_by_page.setdefault(int(page_number), []).append(row)
            source_pages = [page for page in pages if not page['ocr_skip']
                            and page['category'] not in ('blank', 'misc')
                            and 'han' in page['ocr_languages']
                            and (page['source_text'].strip() or page['boxes'])
                            and not new_data.image(page['id'])]
            for page in source_pages:
                if not page['ocr_granularity']:
                    page['ocr_granularity'] = ('phrase' if any(len(box['transcription'].strip()) > 1
                        for box in page['boxes']) else 'character')
            reference = text_sources(book_id).get('vi', {}).get('text', '')
            if reference and not (re.search(r'^\s*\*+\s*Page\s+\d+\s*\*+\s*$', reference, re.I | re.M)
                                  or '\f' in reference or len(source_pages) == 1):
                reference = ''
            created = 0
            boxes_created = 0
            boxes_removed = 0
            boxes_renumbered = 0
            for page in source_pages:
                page_pairs = rows_by_page.get(page['number'], [])
                if (page_pairs and page['ocr_granularity'] == 'phrase'
                        and 'boxes' in page['edited_fields']):
                    fresh = automatic_page_rows(page, pages, book['name'], reference, page_indexes)
                    legacy_grouping = (
                        len(page_pairs) < len(fresh)
                        and ''.join(row['source'] for row in page_pairs) == ''.join(row['source'] for row in fresh)
                        and all(not row.get('reviewed') and not row.get('marks') for row in page_pairs)
                    )
                    if len(page_pairs) >= len(fresh) or legacy_grouping:
                        fresh = []
                    used_indexes = set()
                    source_pairs = sorted(
                        (row for row in page_pairs
                         if row.get('source_page_id') in (None, page['id'])),
                        key=lambda row: row.get('source_line_index')
                        if isinstance(row.get('source_line_index'), int) else float('inf'),
                    )

                    def normalized_source(value):
                        return re.sub(r'\s+', '', value or '')

                    # Re-anchor by matching text; a legacy index alone cannot
                    # distinguish corrected text from an inserted/reordered line.
                    unmatched = []
                    for row in (source_pairs if fresh else []):
                        expected = normalized_source(row['source'])
                        old_index = row.get('source_line_index')
                        candidates = [index for index, current in enumerate(fresh)
                                      if index not in used_indexes
                                      and normalized_source(current['source']) == expected]
                        if candidates:
                            index = min(candidates, key=lambda item: (
                                abs(item - old_index) if isinstance(old_index, int) else item,
                                item,
                            ))
                            row['source_line_index'] = index
                            row['source_page_id'] = page['id']
                            used_indexes.add(index)
                        else:
                            unmatched.append(row)

                    if unmatched:
                        # Preserve manual pairs and defer additions until the
                        # ambiguous page has been linked explicitly.
                        used_indexes.update(range(len(fresh)))

                    existing_sentence_ids = {row['sentence_id'] for row in rows}
                    next_sentence_number = max(
                        (int(row['sentence_id'].rsplit('.', 1)[-1]) for row in rows
                         if row['sentence_id'].startswith(f"{book['name']}.{page['number']:03d}.")
                         and row['sentence_id'].rsplit('.', 1)[-1].isdigit()),
                        default=0,
                    ) + 1
                    added = []
                    for index, current in enumerate(fresh):
                        if index in used_indexes:
                            continue
                        candidate = dict(current)
                        if candidate['sentence_id'] in existing_sentence_ids:
                            candidate['sentence_id'] = f"{book['name']}.{page['number']:03d}.{next_sentence_number}"
                            next_sentence_number += 1
                        existing_sentence_ids.add(candidate['sentence_id'])
                        added.append(candidate)
                        used_indexes.add(index)
                    if added:
                        rows.extend(added)
                        page_pairs.extend(added)
                        rows_by_page[page['number']] = page_pairs
                        created += len(added)
                    page_pairs.sort(key=lambda row: (
                        row.get('source_line_index')
                        if isinstance(row.get('source_line_index'), int) else float('inf'),
                        row['sentence_id'],
                    ))

                if page_pairs and page['ocr_granularity'] == 'phrase' and len(page_pairs) < len(page['boxes']):
                    fresh = automatic_page_rows(page, pages, book['name'], reference, page_indexes)
                    old_boxes = {box.get('alignment_id'): box for box in page['export_boxes'] if box.get('alignment_id')}
                    expected_boxes = boxes_for_rows(page, page_pairs)
                    untouched = (
                        len(fresh) == len(page['boxes']) and len(expected_boxes) == len(page_pairs)
                        and all(not row['reviewed'] and not row.get('marks')
                                and row.get('source_page_id') == page['id']
                                and row.get('source_line_index') == index
                                and row['target'] == fresh[index]['target']
                                and row.get('target_page_id') == fresh[index].get('target_page_id')
                                and row.get('target_line_index') == fresh[index].get('target_line_index')
                                for index, row in enumerate(page_pairs))
                        and ''.join(row['source'] for row in page_pairs) == ''.join(box['transcription'] for box in page['boxes'])
                        and all(box['alignment_id'] in old_boxes
                                and box['points'] == old_boxes[box['alignment_id']]['points']
                                and box['transcription'] == old_boxes[box['alignment_id']]['transcription']
                                for box in expected_boxes)
                    )
                    if untouched:
                        obsolete = {row['id'] for row in page_pairs}
                        page['export_boxes'] = [box for box in page['export_boxes']
                                                if box.get('alignment_id') not in obsolete]
                        rows = [row for row in rows if row['id'] not in obsolete] + fresh
                        rows_by_page[page['number']] = fresh
                        created += len(fresh) - len(page_pairs)
                        page_pairs = fresh
                        with store.db() as db:
                            db.execute('UPDATE pages SET export_boxes=?,source_text=?,version=version+1 WHERE id=?',
                                       (json.dumps(page['export_boxes'], ensure_ascii=False),
                                        '\n'.join(box['transcription'] for box in page['boxes']), page['id']))
                if not page_pairs:
                    page_pairs = automatic_page_rows(page, pages, book['name'], reference, page_indexes)
                    rows.extend(page_pairs)
                    rows_by_page[page['number']] = page_pairs
                    created += len(page_pairs)
                if not page_pairs or not page['boxes']:
                    continue
                existing = [dict(box) for box in page['export_boxes'] if box.get('box_axis')]
                removed_here = 0
                if page['ocr_granularity'] == 'phrase':
                    valid_ids = {row['id'] for row in page_pairs}
                    kept = [box for box in existing if box.get('alignment_id') in valid_ids]
                    removed_here = len(existing) - len(kept)
                    boxes_removed += removed_here
                    existing = kept
                assigned = {box.get('alignment_id') for box in existing}
                generated = [box for box in boxes_for_rows(page, page_pairs)
                             if box['alignment_id'] not in assigned]
                offset = max((box.get('export_order') or 0 for box in existing), default=0)
                for index, box in enumerate(generated, 1):
                    box['export_order'] = offset + index
                prepared_boxes = sorted(existing + generated,
                                        key=lambda box: box.get('export_order') or float('inf'))
                group_orders = {}
                for box in prepared_boxes:
                    group = box.get('export_group') or box['id']
                    group_orders.setdefault(group, len(group_orders) + 1)
                    order = group_orders[group]
                    if box.get('export_order') != order:
                        boxes_renumbered += 1
                    box['export_order'] = order
                if prepared_boxes == page['export_boxes']:
                    continue
                with store.db() as db:
                    db.execute('UPDATE pages SET export_boxes=?,version=version+1 WHERE id=?',
                               (json.dumps(prepared_boxes, ensure_ascii=False), page['id']))
                boxes_created += len(generated)
            if created:
                rows.sort(key=lambda row: (int(row['sentence_id'].rsplit('.', 2)[1]),
                                           int(row['sentence_id'].rsplit('.', 1)[1])))
                with store.db() as db:
                    db.execute('INSERT INTO alignments VALUES (?,?) ON CONFLICT(book_id) DO UPDATE SET rows=excluded.rows',
                               (book_id, json.dumps(rows, ensure_ascii=False)))
            if created or boxes_created or boxes_removed or boxes_renumbered or deleted or reconciled:
                store.sync_labels(book_id)
        return {'rows': store.describe_alignments(book_id, rows), 'created': created, 'boxes_created': boxes_created,
                'boxes_removed': boxes_removed, 'boxes_renumbered': boxes_renumbered}

    @app.put('/api/books/{book_id}/alignments')
    def save_alignments(book_id: str, data: AlignmentsInput):
        book = require_book(book_id)
        if book['input_revision'] and data.input_revision != book['input_revision']:
            raise HTTPException(409, 'Dữ liệu sách đã được thay bằng bản mới. Tải lại trước khi lưu căn chỉnh.')
        ids = [r.sentence_id for r in data.rows]
        if len(ids) != len(set(ids)) or len({r.id for r in data.rows}) != len(data.rows):
            raise HTTPException(422,'ID câu hoặc ID hàng bị trùng.')
        book_pages=store.pages(book_id)
        valid_images = {p['number'] for p in book_pages
                        if not p['ocr_skip'] and p['category'] not in ('blank','misc') and 'han' in p['ocr_languages']}
        pages_by_id={p['id']:p for p in book_pages}
        for row in data.rows:
            match = re.fullmatch(re.escape(book['name'])+r'\.(\d{3,})\.([1-9]\d*)',row.sentence_id)
            if not match or int(match[1]) not in valid_images:
                raise HTTPException(422,'sentence_id phải trỏ tới trang Hán Nôm có thật: <Tên sách>.<trang ít nhất 3 số>.<câu từ 1>.')
            if row.source_page_id and (row.source_page_id not in pages_by_id or
                    pages_by_id[row.source_page_id]['number']!=int(match[1]) or
                    'han' not in pages_by_id[row.source_page_id]['ocr_languages']):
                raise HTTPException(422,'Trang nguồn không khớp sentence_id.')
            if row.target_page_id and (row.target_page_id not in pages_by_id or
                    'vi' not in pages_by_id[row.target_page_id]['ocr_languages']):
                raise HTTPException(422,'Trang Quốc ngữ không thuộc sách hoặc chưa có nhãn Quốc ngữ.')
        rows = [r.model_dump(exclude_none=True, exclude={'alignment_version'}) for r in data.rows]
        for row in rows:
            for mark in row['marks']:
                if not (0 <= mark['source_start'] < mark['source_end'] <= len(row['source'])
                        and 0 <= mark['target_start'] < mark['target_end'] <= len(row['target'])):
                    raise HTTPException(422, 'Vùng tô màu phải nằm trong cả hai vế của cặp căn chỉnh.')
        with store.lock:
            current = store.book(book_id)
            if current['input_revision'] and current['input_revision'] != data.input_revision:
                raise HTTPException(409, 'Dữ liệu sách đã thay đổi. Tải lại trước khi lưu căn chỉnh.')
            versions = {row.alignment_version for row in data.rows if row.alignment_version is not None}
            expected = data.alignment_version if data.alignment_version is not None else next(iter(versions), None)
            previous = store.alignment_rows(book_id)
            if len(versions) > 1:
                raise HTTPException(409, 'Các cặp không cùng phiên bản lưu.')
            if expected is not None and expected != current['alignment_version']:
                if data.base_rows is None:
                    raise HTTPException(409, 'Các cụm đã thay đổi ở màn hình khác. Tải lại trước khi lưu để tránh ghi đè chữ/màu mới.')
            if data.base_rows is not None:
                normalize = lambda items: [AlignmentInput.model_validate(row).model_dump(exclude_none=True, exclude={'alignment_version'}) for row in items]
                try:
                    rows = merge_rows(normalize(data.base_rows), rows, normalize(previous))
                except ValueError as error:
                    raise HTTPException(409, str(error)) from error
            book_pages = store.pages(book_id)
            pages_by_id = {page['id']: page for page in book_pages}
            previous = attach_refs(previous, book_pages)
            old_rows = {row['id']: row for row in previous}
            supplied_fields = {row.id: row.model_fields_set for row in data.rows}
            if len({row['id'] for row in rows}) != len(rows) or len({row['sentence_id'] for row in rows}) != len(rows):
                raise HTTPException(409, 'Hai phiên đã tạo cặp với cùng ID. Giữ nguyên bản đã lưu để đối chiếu.')
            for row in rows:
                old = old_rows.get(row['id'])
                if old:
                    for side in ('source', 'target'):
                        if (side + '_refs' not in supplied_fields.get(row['id'], set()) and not row.get(side + '_refs') and
                                row.get(side + '_page_id') == old.get(side + '_page_id') and
                                row.get(side + '_line_index') == old.get(side + '_line_index')):
                            row[side + '_refs'] = old.get(side + '_refs', [])
                for side, boxes_key in (('source', 'boxes'), ('target', 'vi_boxes')):
                    refs = row.get(side + '_refs', [])
                    if not refs:
                        continue
                    if (old and refs == old.get(side + '_refs')
                            and row.get(side + '_page_id') == old.get(side + '_page_id')):
                        continue
                    page = pages_by_id.get(row.get(side + '_page_id'))
                    if not page or ref_text(refs, page[boxes_key]) != row[side]:
                        raise HTTPException(422, f"{row['sentence_id']}: liên kết {side} không khớp nội dung và ID box.")
            with store.db() as db:
                db.execute('INSERT INTO alignments VALUES (?,?) ON CONFLICT(book_id) DO UPDATE SET rows=excluded.rows',(book_id,json.dumps(rows,ensure_ascii=False)))
            store.sync_alignment_edits(book_id, previous, rows)
            store.sync_labels(book_id)
            return store.describe_alignments(book_id)

    def download_response(path):
        folder = store.local / 'downloads' / uuid4().hex
        folder.mkdir(parents=True)
        snapshot = folder / path.name
        shutil.copyfile(path, snapshot)
        def cleanup():
            if not folder.resolve().is_relative_to((store.local / 'downloads').resolve()):
                raise ValueError('Đường dẫn tải xuống không thuộc workspace.')
            snapshot.unlink(missing_ok=True)
            folder.rmdir()
        return FileResponse(snapshot, filename=path.name, background=BackgroundTask(cleanup))

    @app.get('/api/books/{book_id}/export')
    def export(book_id: str, format: Literal['csv','xlsx','labels']='csv'):
        with store.lock:
            return download_response(build_export(book_id, format))

    def build_export(book_id, format, *, complete_only=False, reviewed_only=False):
        book = require_book(book_id)
        folder = store.data / 'output_alignment' / book_id
        folder.mkdir(exist_ok=True)
        if format == 'labels':
            store.sync_labels(book_id)
            pages=store.pages(book_id)
            if reviewed_only:
                selected = [row for row in get_alignments(book_id) if row.get('reviewed')
                            and not row.get('duplicate_of') and row['review_state'] != 'excluded'
                            and all(export_text(row[side], side)[0].strip() for side in ('source', 'target'))]
                try:
                    pages = select_label_pages(pages, selected)
                except ValueError as error:
                    raise HTTPException(422, str(error)) from error
            if book['input_revision'] and not complete_only:
                assigned = {box.get('alignment_id') for page in pages for box in page['export_boxes']}
                missing = [row for row in get_alignments(book_id) if not row.get('duplicate_of')
                           and row['source'].strip() and row['target'].strip() and row['id'] not in assigned]
                if missing:
                    raise HTTPException(400, 'Còn cụm chưa có box nhãn thật. Vẽ/gán box cho các cụm đã tách hoặc thêm trước khi xuất ZIP nhãn.')
            path = folder / f"{book['name']}_{format}.zip"
            temporary = path.with_suffix('.zip.tmp')
            with zipfile.ZipFile(temporary,'w',zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                archive.write(raw_folder / book['filename'], f"{book['name']}/{book['filename']}")
                for category in CATEGORIES:
                    if category == 'both' or (category == 'vi' and not any(page['vi_boxes'] for page in pages)):
                        continue
                    archive.writestr(f"{book['name']}/{category}/", b'')
                    if category not in ('blank','misc','both'):
                        for name in ('Label.txt','fileState.txt'):
                            destination = f"{book['name']}/{category}/{name}"
                            if reviewed_only:
                                entries = []
                                for page in pages:
                                    if category not in label_groups(page) or (category == 'vi' and not page['vi_boxes']):
                                        continue
                                    image_name = f"{category}/{book['name']}.{page['number']:03d}.jpg"
                                    if name == 'fileState.txt':
                                        entries.append(image_name + '\t' + str(int(page.get('export_complete', False))))
                                    else:
                                        side = 'target' if category == 'vi' else 'source'
                                        boxes = [{'transcription': export_text(box['transcription'], side)[0], 'points': box['points']}
                                                 for box in label_boxes(page, category) if export_text(box['transcription'], side)[0].strip()]
                                        entries.append(image_name + '\t' + json.dumps(boxes, ensure_ascii=False))
                                archive.writestr(destination, '\n'.join(entries) + ('\n' if entries else ''))
                            else:
                                archive.write(store.book_dir(book_id)/category/name, destination)
                for page in pages:
                    original=rendered_image(page)
                    image_name=f"{book['name']}.{page['number']:03d}.jpg"
                    for category in label_groups(page):
                        if category == 'vi' and not page['vi_boxes']:
                            continue
                        archive.write(original,f"{book['name']}/{category}/{image_name}")
            os.replace(temporary,path)
        else:
            rows = [row for row in get_alignments(book_id) if not row.get('duplicate_of') and row['review_state'] != 'excluded']
            if reviewed_only:
                rows = [row for row in rows if row.get('reviewed')]
            if complete_only:
                rows = [row for row in rows if row['source'].strip() and row['target'].strip()]
            if not rows:
                raise HTTPException(400,'Chưa có cặp căn chỉnh. Hãy tạo và lưu các cặp trước khi xuất.')
            if any(not row['source'].strip() or not row['target'].strip() for row in rows):
                raise HTTPException(400,'Còn cặp căn chỉnh thiếu một vế. Hãy sửa hoặc gộp cặp trước khi xuất.')
            prepared = prepared_rows(rows)
            if not prepared:
                raise HTTPException(400, 'Chưa có cặp đủ hai vế sau khi làm sạch để xuất.')
            if not complete_only and len(prepared) != len(rows):
                raise HTTPException(400, 'Có cặp không còn nội dung sau khi làm sạch. Kiểm tra trước khi xuất.')
            path = folder / f"{book['name']}.{format}"
            if not reviewed_only:
                folder = folder / 'working'
                folder.mkdir(exist_ok=True)
                path = folder / path.name
            write_alignment(path, prepared)
        return path

    @app.get('/api/results/archive')
    def all_results_archive():
        """Package immutable book snapshots; compression does not hold the editor lock."""
        candidates = [book for book in store.books() if not store.book(book['id'])['demo']]
        if not candidates:
            raise HTTPException(404, 'Chưa có sách để tải kết quả.')
        output = store.data / 'output_alignment'
        staging = store.local / 'downloads' / uuid4().hex
        staging.mkdir(parents=True)
        try:
            books = []
            with store.lock:
                for book in candidates:
                    book_id = book['id']
                    rows = get_alignments(book_id)
                    if not prepared_rows(rows, reviewed_only=True):
                        continue
                    build_export(book_id, 'labels', complete_only=True, reviewed_only=True)
                    books.append(book)
                    destination = staging / book_id
                    destination.mkdir()
                    for name in (f"{book['name']}.csv", f"{book['name']}.xlsx", f"{book['name']}_labels.zip"):
                        source = output / book_id / name
                        try:
                            os.link(source, destination / name)
                        except OSError:
                            shutil.copyfile(source, destination / name)
            if not books:
                raise HTTPException(404, 'Chưa có cặp đã xác nhận và đủ hai vế để tải.')
            path = staging / 'tat-ca-ket-qua.zip'
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
                for book in books:
                    folder = staging / book['id']
                    with zipfile.ZipFile(folder / f"{book['name']}_labels.zip") as labels:
                        for info in labels.infolist():
                            if info.is_dir():
                                archive.writestr(info.filename, b'')
                            else:
                                with labels.open(info) as source, archive.open(info.filename, 'w') as target:
                                    shutil.copyfileobj(source, target)
                    for extension in ('csv', 'xlsx'):
                        result = folder / f"{book['name']}.{extension}"
                        archive.write(result, f"{book['name']}/{result.name}")
            # The download owns a separate snapshot even if another editor saves now.
            return download_response(path)
        finally:
            if staging.resolve().is_relative_to((store.local / 'downloads').resolve()):
                shutil.rmtree(staging)

    @app.get('/api/books/{book_id}/results/{filename}')
    def result_file(book_id: str,filename: Literal['summary.json','pages.json','alignments.json','pairs.csv']):
        with store.lock:
            require_book(book_id)
            store.sync_results(book_id)
            path=store.data/'output_alignment'/book_id/filename
            if not path.is_file():
                raise HTTPException(404,'Chưa có tệp kết quả để tải.')
            return download_response(path)

    @app.get('/', include_in_schema=False)
    def frontend_source():
        return RedirectResponse('http://127.0.0.1:5173')
    return app
