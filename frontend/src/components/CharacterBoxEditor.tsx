import { Search } from 'lucide-react';
import type { Box } from '../types';
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
}: {
  boxes: Box[];
  direction: 1 | 2;
  selected: string | null;
  disabled: boolean;
  onSelect: (id: string) => void;
  onChange: (box: Box, text: string) => void;
  onLookup: (box: Box, character: string, index: number) => void;
}) {
  return (
    <div className="character-box-editor">
      <small>{boxes.length} box ký tự</small>
      {groupCharacterBoxes(boxes, direction).map((row, index) => (
        <div className="character-box-line" key={row[0].id}>
          <span className="line-num">{index + 1}</span>
          <div>
            {row.map((box) => (
              <div
                key={box.id}
                data-row={box.id}
                className={`character-box-cell ${selected === box.id ? 'selected' : ''} ${box.transcription.includes('□') ? 'uncertain' : ''}`}
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
                  disabled={!/\p{Script=Han}/u.test(box.transcription)}
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
