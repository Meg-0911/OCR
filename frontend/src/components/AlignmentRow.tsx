import { useLayoutEffect, useRef, useState } from 'react';
import { CheckCheck, Link2, SplitSquareVertical, Trash2 } from 'lucide-react';
import type { Alignment, ReviewKind, ReviewMark } from '../types';
import { splitAlignmentText } from './alignmentSplit';

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
  if (!selection?.rangeCount || !element.contains(selection.focusNode)) return 0;
  const range = selection.getRangeAt(0).cloneRange();
  range.selectNodeContents(element);
  range.setEnd(selection.focusNode!, selection.focusOffset);
  return Array.from(range.toString()).length;
}

function AlignmentEditor({
  side,
  index,
  value,
  display,
  className,
  compact,
  onChange,
  onSelectionChange,
}: {
  side: 'source' | 'target';
  index: number;
  value: string;
  display: ReturnType<typeof colorsFor>;
  className: string;
  compact: boolean;
  onChange: (value: string) => void;
  onSelectionChange: (element: HTMLElement) => void;
}) {
  const editorRef = useRef<HTMLDivElement>(null);
  const [editing, setEditing] = useState(false);

  useLayoutEffect(() => {
    const element = editorRef.current;
    if (!element || editing) return;
    element.replaceChildren(
      ...display.characters.map((character, charIndex) => {
        const span = document.createElement('span');
        span.className = `review-${display.kinds[charIndex]}`;
        span.textContent = character;
        return span;
      }),
    );
  }, [display, editing, value]);

  return (
    <div
      ref={editorRef}
      className={`alignment-editor ${className}`}
      role="textbox"
      aria-label={`${side === 'source' ? 'Hán Nôm' : 'Quốc ngữ'} cặp ${index + 1}`}
      aria-multiline="true"
      contentEditable={!compact}
      suppressContentEditableWarning
      onFocus={() => setEditing(true)}
      onBlur={() => setEditing(false)}
      onInput={(event) => {
        const next = event.currentTarget.innerText.replace(/\r\n/g, '\n').replace(/\n$/, '');
        onChange(next);
      }}
      onSelect={(event) => onSelectionChange(event.currentTarget)}
      onKeyUp={(event) => onSelectionChange(event.currentTarget)}
      onMouseUp={(event) => onSelectionChange(event.currentTarget)}
    />
  );
}

export default function AlignmentRow({
  row,
  index,
  total,
  onChange,
  onRemove,
  onMerge,
  onSplit,
  onDrawBox,
  hasBox = false,
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
  onDrawBox?: (axis: 'vertical' | 'horizontal') => void;
  hasBox?: boolean;
  compact?: boolean;
  sourceColors?: (ReviewKind | undefined)[];
  targetColors?: (ReviewKind | undefined)[];
}) {
  const [splitting, setSplitting] = useState(false);
  const [cut, setCut] = useState<{ side?: 'source' | 'target'; position?: number }>({});
  const marks = row.marks || [];
  const sourceDisplay = colorsFor(row.source, sourceColors, marks, 'source');
  const targetDisplay = colorsFor(row.target, targetColors, marks, 'target');
  function editor(side: 'source' | 'target', value: string, display: ReturnType<typeof colorsFor>, className = '') {
    return (
      <AlignmentEditor
        side={side}
        index={index}
        value={value}
        display={display}
        className={className}
        compact={compact}
        onChange={(next) => {
          if (next !== value) {
            setCut({});
            onChange({
              ...row,
              [side]: next,
              reviewed: false,
              marks: [],
            });
          }
        }}
        onSelectionChange={(element) =>
          setCut({ side, position: selectionOffset(element) })
        }
      />
    );
  }
  function split() {
    const parts = splitAlignmentText(row.source, row.target, cut.side, cut.position);
    if (!parts) {
      setSplitting(true);
      return;
    }
    onSplit?.(parts.source, parts.target);
    setSplitting(false);
    setCut({});
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
        {onDrawBox && (
          <div className="sentence-box-actions">
            <small>{hasBox ? 'Đã có box cho câu' : 'Chưa có box cho câu'}</small>
            <button type="button" onClick={() => onDrawBox('vertical')}>Vẽ box dọc</button>
            <button type="button" onClick={() => onDrawBox('horizontal')}>Vẽ box ngang</button>
          </div>
        )}
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
          <small className="split-hint" role="status">
            Đặt một con trỏ tại ranh giới trong một vế rồi bấm Tách lần nữa. Quốc ngữ sẽ được chia theo ranh giới từ gần nhất.
          </small>
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
          title="Tách theo vị trí con trỏ trong một vế"
          aria-label={`Tách cặp ${index + 1}`}
          aria-pressed={splitting}
          disabled={Array.from(row.source).length < 2 && Array.from(row.target).length < 2}
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
