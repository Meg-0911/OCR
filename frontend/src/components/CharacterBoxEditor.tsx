import { useState } from 'react';
import { Search } from 'lucide-react';
import type { Box, ReviewKind } from '../types';
export { groupCharacterBoxes } from './boxText';

export default function CharacterBoxEditor({
  boxes,
  selected,
  selectedIds,
  disabled,
  onSelect,
  onHover,
  onChange,
  onLookup,
  onOrder,
  onRenumber,
  onMark,
  onMarkAll,
  pairedWords,
}: {
  boxes: Box[];
  pairedWords: string[];
  selected: string | null;
  selectedIds: string[];
  disabled: boolean;
  onSelect: (id: string) => void;
  onHover: (id: string) => void;
  onChange: (box: Box, text: string) => void;
  onLookup: (box: Box, character: string, index: number) => void;
  onOrder: (box: Box, order: number | null) => void;
  onRenumber: () => void;
  onMark: (id: string, kind: ReviewKind) => void;
  onMarkAll: (kind: ReviewKind) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const selectedBox = boxes.find((box) => box.id === selected);
  const selectedIndex = selectedBox ? boxes.indexOf(selectedBox) : -1;
  const pairedWordIndex = selectedBox?.review_order != null
    ? selectedBox.review_order - 1
    : selectedIndex;
  const pairedWord = pairedWordIndex >= 0 ? pairedWords[pairedWordIndex] : undefined;
  const orderValues = boxes.map((box, index) => box.review_order ?? (boxes.some((item) => item.review_order !== undefined) ? null : index + 1));
  const orderConflict = orderValues.some((order) => order === null) || new Set(orderValues).size !== boxes.length ||
    [...orderValues].sort((a, b) => (a || 0) - (b || 0)).some((order, index) => order !== index + 1);
  function lookup(box: Box, input: HTMLInputElement | null) {
    const cursor = Math.max(0, (input?.selectionStart || 0) - 1);
    let offset = 0;
    for (const character of Array.from(box.transcription)) {
      if (offset + character.length > cursor) {
        onLookup(box, character, offset);
        return;
      }
      offset += character.length;
    }
    onLookup(box, '', 0);
  }
  return (
    <div className="character-box-editor">
      <div className="character-box-toolbar">
        <small>{boxes.length} box ký tự</small>
        <button
          type="button"
          className="secondary-button"
          disabled={disabled || selectedIds.length < 2}
          title="Đánh lại số cho toàn bộ box theo chiều đọc đã gán cho trang"
          onClick={onRenumber}
        >
          Đánh số lại trang
        </button>
        {orderConflict && <small role="alert">Số thứ tự box bị thiếu hoặc trùng; hãy sửa trước khi hoàn thành trang.</small>}

        <button
          type="button"
          className="text-button"
          aria-expanded={!collapsed}
          onClick={() => setCollapsed((value) => !value)}
        >
          {collapsed ? 'Hiện danh sách box' : 'Thu gọn danh sách box'}
        </button>
      </div>
      <div className="character-review-toolbar" aria-label="Đánh dấu màu chữ đang chọn">
        <span>
          {selectedBox
            ? `Chữ đang chọn: ${selectedBox.transcription || '—'} ↔ ${pairedWord || 'chưa có từ Quốc ngữ'}`
            : 'Chọn một chữ để đánh dấu:'}
        </span>
        <button
          type="button"
          disabled={!selectedBox || disabled}
          onClick={() => selectedBox && onMark(selectedBox.id, 'match')}
        >
          Đen
        </button>
        <button
          type="button"
          disabled={!selectedBox || disabled}
          onClick={() => selectedBox && onMark(selectedBox.id, 'mismatch')}
        >
          Đỏ
        </button>
        <button
          type="button"
          disabled={!selectedBox || disabled}
          onClick={() => selectedBox && onMark(selectedBox.id, 'unknown')}
        >
          Thiếu từ điển
        </button>
        <button type="button" disabled={disabled} onClick={() => onMarkAll('match')}>
          Đặt hết đen
        </button>
        <small>Alt + 1: đen; 2: đỏ; 3: thiếu từ điển</small>
      </div>
      {!collapsed && (
        <div className="character-box-line">
          <div>
            {[...boxes].sort((a, b) =>
              (a.review_order ?? boxes.indexOf(a) + 1) - (b.review_order ?? boxes.indexOf(b) + 1),
            ).map((box, index) => (
              <div
                key={box.id}
                data-row={box.id}
                className={`character-box-cell review-${box.review_kind || 'match'} ${selected === box.id ? 'selected' : ''} ${box.transcription.includes('□') ? 'uncertain' : ''}`}
                onMouseEnter={() => onHover(box.id)}
              >
                <input
                  className="han-text"
                  style={{ width: `${Math.min(180, Math.max(38, Array.from(box.transcription).length * 28 + 12))}px` }}
                  aria-label={box.transcription ? `Ký tự ${box.transcription} theo thứ tự ${index + 1}` : `Ô trống theo thứ tự ${index + 1}`}
                  value={box.transcription}
                  disabled={disabled}
                  onFocus={() => onSelect(box.id)}
                  onChange={(event) => {
                    if (!(event.nativeEvent as InputEvent).isComposing)
                      onChange(box, event.target.value);
                  }}
                  onCompositionEnd={(event) => onChange(box, event.currentTarget.value)}
                />
                <input
                  className="character-order-input"
                  type="number"
                  min="1"
                  aria-label={`Số thứ tự box ${box.transcription || 'trống'}`}
                  aria-invalid={orderConflict}
                  value={box.review_order ?? (boxes.some((item) => item.review_order !== undefined) ? '' : boxes.indexOf(box) + 1)}
                  disabled={disabled}
                  onFocus={() => onSelect(box.id)}
                  onChange={(event) => onOrder(box, /^[1-9]\d*$/u.test(event.target.value) ? Number(event.target.value) : null)}
                />
                <button
                  className="character-dictionary-button"
                  aria-label={box.transcription ? `Tra chữ ${box.transcription}` : 'Tra âm đọc cho ô trống'}
                  title={box.transcription ? 'Tra từ điển' : 'Tìm chữ cho ô trống'}
                  onClick={(event) => lookup(box, event.currentTarget.parentElement?.querySelector('input.han-text') || null)}
                >
                  <Search size={12} />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}
