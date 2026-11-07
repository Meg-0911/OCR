import { useEffect, useRef, useState } from 'react';
import { LoaderCircle, Search, X } from 'lucide-react';
import { api } from '../api';
import type { DictionaryEntry, DictionaryLookup, DictionaryReverseMatch } from '../types';

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
  initialMode,
  canReplace,
  onReplace,
  onClose,
}: {
  character: string;
  initialMode: 'character' | 'reading';
  canReplace: boolean;
  onReplace: (char: string) => void;
  onClose: () => void;
}) {
  const [mode, setMode] = useState<'character' | 'reading'>(initialMode);
  const [query, setQuery] = useState(character);
  const [result, setResult] = useState<DictionaryLookup | null>(null);
  const [matches, setMatches] = useState<DictionaryEntry[]>([]);
  const [reverseMatches, setReverseMatches] = useState<DictionaryReverseMatch[]>([]);
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
    setReverseMatches([]);
    setMode('character');
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
  useEffect(() => {
    setMode(initialMode);
    if (initialMode === 'reading') {
      setQuery('');
      setResult(null);
      setMatches([]);
      setReverseMatches([]);
      setError('');
    }
  }, [initialMode]);
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
    setReverseMatches([]);
    try {
      const entries = await api.searchDictionary(query);
      if (id === requestId.current) setMatches(entries);
    } catch (e) {
      if (id === requestId.current) setError(e instanceof Error ? e.message : 'Không tìm được từ.');
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }
  async function reverseSearch() {
    const id = ++requestId.current;
    setBusy(true);
    setError('');
    setResult(null);
    setMatches([]);
    setReverseMatches([]);
    try {
      const groups = await api.reverseSearchDictionary(query);
      if (id === requestId.current) setReverseMatches(groups);
    } catch (e) {
      if (id === requestId.current)
        setError(e instanceof Error ? e.message : 'Không tìm được chữ Hán/Nôm.');
    } finally {
      if (id === requestId.current) setBusy(false);
    }
  }
  const entry = result?.entry;
  return (
    <aside className="dictionary-panel" aria-label="Từ điển hỗ trợ Gán nhãn">
      <div className="dictionary-heading">
        <strong>Từ điển Hán / Nôm</strong>
        <button className="icon-button" aria-label="Đóng từ điển" onClick={onClose}>
          <X size={19} />
        </button>
      </div>
      <div className="dictionary-modes" role="tablist" aria-label="Chiều tra từ điển">
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'character'}
          onClick={() => setMode('character')}
        >
          Tra từ chữ Hán/Nôm
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={mode === 'reading'}
          onClick={() => {
            setMode('reading');
            setQuery('');
            setResult(null);
            setMatches([]);
            setReverseMatches([]);
            setError('');
          }}
        >
          Tìm chữ từ Quốc ngữ
        </button>
      </div>
      <form
        className="dictionary-search"
        onSubmit={(event) => {
          event.preventDefault();
          if (mode === 'reading') void reverseSearch();
          else void search();
        }}
      >
        <input
          aria-label={mode === 'reading' ? 'Nhập tiếng Quốc ngữ' : 'Tìm chữ hoặc âm đọc'}
          maxLength={100}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder={mode === 'reading' ? 'Ví dụ: thiên địa, người…' : 'Nhập chữ Hán/Nôm…'}
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
        {mode === 'reading'
          ? 'Tìm theo từng tiếng Quốc ngữ trong âm đọc Việt của Unihan và dữ liệu Nôm cục bộ; cụm nhiều tiếng được chia thành từng nhóm.'
          : 'Tra tại máy: ưu tiên bộ Nôm cục bộ nếu có, dùng Unihan dự phòng. Chỉ thay chữ khi bạn chọn áp dụng.'}
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
      {!busy && mode === 'reading' && reverseMatches.length > 0 && (
        <div className="dictionary-reverse-results">
          {reverseMatches.map(({ syllable, entries }, index) => (
            <section key={`${syllable}-${index}`}>
              <h3>
                “{syllable}” · {entries.length} chữ
              </h3>
              {entries.length ? (
                entries.map((entry) => (
                  <button
                    key={entry.character}
                    className="dictionary-match"
                    onClick={() => void lookup(entry.character)}
                  >
                    <span className="han-text">{entry.character}</span>
                    <span>
                      {entry.readings.join(' · ')}
                      <small>{entry.definitions.join('; ') || 'Chưa có nghĩa trong nguồn này'}</small>
                    </span>
                  </button>
                ))
              ) : (
                <p>Không có chữ khớp âm đọc này trong dữ liệu từ điển đã cài.</p>
              )}
            </section>
          ))}
        </div>
      )}
      {!busy && mode === 'reading' && reverseMatches.length === 0 && !error && query.trim() && (
        <p>Chưa có kết quả. Từ điển chỉ tìm âm đọc từng tiếng, không dịch nghĩa cả cụm.</p>
      )}
      <p className="dictionary-note">
        {result?.notice ||
          'Mục từ và dị thể giúp đọc lại từng chữ; cần tự kiểm tra nghĩa theo ngữ cảnh.'}
      </p>
    </aside>
  );
}
