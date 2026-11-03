import { useEffect, useRef, useState } from 'react';
import { api } from '../api';
import type { Category, OCRJob, OCRSettings, Page, PagePlan } from '../types';

const labels: Record<OCRJob['status'], string> = {
  running: 'Đang OCR toàn bộ sách',
  pausing: 'Đang chờ trang hiện tại xong',
  paused: 'Đã tạm dừng',
  failed: 'Cần xử lý lỗi để tiếp tục',
  completed: 'Đã OCR xong các trang được chọn',
};
const categories: Record<Category, string> = {
  ch: 'Nội dung Hán Nôm',
  vi: 'Quốc ngữ',
  intro: 'Giới thiệu',
  ref: 'Chú thích',
  toc: 'Mục lục',
  blank: 'Trang trắng',
  misc: 'Chưa phân loại',
};
type Props = {
  bookId: string;
  pages: Page[];
  ready: boolean;
  viReady: boolean;
  referenceFile?: string | null;
  viEngine?: string;
  disabled: boolean;
  onRefresh: () => void;
  onError: (error: unknown) => void;
  beforeStart: () => Promise<void>;
  onOpenPage: (id: string) => void;
  onJob: (job: OCRJob | null) => void;
};

export default function BookOCRPanel(props: Props) {
  const [job, setJob] = useState<OCRJob | null>(null);
  const [acting, setActing] = useState(false);
  const [search, setSearch] = useState('');
  const [saveState, setSaveState] = useState(
    'Nhãn được lưu tự động; bấm nút bên dưới để bắt đầu OCR cả sách.',
  );
  const key = `nom-plan-${props.bookId}`;
  const [changes, setChanges] = useState<Record<string, PagePlan>>(() => {
    try {
      return JSON.parse(localStorage.getItem(key) || '{}');
    } catch {
      return {};
    }
  });
  const [settings, setSettings] = useState<OCRSettings>({
    ocr_id: 4,
    lang_type: 2,
    reading_direction: 2,
    epitaph: 0,
    tag: null,
    mode: 'bilingual',
  });
  const latest = useRef(props);
  latest.current = props;
  const changesRef = useRef(changes);
  changesRef.current = changes;
  const planSaves = useRef<Promise<unknown>>(Promise.resolve());
  const settingsKey = `nom-ocr-settings-${props.bookId}`;
  useEffect(() => {
    try {
      const saved = localStorage.getItem(settingsKey);
      if (saved) setSettings(JSON.parse(saved));
    } catch {
      /* defaults */
    }
  }, [settingsKey]);
  useEffect(() => {
    try {
      localStorage.setItem(settingsKey, JSON.stringify(settings));
    } catch {
      /* form remains available */
    }
  }, [settings, settingsKey]);
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    async function poll() {
      try {
        const next = await api.ocrJob(props.bookId);
        if (cancelled) return;
        setJob(next);
        latest.current.onJob(next);
        if (next) latest.current.onRefresh();
      } catch {
        /* persistent results remain; retry on next poll */
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 1500);
    }
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [props.bookId]);
  async function persistPlan(snapshot = changesRef.current) {
    if (!Object.keys(snapshot).length) return;
    setSaveState('Đang lưu nhãn…');
    const task = planSaves.current
      .catch(() => {})
      .then(() => api.savePlan(props.bookId, Object.values(snapshot)));
    planSaves.current = task;
    await task;
    setChanges((current) => (current === snapshot ? {} : current));
    setSaveState('Đã lưu nhãn vào máy.');
    latest.current.onRefresh();
  }
  useEffect(() => {
    try {
      localStorage.setItem(key, JSON.stringify(changes));
    } catch {
      props.onError(
        new Error('Không lưu được nhãn nháp trên trình duyệt. Hãy bấm Lưu nhãn & OCR.'),
      );
    }
    if (!Object.keys(changes).length) return;
    const timer = setTimeout(() => void persistPlan(changes).catch(props.onError), 800);
    return () => clearTimeout(timer);
  }, [changes, key]);
  function planFor(page: Page): PagePlan {
    return (
      changes[page.id] || { page_id: page.id, category: page.category, ocr_skip: page.ocr_skip }
    );
  }
  function update(page: Page, patch: Partial<PagePlan>) {
    setChanges((old) => ({ ...old, [page.id]: { ...planFor(page), ...patch } }));
  }
  async function act(action: 'start' | 'pause' | 'resume') {
    setActing(true);
    try {
      const pending = changesRef.current;
      await latest.current.beforeStart();
      await persistPlan(pending);
      const fresh = action === 'start' ? await api.pages(props.bookId) : [];
      const result =
        action === 'start'
          ? await api.startWorkflow(
              props.bookId,
              settings,
              fresh.map(
                (page) =>
                  changesRef.current[page.id] ||
                  pending[page.id] || {
                    page_id: page.id,
                    category: page.category,
                    ocr_skip: page.ocr_skip,
                  },
              ),
            )
          : await api.controlOCRJob(job!.id, action);
      setJob(result);
      props.onJob(result);
      props.onRefresh();
    } catch (error) {
      props.onError(error);
    } finally {
      setActing(false);
    }
  }
  const running = !!job && ['running', 'pausing'].includes(job.status);
  const selected = props.pages.filter((page) => {
    const plan = planFor(page);
    return !plan.ocr_skip && plan.category !== 'blank';
  }).length;
  return (
    <section className="book-ocr-panel book-workflow" aria-label="Gắn nhãn và OCR toàn bộ sách">
      <h3>1. Gắn nhãn trang → 2. Lưu và OCR toàn bộ sách → 3. Hiệu đính kết quả đang về</h3>
      <p>
        Chọn bỏ qua trang đặc biệt. Kết quả hai ngôn ngữ hiện dần theo từng phần đã xong để bạn sửa
        ngay, không cần chờ cả sách. Quốc ngữ{' '}
        {props.referenceFile
          ? `lấy trực tiếp từ ${props.referenceFile}, ghép nháp theo số dòng Nôm`
          : `dùng ${props.viEngine || 'VietOCR CPU'} tại máy`}
        .
      </p>
      <details className="book-page-plan" open>
        <summary>
          Danh sách gắn nhãn · {selected}/{props.pages.length} trang sẽ OCR
        </summary>
        <div className="button-group">
          <input
            aria-label="Tìm trang để gắn nhãn"
            placeholder="Số trang…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
          <button
            className="secondary-button"
            disabled={acting}
            onClick={() =>
              setChanges((old) => ({
                ...old,
                ...Object.fromEntries(
                  props.pages
                    .filter((p) => planFor(p).category === 'misc')
                    .map((p) => [p.id, { ...planFor(p), category: 'ch' }]),
                ),
              }))
            }
          >
            Gắn trang chưa phân loại là nội dung
          </button>
        </div>
        <div className="book-plan-table">
          <table>
            <thead>
              <tr>
                <th>Trang / ảnh đối chiếu</th>
                <th>Nhãn</th>
                <th>Thực hiện OCR</th>
              </tr>
            </thead>
            <tbody>
              {props.pages
                .filter((p) => !search || String(p.number).includes(search))
                .map((page) => {
                  const plan = planFor(page);
                  return (
                    <tr key={page.id}>
                      <td>
                        <button
                          className="plan-page-link"
                          onClick={() => props.onOpenPage(page.id)}
                        >
                          <img loading="lazy" src={`${page.image_url}?thumbnail=true`} alt="" />
                          Trang {page.number}
                        </button>
                      </td>
                      <td>
                        <select
                          aria-label={`Nhãn trang ${page.number}`}
                          value={plan.category}
                          onChange={(e) => update(page, { category: e.target.value as Category })}
                        >
                          {Object.entries(categories).map(([value, label]) => (
                            <option key={value} value={value}>
                              {label}
                            </option>
                          ))}
                        </select>
                      </td>
                      <td>
                        <label>
                          <input
                            type="checkbox"
                            aria-label={`OCR trang ${page.number}`}
                            checked={!plan.ocr_skip && plan.category !== 'blank'}
                            disabled={plan.category === 'blank'}
                            onChange={(e) => update(page, { ocr_skip: !e.target.checked })}
                          />
                          {plan.ocr_skip || plan.category === 'blank' ? 'Bỏ qua' : 'Chạy OCR'}
                        </label>
                      </td>
                    </tr>
                  );
                })}
            </tbody>
          </table>
        </div>
        <small role="status">{saveState}</small>
      </details>
      <details>
        <summary>Cấu hình OCR Nôm cho sách</summary>
        <div className="book-ocr-settings">
          <label>
            Kiểu văn bản
            <select
              disabled={running}
              value={settings.ocr_id}
              onChange={(e) =>
                setSettings({
                  ...settings,
                  ocr_id: Number(e.target.value) as OCRSettings['ocr_id'],
                })
              }
            >
              <option value={1}>Thông thường dọc</option>
              <option value={2}>Hành chính</option>
              <option value={3}>Ngoại cảnh</option>
              <option value={4}>Thông thường ngang</option>
            </select>
          </label>
          <label>
            Chiều đọc
            <select
              disabled={running}
              value={settings.reading_direction}
              onChange={(e) =>
                setSettings({ ...settings, reading_direction: Number(e.target.value) as 1 | 2 })
              }
            >
              <option value={1}>Dọc</option>
              <option value={2}>Ngang</option>
            </select>
          </label>
          <label>
            Loại chữ
            <select
              disabled={running}
              value={settings.lang_type}
              onChange={(e) =>
                setSettings({ ...settings, lang_type: Number(e.target.value) as 0 | 1 | 2 })
              }
            >
              <option value={0}>Chưa biết</option>
              <option value={1}>Hán</option>
              <option value={2}>Nôm</option>
            </select>
          </label>
        </div>
      </details>
      <div className="button-group">
        {!running && (
          <button
            className="primary-button"
            disabled={
              acting ||
              props.disabled ||
              !props.ready ||
              (!props.viReady && !props.referenceFile) ||
              !selected
            }
            onClick={() => void act('start')}
          >
            Lưu nhãn & OCR toàn bộ sách ({selected} trang)
          </button>
        )}
        {job?.status === 'running' && (
          <button className="secondary-button" disabled={acting} onClick={() => void act('pause')}>
            Lưu và tạm dừng sau trang hiện tại
          </button>
        )}
        {job && ['paused', 'failed'].includes(job.status) && (
          <button
            className="primary-button"
            disabled={acting || props.disabled}
            onClick={() => void act('resume')}
          >
            Tiếp tục đúng phần chưa xong
          </button>
        )}
      </div>
      {!props.ready && (
        <p>
          Thêm KHN_token vào backend/.env để OCR Nôm, rồi khởi động lại backend. Nhãn vẫn lưu được.
        </p>
      )}
      {job && (
        <div className="book-ocr-status" role="status">
          <strong>
            {labels[job.status]} · {job.completed}/{job.total} trang
          </strong>
          <progress value={job.completed} max={job.total || 1} />
          {job.error && <p role="alert">{job.error}</p>}
          <small>
            Bạn có thể mở trang đã có kết quả bên dưới và hiệu đính trong khi các trang tiếp theo
            đang chạy.
          </small>
        </div>
      )}
    </section>
  );
}
