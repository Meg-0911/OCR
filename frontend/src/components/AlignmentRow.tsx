import { useRef, useState } from 'react';
import { CheckCheck, Link2, SplitSquareVertical, Trash2 } from 'lucide-react';
import type { Alignment } from '../types';

export default function AlignmentRow({
  row,
  index,
  total,
  onChange,
  onRemove,
  onMerge,
  onSplit,
}: {
  row: Alignment;
  index: number;
  total: number;
  onChange: (row: Alignment) => void;
  onRemove: () => void;
  onMerge: () => void;
  onSplit: (source: [string, string], target: [string, string]) => void;
}) {
  const source = useRef<HTMLTextAreaElement>(null),
    target = useRef<HTMLTextAreaElement>(null);
  const [splitting, setSplitting] = useState(false);
  function split() {
    const a = source.current?.selectionStart || 0,
      b = target.current?.selectionStart || 0;
    if (a <= 0 || a >= row.source.length || b <= 0 || b >= row.target.length) {
      setSplitting(true);
      return;
    }
    onSplit(
      [row.source.slice(0, a), row.source.slice(a)],
      [row.target.slice(0, b), row.target.slice(b)],
    );
    setSplitting(false);
  }
  return (
    <div className={`alignment-row ${row.reviewed ? 'reviewed' : ''}`}>
      <div className="sentence-id">
        <small>CẶP {String(index + 1).padStart(2, '0')}</small>
        <span>{row.sentence_id}</span>
        <button onClick={() => onChange({ ...row, reviewed: !row.reviewed })}>
          {row.reviewed ? <CheckCheck size={13} /> : <span className="status-dot pending" />}
          {row.reviewed ? 'Đã đọc lại' : 'Chờ đọc lại'}
        </button>
      </div>
      <div>
        <textarea
          ref={source}
          className="han-text"
          aria-label={`Hán Nôm cặp ${index + 1}`}
          value={row.source}
          onChange={(event) => onChange({ ...row, source: event.target.value, reviewed: false })}
          placeholder="Văn bản Hán Nôm…"
        />
        <small className="unverified">Chưa đối chiếu từ điển</small>
      </div>
      <div>
        <textarea
          ref={target}
          aria-label={`Quốc ngữ cặp ${index + 1}`}
          value={row.target}
          onChange={(event) => onChange({ ...row, target: event.target.value, reviewed: false })}
          placeholder="Văn bản Quốc ngữ…"
        />
        {splitting && (
          <small className="split-hint">
            Đặt con trỏ ở điểm tách trong mỗi ô rồi bấm tách lại.
          </small>
        )}
      </div>
      <div className="alignment-tools">
        <button
          className="icon-button"
          title="Gộp với cặp tiếp theo"
          aria-label={`Gộp cặp ${index + 1} với cặp tiếp theo`}
          disabled={index === total - 1}
          onClick={onMerge}
        >
          <Link2 size={16} />
        </button>
        <button
          className="icon-button"
          title="Tách tại con trỏ trong hai ô"
          aria-label={`Tách cặp ${index + 1}`}
          onClick={split}
        >
          <SplitSquareVertical size={16} />
        </button>
        <button
          className="icon-button"
          title="Xóa cặp"
          aria-label={`Xóa cặp ${index + 1}`}
          onClick={onRemove}
        >
          <Trash2 size={15} />
        </button>
      </div>
    </div>
  );
}
