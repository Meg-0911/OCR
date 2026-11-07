import { useState } from 'react';
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
  const [splitting, setSplitting] = useState(false);
  const [cut, setCut] = useState<{ side: 'source' | 'target'; position: number } | null>(null);
  function split() {
    const value = cut?.side === 'source' ? row.source : row.target;
    if (!cut || cut.position <= 0 || cut.position >= value.length) {
      setSplitting(true);
      return;
    }
    onSplit(
      cut.side === 'source' ? [row.source.slice(0, cut.position), row.source.slice(cut.position)] : [row.source, ''],
      cut.side === 'target' ? [row.target.slice(0, cut.position), row.target.slice(cut.position)] : [row.target, ''],
    );
    setSplitting(false);
    setCut(null);
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
          className="han-text"
          aria-label={`Hán Nôm cặp ${index + 1}`}
          value={row.source}
          onChange={(event) => onChange({ ...row, source: event.target.value, reviewed: false })}
          onSelect={(event) => setCut({ side: 'source', position: event.currentTarget.selectionStart })}
          placeholder="Văn bản Hán Nôm…"
        />
        <small className="unverified">Chưa kiểm chứng ngữ nghĩa</small>
      </div>
      <div>
        <textarea
          aria-label={`Quốc ngữ cặp ${index + 1}`}
          value={row.target}
          onChange={(event) => onChange({ ...row, target: event.target.value, reviewed: false })}
          onSelect={(event) => setCut({ side: 'target', position: event.currentTarget.selectionStart })}
          placeholder="Văn bản Quốc ngữ…"
        />
        {splitting && (
          <small className="split-hint">Đặt con trỏ giữa chữ trong một ô, rồi bấm Tách. Ô còn lại sẽ ở cặp đầu.</small>
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
          title="Tách tại con trỏ trong một ô"
          aria-label={`Tách cặp ${index + 1}`}
          disabled={row.source.length < 2 && row.target.length < 2}
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
