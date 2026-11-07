import { useState } from 'react';
import { CheckCheck, Link2, SplitSquareVertical, Trash2 } from 'lucide-react';
import type { Alignment, ReviewKind, ReviewMark } from '../types';

function exportPreview(value: string, side: 'source' | 'target') {
  const text = value.normalize('NFC');
  return side === 'source'
    ? text.replace(/\p{P}|\s/gu, '')
    : text.toLocaleLowerCase('vi').replace(/\p{P}/gu, '');
}

function colorsFor(value: string, base: (ReviewKind | undefined)[], marks: ReviewMark[], side: 'source' | 'target') {
  const characters = Array.from(value);
  const kinds = characters.map((_, index) => base[index] || 'match');
  for (const mark of marks) {
    const start = Array.from(value.slice(0, mark[`${side}_start`])).length;
    const end = Array.from(value.slice(0, mark[`${side}_end`])).length;
    kinds.fill(mark.kind, start, end);
  }
  return { characters, kinds };
}

function selectionOffset(element: HTMLElement) {
  const selection = window.getSelection();
  if (!selection?.rangeCount || !element.contains(selection.anchorNode)) return 0;
  const range = selection.getRangeAt(0).cloneRange();
  range.selectNodeContents(element);
  range.setEnd(selection.anchorNode!, selection.anchorOffset);
  return range.toString().length;
}

export default function AlignmentRow({
  row,
  index,
  total,
  onChange,
  onRemove,
  onMerge,
  onSplit,
  compact = false,
  sourceColors = [],
  targetColors = [],
}: {
  row: Alignment;
  index: number;
  total: number;
  onChange: (row: Alignment) => void;
  onRemove?: () => void;
  onMerge?: () => void;
  onSplit?: (source: [string, string], target: [string, string]) => void;
  compact?: boolean;
  sourceColors?: (ReviewKind | undefined)[];
  targetColors?: (ReviewKind | undefined)[];
}) {
  const [splitting, setSplitting] = useState(false);
  const [cut, setCut] = useState<{ side: 'source' | 'target'; position: number } | null>(null);
  const marks = row.marks || [];
  const sourceDisplay = colorsFor(row.source, sourceColors, marks, 'source');
  const targetDisplay = colorsFor(row.target, targetColors, marks, 'target');
  function editor(
    side: 'source' | 'target',
    value: string,
    display: ReturnType<typeof colorsFor>,
    className = '',
  ) {
    return (
      <div
        className={`alignment-editor ${className}`}
        role="textbox"
        aria-label={`${side === 'source' ? 'Hán Nôm' : 'Quốc ngữ'} cặp ${index + 1}`}
        aria-multiline="true"
        contentEditable={!compact}
        suppressContentEditableWarning
        onInput={(event) => {
          const next = event.currentTarget.innerText.replace(/\r\n/g, '\n').replace(/\n$/, '');
          if (next !== value)
            onChange({
              ...row,
              [side]: next,
              reviewed: false,
              marks: [],
            });
        }}
        onKeyUp={(event) =>
          setCut({ side, position: selectionOffset(event.currentTarget) })
        }
        onMouseUp={(event) =>
          setCut({ side, position: selectionOffset(event.currentTarget) })
        }
      >
        {display.characters.map((character, charIndex) => (
          <span key={charIndex} className={`review-${display.kinds[charIndex]}`}>
            {character}
          </span>
        ))}
      </div>
    );
  }
  function split() {
    const value = cut?.side === 'source' ? row.source : row.target;
    if (!cut || cut.position <= 0 || cut.position >= value.length) {
      setSplitting(true);
      return;
    }
    onSplit?.(
      cut.side === 'source' ? [row.source.slice(0, cut.position), row.source.slice(cut.position)] : [row.source, ''],
      cut.side === 'target' ? [row.target.slice(0, cut.position), row.target.slice(cut.position)] : [row.target, ''],
    );
    setSplitting(false);
    setCut(null);
  }
  return (
    <div className={`alignment-row ${row.reviewed ? 'reviewed' : ''} ${compact ? 'compact' : ''}`}>
      <div className="sentence-id">
        <small>CẶP {String(index + 1).padStart(2, '0')}</small>
        <span>{row.sentence_id}</span>
        <button onClick={() => onChange({ ...row, reviewed: !row.reviewed })}>
          {row.reviewed ? <CheckCheck size={13} /> : <span className="status-dot pending" />}
          {row.reviewed ? 'Đã đọc lại' : 'Chờ đọc lại'}
        </button>
      </div>
      <div>
        {editor('source', row.source, sourceDisplay, 'han-text')}
        <small className="unverified">Màu theo đánh dấu box ở bước Gán nhãn OCR.</small>
        <small className="comparison-text">Khi xuất (bỏ dấu câu): {exportPreview(row.source, 'source') || '—'}</small>
      </div>
      <div>
        {editor('target', row.target, targetDisplay)}
        <small className="comparison-text">Khi xuất (chữ thường, bỏ dấu câu): {exportPreview(row.target, 'target') || '—'}</small>
        {splitting && (
          <small className="split-hint">Đặt con trỏ giữa chữ trong một ô, rồi bấm Tách. Ô còn lại sẽ ở cặp đầu.</small>
        )}
      </div>
      {!compact && <div className="alignment-tools">
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
      </div>}
    </div>
  );
}
