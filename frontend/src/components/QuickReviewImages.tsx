import { useEffect, useState } from 'react';
import { api } from '../api';
import type { Page, QuickCard } from '../types';
import { imageRegionBounds, reviewImageRegions, type ReviewSide } from './quickReviewRegions';

function ReviewImage({ card, page, side }: { card: QuickCard; page: Page; side: ReviewSide }) {
  const [mode, setMode] = useState<'focus' | 'line' | 'page'>('focus');
  const [zoom, setZoom] = useState(1);
  const [imageError, setImageError] = useState(false);
  const { line, focus, canLocateWord, approximate } = reviewImageRegions(card, page, side);
  const viewBox = mode === 'page' ? [0, 0, page.width, page.height]
    : imageRegionBounds(mode === 'line' ? line : focus, page, side === 'source' ? 22 : 35);
  const hasRegions = line.length > 0;
  const clipId = `quick-image-${card.id}-${side}`;
  return <section className={`quick-image-panel ${side}`} aria-label={`Ảnh ${side === 'source' ? 'Hán Nôm' : 'Quốc ngữ'} trang ${page.number}`}>
    <div className="quick-image-heading"><strong>{side === 'source' ? 'Hán Nôm' : 'Quốc ngữ'}</strong><span>Trang {page.number}</span></div>
    <div className="quick-image-tools">
      {(['focus', 'line', 'page'] as const).map(value => <button key={value} type="button" aria-pressed={mode === value} onClick={() => { setMode(value); setZoom(1); }}>
        {value === 'focus' ? 'Chỗ đang xét' : value === 'line' ? 'Cả dòng' : 'Cả trang'}
      </button>)}
      <button type="button" aria-label={`Phóng ảnh ${side === 'source' ? 'Nôm' : 'Quốc ngữ'}`} onClick={() => setZoom(zoom === 1 ? 2 : 1)}>{zoom}×</button>
    </div>
    <div className={`quick-image-stage ${mode === 'page' || !hasRegions ? 'whole-page' : ''}`}>
      <svg viewBox={viewBox.join(' ')} style={{ width: `${zoom * 100}%`, height: mode === 'page' || !hasRegions ? 'auto' : `${220 * zoom}px` }}
        role="img" aria-label={`Box dòng và vị trí đang xét, trang ${page.number}`}>
        <defs><clipPath id={clipId} clipPathUnits="userSpaceOnUse"><rect x={viewBox[0]} y={viewBox[1]} width={viewBox[2]} height={viewBox[3]} /></clipPath></defs>
        <g clipPath={`url(#${clipId})`}>
        <image href={page.image_url} width={page.width} height={page.height} preserveAspectRatio="none" onError={() => setImageError(true)} />
        {line.map((region, i) => <polygon key={`line-${i}`} points={region.points.map(p => p.join(',')).join(' ')}
          className="quick-image-line" vectorEffect="non-scaling-stroke" />)}
        {focus.map((region, i) => <polygon key={`focus-${i}`} points={region.points.map(p => p.join(',')).join(' ')}
          className={`quick-image-focus ${region.approximate ? 'estimated' : ''}`} vectorEffect="non-scaling-stroke" />)}
        </g>
      </svg>
    </div>
    {imageError && <p role="alert">Không tải được ảnh. Thử mở ảnh gốc bên dưới.</p>}
    <p className="quick-image-legend">{!hasRegions ? 'Chưa có box liên kết chắc chắn cho dòng này.'
      : card.index !== null && !canLocateWord ? 'Khung dòng đã lưu; văn bản đã đổi nên chưa định vị riêng chữ.'
      : approximate ? 'Xanh: box dòng · Cam nét đứt: vị trí chữ ước lượng trong dòng.'
      : 'Xanh: box dòng · Cam: vùng đang đối chiếu.'}</p>
    <a href={page.image_url} target="_blank" rel="noreferrer">Mở ảnh trang {page.number} ↗</a>
  </section>;
}

export default function QuickReviewImages({ card }: { card: QuickCard }) {
  const [loaded, setLoaded] = useState<{ key: string; source: Page | null; target: Page | null; errors: string[] } | null>(null);
  const pageKey = `${card.row.source_page_id || ''}:${card.row.target_page_id || ''}:${card.fingerprint}`;
  const [retry, setRetry] = useState(0);
  useEffect(() => {
    let cancelled = false;
    const sourceId = card.row.source_page_id;
    const targetId = card.row.target_page_id;
    const sourceRequest = sourceId ? api.page(sourceId) : Promise.resolve(null);
    const targetRequest = targetId === sourceId ? sourceRequest : targetId ? api.page(targetId) : Promise.resolve(null);
    void Promise.allSettled([sourceRequest, targetRequest]).then(([source, target]) => {
      if (cancelled) return;
      setLoaded({ key: pageKey, source: source.status === 'fulfilled' ? source.value : null,
        target: target.status === 'fulfilled' ? target.value : null,
        errors: [source, target].flatMap((result, i) => result.status === 'rejected' ? [`Không tải được trang ${i ? 'Quốc ngữ' : 'Nôm'}.`] : []) });
    });
    return () => { cancelled = true; };
  }, [pageKey, retry]);
  const current = loaded?.key === pageKey ? loaded : null;
  return <div className="quick-images">
    {!current ? <p role="status">Đang tải hai trang đối chiếu…</p> : <>
      {(['source', 'target'] as const).map(side => current[side]
        ? <ReviewImage key={`${card.id}:${side}:${current[side].id}`} card={card} page={current[side]} side={side} />
        : <section className="quick-image-missing" key={side}><strong>{side === 'source' ? 'Hán Nôm' : 'Quốc ngữ'}</strong>
          <p>{card.row[`${side}_page_id`] ? 'Ảnh chưa tải được.' : side === 'target'
            ? 'Cặp này chưa có trang ảnh Quốc ngữ liên kết. Mở căn chỉnh đầy đủ để chọn đúng trang.'
            : 'Cặp này chưa có trang ảnh Nôm liên kết.'}</p></section>)}
      {!!current.errors.length && <p role="alert">{current.errors.join(' ')} <button type="button" className="text-button" onClick={() => setRetry(n => n + 1)}>Tải lại ảnh</button></p>}
    </>}
  </div>;
}
