"""A single local OCR worker with durable per-page checkpoints."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from uuid import uuid4
from .ocr import OCRPaused


class OCRJobs:
    def __init__(self, store, recognize, needs_ocr=None):
        self.store, self.recognize = store, recognize
        self.needs_ocr=needs_ocr or (lambda page,settings:page['status']!='done' and not page['boxes'] and store.latest_ocr(page['id']) is None)
        self.lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix='book-ocr')
        self.stopping = threading.Event()
        self.futures = {}
        with store.db() as db:
            # A process restart never resubmits external calls on its own.
            db.execute("UPDATE ocr_jobs SET status='paused' WHERE status IN ('running','pausing')")
            db.execute("UPDATE ocr_job_pages SET status='pending' WHERE status='running'")

    def get(self, job_id):
        with self.store.db() as db:
            row = db.execute('SELECT * FROM ocr_jobs WHERE id=?', (job_id,)).fetchone()
            if not row:
                return None
            pages = [dict(p) for p in db.execute('''SELECT j.page_id,j.status,j.error,p.number FROM ocr_job_pages j
                JOIN pages p ON p.id=j.page_id WHERE job_id=? ORDER BY p.number,p.category''', (job_id,))]
        result = dict(row)
        result['settings'] = json.loads(result['settings'])
        result['pages'] = pages
        result['total'] = len(pages)
        result['completed'] = sum(p['status'] in ('succeeded','skipped') for p in pages)
        return result

    def latest(self, book_id):
        with self.store.db() as db:
            row = db.execute('SELECT id FROM ocr_jobs WHERE book_id=? ORDER BY created_at DESC,rowid DESC LIMIT 1', (book_id,)).fetchone()
        return self.get(row['id']) if row else None

    def start(self, book_id, settings, start_page, end_page, include_unclassified=False):
        with self.lock:
            with self.store.db() as db:
                if db.execute("SELECT 1 FROM ocr_jobs WHERE status IN ('running','pausing')").fetchone():
                    raise ValueError('Đang chạy một quyển khác. Tạm dừng hoặc đợi quyển đó xong trước.')
            pages = [p for p in self.store.pages(book_id) if start_page <= p['number'] <= end_page
                     and p['status']!='done'
                     and not p.get('ocr_skip',False)
                     and (p['category'] in (('ch','both','intro','ref','toc') if settings.get('mode','han')=='han' else ('ch','vi','both','intro','ref','toc')) or (include_unclassified and p['category']=='misc'))]
            if not pages:
                raise ValueError('Không có trang cần OCR trong phạm vi.')
            job_id = uuid4().hex
            with self.store.db() as db:
                db.execute('INSERT INTO ocr_jobs VALUES (?,?,?,?,?,?)', (job_id,book_id,'running',json.dumps(settings),None,datetime.now(timezone.utc).isoformat()))
                for page in pages:
                    skip = not self.needs_ocr(page,settings)
                    db.execute('INSERT INTO ocr_job_pages VALUES (?,?,?,NULL)', (job_id,page['id'],'skipped' if skip else 'pending'))
            self.store.sync_labels(book_id)
            initial = self.get(job_id)
            self.futures[job_id] = self.executor.submit(self._run, job_id)
            return initial

    def pause(self, job_id):
        with self.store.db() as db:
            db.execute("UPDATE ocr_jobs SET status='pausing' WHERE id=? AND status='running'", (job_id,))
        return self.get(job_id)

    def resume(self, job_id):
        with self.lock:
            job = self.get(job_id)
            if not job or job['status'] not in ('paused','failed'):
                raise ValueError('Chỉ tiếp tục tác vụ đã dừng hoặc bị lỗi.')
            if job_id in self.futures and not self.futures[job_id].done():
                raise ValueError('Tác vụ đang kết thúc lượt hiện tại. Hãy đợi rồi tiếp tục.')
            with self.store.db() as db:
                if db.execute("SELECT 1 FROM ocr_jobs WHERE status IN ('running','pausing')").fetchone():
                    raise ValueError('Đang chạy một quyển khác.')
                db.execute("UPDATE ocr_job_pages SET status='pending',error=NULL WHERE job_id=? AND status IN ('failed','running')", (job_id,))
                for item in job['pages']:
                    page=self.store.page(item['page_id'])
                    if page['status']!='done' and self.needs_ocr(page,job['settings']):
                        db.execute("UPDATE ocr_job_pages SET status='pending',error=NULL WHERE job_id=? AND page_id=?",(job_id,page['id']))
                db.execute("UPDATE ocr_jobs SET status='running',error=NULL WHERE id=?", (job_id,))
            initial = self.get(job_id)
            self.futures[job_id] = self.executor.submit(self._run, job_id)
            return initial

    def _run(self, job_id):
        try:
            job = self.get(job_id)
            for item in job['pages']:
                if self.stopping.is_set() or self.get(job_id)['status'] != 'running':
                    self._status(job_id, 'paused')
                    return
                if item['status'] != 'pending':
                    continue
                page = self.store.page(item['page_id'])
                if not self.needs_ocr(page,job['settings']) or page['category']=='blank' or page.get('ocr_skip',False):
                    self._page_status(job_id, page['id'], 'skipped')
                    continue
                self._page_status(job_id, page['id'], 'running')
                try:
                    self.recognize(page['id'], {'version':page['version'], **job['settings']})
                except OCRPaused:
                    self._page_status(job_id, page['id'], 'pending')
                    self._status(job_id, 'paused')
                    return
                except Exception as error:
                    # Only controlled public messages may be persisted, never request headers.
                    message = getattr(error, 'detail', None) or 'Không hoàn tất OCR trang này. Kiểm tra kết nối/cấu hình rồi tiếp tục.'
                    self._page_status(job_id, page['id'], 'failed', str(message))
                    self._status(job_id, 'failed', str(message))
                    return
                self._page_status(job_id, page['id'], 'succeeded')
            self._status(job_id, 'completed')
        except Exception:
            self._status(job_id, 'failed', 'Lỗi tác vụ cục bộ. Các kết quả đã lưu vẫn được giữ; khởi động lại rồi tiếp tục.')

    def _status(self, job_id, status, error=None):
        with self.store.db() as db:
            db.execute('UPDATE ocr_jobs SET status=?,error=? WHERE id=?', (status,error,job_id))
        self.store.sync_results(self.get(job_id)['book_id'],'ocr_'+status)

    def _page_status(self, job_id, page_id, status, error=None):
        with self.store.db() as db:
            db.execute('UPDATE ocr_job_pages SET status=?,error=? WHERE job_id=? AND page_id=?', (status,error,job_id,page_id))
        self.store.sync_results(self.get(job_id)['book_id'])

    def close(self):
        self.stopping.set()
        self.executor.shutdown(wait=True, cancel_futures=True)
