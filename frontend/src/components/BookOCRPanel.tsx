import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, Pause, Play } from 'lucide-react';
import { api } from '../api';
import type { OCRJob, OCRSettings } from '../types';

type OCRAction = 'start' | 'pause' | 'resume';
type ControllerProps = {
  bookId: string;
  job: OCRJob | null;
  onJob: (job: OCRJob | null) => void;
  onRefresh: () => void;
  onError: (error: unknown) => void;
  beforeStart: () => Promise<void>;
  settings: OCRSettings;
};
export function useBookOCR(props: ControllerProps) {
  const [acting, setActing] = useState(false);
  const inFlight = useRef(false);
  const latest = useRef(props);
  latest.current = props;
  useEffect(() => {
    let cancelled = false;
    let timer: ReturnType<typeof setTimeout>;
    let lastProgress = '';
    let lastPageRefresh = 0;
    async function poll() {
      try {
        const next = await api.ocrJob(props.bookId);
        if (cancelled) return;
        const progress = JSON.stringify(next);
        const progressChanged = progress !== lastProgress;
        if (progressChanged) latest.current.onJob(next);
        // Checkpoints can update page text without changing the job progress.
        const checkpointRefreshDue =
          next?.status === 'running' && Date.now() - lastPageRefresh >= 5000;
        if (next && (progressChanged || checkpointRefreshDue)) {
          latest.current.onRefresh();
          lastPageRefresh = Date.now();
        }
        lastProgress = progress;
      } catch {
        /* retry */
      }
      if (!cancelled) timer = setTimeout(() => void poll(), 1800);
    }
    void poll();
    return () => {
      cancelled = true;
      clearTimeout(timer);
    };
  }, [props.bookId]);
  async function act(action: OCRAction) {
    if (inFlight.current) return;
    inFlight.current = true;
    setActing(true);
    try {
      if (action !== 'pause') await props.beforeStart();
      const next =
        action === 'start'
          ? await api.startWorkflow(props.bookId, props.settings, [])
          : await api.controlOCRJob(props.job!.id, action);
      props.onJob(next);
      props.onRefresh();
    } catch (error) {
      props.onError(error);
    } finally {
      inFlight.current = false;
      setActing(false);
    }
  }
  return { acting, act };
}

export default function BookOCRPanel(props: {
  job: OCRJob | null;
  disabled: boolean;
  showStart: boolean;
  showResume: boolean;
  acting: boolean;
  onAction: (action: OCRAction) => Promise<void>;
}) {
  const { acting, onAction: act } = props;
  const job = props.job;
  const running = job && ['running', 'pausing'].includes(job.status);
  return (
    <div className="workbench-ocr-controls">
      {job && (
        <span role="status">
          {job.status === 'completed'
            ? 'OCR đã xử lý'
            : job.status === 'paused'
              ? 'OCR tạm dừng'
              : job.status === 'pausing'
                ? 'Đang dừng OCR'
                : job.status === 'failed'
                  ? 'OCR gặp lỗi'
                  : 'Đang OCR'}{' '}
          {job.completed}/{job.total}
        </span>
      )}
      {job && <progress aria-label="Tiến trình OCR" value={job.completed} max={job.total || 1} />}
      {job?.error && (
        <span className="workbench-error" role="alert">
          {job.error}
        </span>
      )}
      {running ? (
        <button
          className="secondary-button"
          disabled={acting || job.status === 'pausing'}
          onClick={() => void act('pause')}
        >
          <Pause size={14} />
          Tạm dừng
        </button>
      ) : props.showStart ||
        (props.showResume && job && ['paused', 'failed'].includes(job.status)) ? (
        <button
          className="primary-button"
          disabled={acting || props.disabled}
          onClick={() =>
            void act(job && ['paused', 'failed'].includes(job.status) ? 'resume' : 'start')
          }
        >
          {acting ? <LoaderCircle size={14} className="spin" /> : <Play size={14} />}
          {job && ['paused', 'failed'].includes(job.status) ? 'Tiếp tục OCR' : 'OCR toàn sách'}
        </button>
      ) : null}
    </div>
  );
}
