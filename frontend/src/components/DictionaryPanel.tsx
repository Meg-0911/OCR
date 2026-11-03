import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, Search, X } from 'lucide-react';
import { api } from '../api';
import type { DictionaryEntry, DictionaryLookup } from '../types';

export function CharacterStrip({
  text,
  onLookup,
}: {
  text: string;
  onLookup: (char: string, index: number) => void;
}) {
  let offset = 0;
  const chars = Array.from(text).map((char) => {
    const index = offset;
    offset += char.length;
    return { char, index };
  });
  if (!chars.some(({ char }) => /\p{Script=Han}/u.test(char))) return null;
  return (
    <div className="character-lookup">
      <small>Bấm từng chữ để tra nghĩa và dị thể</small>
      <div>
        {chars.map(({ char, index }) =>
          /\p{Script=Han}/u.test(char) ? (
            <button
              key={index}
              className="han-text"
              title={`Tra chữ ${char}`}
              aria-label={`Tra chữ ${char} tại vị trí ${index + 1}`}
              onClick={(event) => {
                event.stopPropagation();
                onLookup(char, index);
              }}
            >
              {char}
            </button>
          ) : (
            <span key={index}>{char}</span>
          ),
        )}
      </div>
    </div>
  );
}

export default function DictionaryPanel({
  character,
  canReplace,
  onReplace,
  onClose,
}: {
  character: string;
  canReplace: boolean;
  onReplace: (char: string) => void;
  onClose: () => void;
}) {
  const [query, setQuery] = useState(character);
  const [result, setResult] = useState<DictionaryLookup | null>(null);
  const [matches, setMatches] = useState<DictionaryEntry[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const requestId = useRef(0);
  async function lookup(char: string) {
    const id = ++requestId.current;
    setBusy(true);
    setError('');
    setResult(null);
    setQuery(char);
    setMatches([]);
    try {
      const value = await api.lookupCharacter(char);
      if (id === requestId.current) setResult(value);
    } catch (e) {
      if (id === requestId.current)
        setError(e instanceof Error ? e.message : 'Không tra được từ điển.');
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }
  useEffect(() => {
    if (character) void lookup(character);
  }, [character]);
  useEffect(
    () => () => {
      requestId.current++;
    },
    [],
  );
  async function search() {
    if (Array.from(query.trim()).length === 1 && /\p{Script=Han}/u.test(query)) {
      await lookup(query.trim());
      return;
    }
    const id = ++requestId.current;
    setBusy(true);
    setError('');
    setResult(null);
    setMatches([]);
    try {
      const entries = await api.searchDictionary(query);
      if (id === requestId.current) setMatches(entries);
    } catch (e) {
      if (id === requestId.current) setError(e instanceof Error ? e.message : 'Không tìm được từ.');
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }
  const entry = result?.entry;
  return (
    <aside className="dictionary-panel" aria-label="Từ điển hỗ trợ hiệu đính">
      <div className="dictionary-heading">
        <strong>Từ điển Hán / Nôm</strong>
        <button className="icon-button" aria-label="Đóng từ điển" onClick={onClose}>
          <X size={19} />
        </button>
      </div>
      <form
        className="dictionary-search"
        onSubmit={(event) => {
          event.preventDefault();
          void search();
        }}
      >
        <input
          aria-label="Tìm chữ hoặc âm đọc"
          maxLength={100}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Nhập chữ hoặc âm Việt…"
        />
        <button
          className="icon-button"
          aria-label="Tìm trong từ điển"
          disabled={busy || !query.trim()}
        >
          <Search size={18} />
        </button>
      </form>
      <p className="muted">
        Tra tại máy: ưu tiên bộ Nôm cục bộ nếu có, dùng Unihan dự phòng. Chỉ thay chữ khi bạn chọn
        áp dụng.
      </p>
      {busy && <LoaderCircle className="spin" size={22} />}
      {error && <p role="alert">{error}</p>}
      {!busy && result && !entry && (
        <p>
          Chưa có mục từ cho “{result.query}”. Đây chưa phải bằng chứng chữ OCR sai. Nếu chưa cài dữ
          liệu, chạy <code>py backend/setup_dictionary.py</code>.
        </p>
      )}
      {!busy && entry && (
        <>
          <div className="dictionary-character han-text">{entry.character}</div>
          <code>{entry.codepoint}</code>
          <p>
            <strong>Âm Việt:</strong> {entry.readings.join(' · ') || 'Chưa có dữ liệu'}
          </p>
          {entry.mandarin && (
            <p>
              <strong>Quan thoại:</strong> {entry.mandarin}
            </p>
          )}
          <h3>Nghĩa {entry.language === 'en' ? '(tiếng Anh)' : '(tiếng Việt)'}</h3>
          {entry.definitions.length ? (
            entry.definitions.map((definition, index) => <p key={index}>{definition}</p>)
          ) : (
            <p>Chưa có nghĩa; chỉ có dữ liệu âm đọc hoặc dị thể.</p>
          )}
          <p className="muted">
            Nguồn:{' '}
            {entry.source_url ? (
              <a href={entry.source_url} target="_blank" rel="noreferrer">
                {entry.source}
              </a>
            ) : (
              entry.source
            )}
          </p>
          {canReplace && entry.character !== character && (
            <button className="secondary-button" onClick={() => onReplace(entry.character)}>
              Thay chữ đang chọn bằng {entry.character}
            </button>
          )}
          <h3>Các dạng chữ khác</h3>
          {entry.variants.length ? (
            entry.variants.map((variant, index) => (
              <div className="dictionary-variant" key={`${variant.character}-${index}`}>
                <button
                  className="han-text"
                  title="Tra nghĩa dạng chữ này"
                  onClick={() => void lookup(variant.character)}
                >
                  {variant.character}
                </button>
                <div>
                  <strong>{variant.kind}</strong>
                  <p>{variant.readings.join(' · ')}</p>
                  <p>{variant.definitions.join('; ') || 'Chưa có nghĩa trong nguồn dự phòng'}</p>
                  {canReplace && (
                    <button className="text-button" onClick={() => onReplace(variant.character)}>
                      Thay chữ đang chọn bằng {variant.character}
                    </button>
                  )}
                </div>
              </div>
            ))
          ) : (
            <p>Không có dị thể được ghi nhận trong nguồn này.</p>
          )}
        </>
      )}
      {!busy &&
        matches.map((match) => (
          <button
            key={match.character}
            className="dictionary-match"
            onClick={() => void lookup(match.character)}
          >
            <span className="han-text">{match.character}</span>
            <span>
              {match.readings.join(' · ')}
              <small>{match.definitions.join('; ')}</small>
            </span>
          </button>
        ))}
      <p className="dictionary-note">
        {result?.notice ||
          'Mục từ và dị thể giúp đọc lại từng chữ; không xác nhận độ đúng ngữ nghĩa của câu hoặc điểm chất lượng ≥95%.'}
      </p>
    </aside>
  );
}
