import { useEffect, useRef, useState } from 'react';
import { Check, X, SkipForward, RotateCcw, Search, ExternalLink, ScanLine, BookOpen, ArrowLeft } from 'lucide-react';
import { api } from '../api';
import QuickReviewImages from './QuickReviewImages';
import type { NomDetail, NomSearch, QuickStatus } from '../types';

export default function QuickReview({ bookId, onChanged, onOpenAlignment }: {
  bookId: string; onChanged: () => void; onOpenAlignment: (pageId?: string | null) => void;
}) {
  const [status, setStatus] = useState<QuickStatus | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [deferred, setDeferred] = useState(false);
  const [source, setSource] = useState('');
  const [target, setTarget] = useState('');
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<NomSearch | null>(null);
  const [detail, setDetail] = useState<NomDetail | null>(null);
  const [detailError, setDetailError] = useState('');
  const [searching, setSearching] = useState(false);
  const [showContext, setShowContext] = useState(false);
  const [selectedGlyph, setSelectedGlyph] = useState<number | null>(null);
  const actionLock = useRef(false);
  const statusRequest = useRef(0);
  const card = status?.card;
  const detailCharacter = card?.index === null ? (selectedGlyph === null ? '' : Array.from(source)[selectedGlyph] || '') : source;
  const running = status?.job.status === 'running';
  const fail = (e: unknown) => setError(e instanceof Error ? e.message : 'Không lưu được. Hãy thử lại.');
  async function refresh() {
    const request = ++statusRequest.current;
    const next = await api.quickStatus(bookId, deferred);
    if (request === statusRequest.current) setStatus(next);
  }
  useEffect(() => {
    let cancelled = false;
    const load = async () => {
      const request = ++statusRequest.current;
      try { const s = await api.quickStatus(bookId, deferred); if (!cancelled && request === statusRequest.current && !actionLock.current) setStatus(s); }
      catch (e) { if (!cancelled) fail(e); }
    };
    void load();
    const timer = window.setInterval(() => { if (!actionLock.current) void load(); }, 2500);
    return () => { cancelled = true; clearInterval(timer); };
  }, [bookId, deferred]);
  useEffect(() => {
    setSource(card?.source || ''); setTarget(card?.target || ''); setQuery(card?.query || '');
    setShowContext(false); setSelectedGlyph(null); setDetail(null); setDetailError('');
  }, [card?.id, card?.fingerprint]);
  useEffect(() => {
    let cancelled = false;
    setResults(null);
    if (!query.trim()) { setSearching(false); return; }
    setSearching(true);
    const timer = window.setTimeout(() => {
      void api.nomSearch(query.trim()).then(r => { if (!cancelled) setResults(r); })
        .catch(e => { if (!cancelled) fail(e); }).finally(() => { if (!cancelled) setSearching(false); });
    }, 180);
    return () => { cancelled = true; clearTimeout(timer); };
  }, [query]);
  useEffect(() => {
    let cancelled = false;
    setDetail(null); setDetailError('');
    if (!detailCharacter || Array.from(detailCharacter).length > 4) return;
    void api.nomDetail(detailCharacter).then(d => { if (!cancelled) setDetail(d); })
      .catch(e => { if (!cancelled) setDetailError(e instanceof Error ? e.message : 'Chưa lấy được nghĩa.'); });
    return () => { cancelled = true; };
  }, [detailCharacter]);
  async function act(action: 'match' | 'mismatch' | 'unknown' | 'defer') {
    if (!card || card.stale || running || actionLock.current) return;
    actionLock.current = true; setBusy(true); setError('');
    try {
      await api.quickDecide(bookId, card.id, { action, fingerprint: card.fingerprint,
        ...(source !== card.source && action !== 'defer' ? { source } : {}),
        ...(target !== card.target && action !== 'defer' ? { target } : {}) });
      await refresh(); onChanged();
    } catch (e) { fail(e); } finally { actionLock.current = false; setBusy(false); }
  }
  async function scan() {
    if (actionLock.current) return;
    actionLock.current = true; setBusy(true); setError('');
    try { await api.quickScan(bookId); await refresh(); } catch (e) { fail(e); }
    finally { actionLock.current = false; setBusy(false); }
  }
  async function undo() {
    if (actionLock.current || running) return;
    actionLock.current = true; setBusy(true); setError('');
    try { await api.quickUndo(bookId); await refresh(); onChanged(); } catch (e) { fail(e); }
    finally { actionLock.current = false; setBusy(false); }
  }
  useEffect(() => {
    function keyboard(e: KeyboardEvent) {
      if ((e.target as HTMLElement).closest('input, textarea, select, [contenteditable="true"]')) return;
      if (e.ctrlKey || e.metaKey || e.altKey) return;
      const actions = { '1': 'match', ArrowRight: 'match', '2': 'mismatch', ArrowLeft: 'mismatch', '3': 'unknown', ' ': 'defer' } as const;
      const action = actions[e.key as keyof typeof actions];
      if (action) { e.preventDefault(); void act(action); }
    }
    window.addEventListener('keydown', keyboard);
    return () => window.removeEventListener('keydown', keyboard);
  });
  const total = Object.values(status?.counts || {}).reduce((a, b) => a + b, 0);
  const done = status?.counts.done || 0;
  function chooseCharacter(character: string) {
    if (card?.index !== null) setSource(character);
    else if (selectedGlyph !== null) { const glyphs = Array.from(source); glyphs.splice(selectedGlyph, 1, character); setSource(glyphs.join('')); }
    else setDetailError('Chọn vị trí chữ Nôm cần thay ở bên trái trước.');
  }
  const scriptNames: Record<string, string> = { seal: 'Triện thư', silk: 'Chữ trên lụa', oracle: 'Giáp cốt', bronze: 'Kim văn',
    clerical: 'Lệ thư', cursive: 'Thảo thư', regular: 'Khải thư', running: 'Hành thư' };
  return <section className="quick-review" aria-label="Duyệt nhanh bán tự động">
    <div className="quick-toolbar">
      <div><span className="eyebrow">MỖI THẺ · MỘT CHỖ CẦN XEM</span><h2>Duyệt nhanh</h2>
        <p>{status?.is_kieu ? 'Đối chiếu Truyện Kiều · bản TXT là nguồn tham khảo, có thể có dị bản.' : 'Lấy âm Quốc ngữ đang có để đối chiếu từ điển Hán Nôm.'}</p></div>
      <button className="secondary-button" disabled={busy || running} onClick={() => void scan()}><ScanLine size={16} />{running ? 'Đang quét…' : 'Quét đối chiếu'}</button>
    </div>
    <div className="quick-progress"><span><strong>{done}</strong> / {total} thẻ đã duyệt</span>
      <progress value={done} max={Math.max(total, 1)} />
      <label><input type="checkbox" checked={deferred} onChange={e => setDeferred(e.target.checked)} /> Xem cả để sau ({status?.counts.deferred || 0})</label>
      <button className="text-button" disabled={busy || running || status?.can_undo === false} onClick={() => void undo()}><RotateCcw size={14} /> Quay lại thẻ trước</button>
    </div>
    {error && <p role="alert" className="quick-error">{error}</p>}
    {status?.export_error && <p role="alert" className="quick-error">{status.export_error}</p>}
    {status?.job.error && <p role="status" className="quick-error">{status.job.error}</p>}
    {status && !status.dictionary_ready && <p className="info-banner">Chưa cài bảng âm Nôm Na Việt. Chạy <code>python -m backend.setup_nom_dictionary</code> rồi khởi động lại backend.</p>}
    {running ? <div className="quick-empty"><ScanLine size={32} /><h3>Đang tìm những chỗ cần bạn xem…</h3>
      <p>{status?.job.processed || 0} / {status?.job.total || '…'} dòng. Có thể rời màn hình; quét vẫn chạy trên backend.</p></div>
      : card ? <div className="quick-layout">
        <article className="quick-card" key={card.id}>
          <header><span>TRANG {card.page_number} · {card.index === null ? 'CẢ DÒNG' : `CHỮ ${card.index + 1}`}</span><span>{card.reason}</span></header>
          {card.stale && <p role="alert" className="quick-error">Dòng đã được sửa ở nơi khác. Quét lại để cập nhật thẻ.</p>}
          <div className="quick-words">
            <label><span>HÁN NÔM HIỆN TẠI</span><textarea aria-label="Chữ Hán Nôm" className="han-text" value={source} onChange={e => setSource(e.target.value)} rows={card.index === null ? 2 : 1} />
              {card.expected_source && card.expected_source !== card.source && <small>Mẫu: <button className="quick-reference han-text" onClick={() => setSource(card.expected_source)}>{card.expected_source}</button></small>}</label>
            <label><span>QUỐC NGỮ HIỆN TẠI</span><textarea aria-label="Chữ Quốc ngữ" value={target} onChange={e => setTarget(e.target.value)} rows={card.index === null ? 3 : 1} />
              {card.expected_target && card.expected_target.toLocaleLowerCase() !== card.target.toLocaleLowerCase() && <small>Mẫu: <button className="quick-reference" onClick={() => setTarget(card.expected_target)}>{card.expected_target}</button></small>}</label>
          </div>
          {card.index === null && <div className="quick-line-lookup"><small>Chọn chữ để tra:</small>
            {Array.from(source).map((c, i) => c.trim() && <button className={`han-text ${selectedGlyph === i ? 'selected' : ''}`} key={`s${i}`} onClick={() => { setSelectedGlyph(i); setQuery(c); }}>{c}</button>)}
            {target.split(/\s+/).filter(Boolean).map((w, i) => <button key={`t${i}`} onClick={() => setQuery(w.replace(/[^\p{L}\p{M}]/gu, ''))}>{w}</button>)}
            <small>Chọn một chữ Nôm ở trên, tra âm mong muốn rồi chọn gợi ý để thay đúng vị trí đó.</small>
          </div>}
          <QuickReviewImages card={card} />
          <button className="text-button quick-context-toggle" onClick={() => setShowContext(!showContext)}><BookOpen size={14} />{showContext ? 'Thu gọn ngữ cảnh' : 'Xem ngữ cảnh'}</button>
          {showContext && <div className="quick-context"><p className="han-text">{card.row.source}</p><p>{card.row.target}</p>
            {card.reference && <><small>TXT · dòng {card.reference.position} (số gốc {card.reference.label || 'thiếu'})</small><p className="han-text">{card.reference.source || 'Thiếu Nôm trong nguồn'}</p><p>{card.reference.target}</p><small>{card.reference.note}</small></>}
            <button className="text-button" onClick={() => onOpenAlignment(card.row.source_page_id)}>Mở căn chỉnh đầy đủ ↗</button></div>}
          {(source !== card.source || target !== card.target) && <p className="quick-change">Đã chọn thay đổi · bấm một màu bên dưới để lưu và sang thẻ tiếp.</p>}
          <footer>
            <button className="quick-back-button" disabled={busy || running || status?.can_undo === false} onClick={() => void undo()}
              title="Hoàn tác lần bấm gần nhất và mở lại thẻ đó"><ArrowLeft size={17} /> Quay lại <small>Hoàn tác lần bấm vừa rồi</small></button>
            <button className="quick-action red" disabled={busy || card.stale} onClick={() => void act('mismatch')}><X />Đỏ<kbd>2 / ←</kbd></button>
            <button className="quick-action" disabled={busy || card.stale} onClick={() => void act('defer')}><SkipForward />Để sau<kbd>Space</kbd></button>
            <button className="quick-action" disabled={busy || card.stale} onClick={() => void act('unknown')}><Search />Thiếu từ điển<kbd>3</kbd></button>
            <button className="quick-action black" disabled={busy || card.stale} onClick={() => void act('match')}><Check />Đúng · đen<kbd>1 / →</kbd></button>
          </footer>
          <small className="quick-save-state" aria-live="polite">{busy ? 'Đang lưu…' : 'Quyết định được lưu ngay. Có thể đóng và mở lại để tiếp tục.'}</small>
        </article>
        <aside className="quick-dictionary">
          <div className="eyebrow">TỪ ĐIỂN HÁN NÔM</div><h3>Nôm Na Việt</h3>
          <label className="quick-search"><Search size={17} /><input aria-label="Tra âm Quốc ngữ hoặc chữ Nôm" value={query} onChange={e => setQuery(e.target.value)} placeholder="Âm Quốc ngữ hoặc chữ Nôm…" /></label>
          <div className="quick-search-options"><button className="text-button" onClick={() => setQuery(target)}>Tra âm hiện tại</button><button className="text-button" onClick={() => setQuery(source)}>Tra chữ hiện tại</button>
            {results && <a href={results.url} target="_blank" rel="noreferrer">Mở nguồn <ExternalLink size={12} /></a>}</div>
          {searching && <p role="status">Đang tra…</p>}
          {results && !results.entries.length && <p>Chưa tìm thấy âm/chữ này trong bảng Nôm. Thử cách viết khác hoặc mở nguồn để tra thêm.</p>}
          <div className="quick-candidates">{results?.entries.map((entry, i) => <button key={`${entry.character}-${i}`} title={`${entry.readings.join(', ')} · ${entry.summary}`}
            className={source === entry.character ? 'selected' : ''}
            onClick={() => chooseCharacter(entry.character)}>
            <span className="han-text">{entry.character}</span><small>{entry.summary || entry.readings.slice(0, 4).join(', ')}</small></button>)}</div>
          {!!detail?.variants?.length && <section className="quick-variants" aria-label="Dị thể có thể chọn">
            <h4>Dị thể của <span className="han-text">{detail.character}</span></h4>
            <div className="quick-candidates">{detail.variants.map((variant, i) => <button key={`${variant.character}-${i}`} onClick={() => chooseCharacter(variant.character)}
              title={`${variant.kind} · ${variant.source} · ${variant.readings.join(', ')}`}>
              <span className="han-text">{variant.character}</span><small>{variant.kind}</small><small>{variant.readings.join(', ')}</small>
            </button>)}</div><small>Chọn chữ để thay; bấm màu trên thẻ để lưu.</small>
          </section>}
          {!!detail?.historical_forms?.length && <section className="quick-variants" aria-label="Ảnh các dạng chữ cổ">
            <h4>Dạng chữ tư liệu của <span className="han-text">{detail.character}</span></h4>
            <div className="quick-historical-forms">{detail.historical_forms.map(form => <a key={form.id} href={form.image_url} target="_blank" rel="noreferrer" title={`${scriptNames[form.script_type] || form.script_type} · ${form.source} · mở ảnh lớn`}>
              <img src={form.image_url} alt={`${detail.character} · ${scriptNames[form.script_type] || form.script_type}`} loading="lazy" />
              <small>{scriptNames[form.script_type] || form.script_type}</small>
            </a>)}</div><small>Ảnh để đối chiếu hình chữ · bấm để phóng lớn.</small>
          </section>}
          {detail?.variants_notice && <p className="quick-detail-notice">{detail.variants_notice}</p>}
          {detail && <div className="quick-definition"><h4><span className="han-text">{detail.character}</span> · nghĩa và xuất xứ</h4>
            {detail.meanings.slice(0, 10).map((m, i) => <p key={i}>{m.reading && <strong>{m.reading}: </strong>}{m.vietnameseMeaning || m.definition}<small>{m.source}</small></p>)}
            {detail.examples.slice(0, 2).map((e, i) => <blockquote key={i}><span className="han-text">{e.classicalTextExcerpt}</span><p>{e.modernVietnameseTranslation}</p><small>{e.source}</small></blockquote>)}</div>}
          {detailError && <small className="quick-detail-notice">{detailError}</small>}
          <p className="quick-footnote">Bảng âm tra cục bộ; nghĩa đầy đủ tải từ nguồn và được lưu lại. Có âm đọc phù hợp là gợi ý để đối chiếu ngữ cảnh.</p>
        </aside>
      </div> : <div className="quick-empty"><Check size={36} /><h3>{status?.job.status === 'idle' ? 'Bắt đầu một lượt đối chiếu' : 'Đã hết thẻ trong bộ lọc này'}</h3>
        <p>{status?.job.status === 'idle' ? 'Quét sách để tự nhận các chữ khớp và gom chỗ cần xem thành thẻ.' : 'Bạn có thể xem các thẻ để sau hoặc quét lại sau khi sửa dữ liệu.'}</p>
        {status?.job.matched !== undefined && <p>{status.job.matched.toLocaleString()} chữ khớp · {status.job.corrected || 0} lỗi đuôi t đã sửa.</p>}
      </div>}
  </section>;
}
