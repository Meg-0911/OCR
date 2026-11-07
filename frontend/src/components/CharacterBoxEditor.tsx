import { useState } from 'react';
import { Search } from 'lucide-react';
import type { Box, ReviewKind } from '../types';
import { groupCharacterBoxes } from './boxText';
export { groupCharacterBoxes } from './boxText';

export default function CharacterBoxEditor({
  boxes,
  direction,
  selected,
  disabled,
  onSelect,
  onChange,
  onLookup,
  onMark,
  onMarkAll,
  pairedWords,
}: {
  boxes: Box[];
  pairedWords: string[];
  direction: 1 | 2;
  selected: string | null;
  disabled: boolean;
  onSelect: (id: string) => void;
  onChange: (box: Box, text: string) => void;
  onLookup: (box: Box, character: string, index: number) => void;
  onMark: (id: string, kind: ReviewKind) => void;
  onMarkAll: (kind: ReviewKind) => void;
}) {
  const [collapsed, setCollapsed] = useState(false);
  const selectedBox = boxes.find((box) => box.id === selected);
  const selectedIndex = selectedBox ? boxes.indexOf(selectedBox) : -1;
  const pairedWord = selectedIndex >= 0 ? pairedWords[selectedIndex] : undefined;
  return (
    <div className="character-box-editor">
      <div className="character-box-toolbar">
        <small>{boxes.length} box ký tự</small>
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
      {!collapsed &&
        groupCharacterBoxes(boxes, direction).map((row, index) => (
          <div className="character-box-line" key={row[0].id}>
            <span className="line-num">{index + 1}</span>
            <div>
              {row.map((box) => (
                <div
                  key={box.id}
                  data-row={box.id}
                  className={`character-box-cell review-${box.review_kind || 'match'} ${selected === box.id ? 'selected' : ''} ${box.transcription.includes('□') ? 'uncertain' : ''}`}
                  onMouseEnter={() => onSelect(box.id)}
                >
                  <input
                    className="han-text"
                    aria-label={`Ký tự ${box.transcription} dòng ${index + 1}`}
                    value={box.transcription}
                    disabled={disabled}
                    onFocus={() => onSelect(box.id)}
                    onChange={(event) => {
                      if (!(event.nativeEvent as InputEvent).isComposing)
                        onChange(box, Array.from(event.target.value).slice(0, 1).join(''));
                    }}
                    onCompositionEnd={(event) =>
                      onChange(box, Array.from(event.currentTarget.value).slice(0, 1).join(''))
                    }
                  />
                  <button
                    className="character-dictionary-button"
                    aria-label={`Tra chữ ${box.transcription}`}
                    title="Tra từ điển"
                    disabled={!/\p{Script=Han}|□/u.test(box.transcription)}
                    onClick={() => onLookup(box, Array.from(box.transcription)[0], 0)}
                  >
                    <Search size={12} />
                  </button>
                </div>
              ))}
            </div>
          </div>
        ))}
    </div>
  );
}
