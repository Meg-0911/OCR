import { useEffect, useId, useRef, useState, type CSSProperties, type PointerEvent } from 'react';
import {
  ArrowLeft,
  Check,
  Eye,
  FileText,
  GripVertical,
  LoaderCircle,
  Maximize2,
  Minimize2,
  Minus,
  Plus,
  Search,
} from 'lucide-react';
import { api } from '../api';
import { formatBookTitle } from './BookCard';
import type { Book, Category, Page } from '../types';

const categories: Record<Category, string> = {
  both: 'Song ngữ (Nôm + Quốc ngữ)',
  ch: 'Hán Nôm',
  vi: 'Quốc ngữ',
  intro: 'Giới thiệu',
  ref: 'Chú thích',
  toc: 'Mục lục',
  blank: 'Trang trắng',
  misc: 'Chưa phân loại',
};

type Props = {
  book: Book;
  onClose: () => void;
  onError: (error: unknown) => void;
};

const defaultColumns = [17, 51, 32];
const minimumColumns = [130, 240, 210];
const columnsStorageKey = 'nom-reader-columns-v1';

function readColumns(): number[] {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(columnsStorageKey) || 'null');
    if (
      Array.isArray(saved) &&
      saved.length === 3 &&
      saved.every((value) => typeof value === 'number' && Number.isFinite(value) && value > 0)
    )
      return saved;
  } catch {
    // Use the default layout when storage is unavailable.
  }
  return defaultColumns;
}

export default function LibraryBookReader({ book, onClose, onError }: Props) {
  const [pages, setPages] = useState<Page[]>([]);
  const [loading, setLoading] = useState(true);
  const [selectedId, setSelectedId] = useState<string>('');
  const [search, setSearch] = useState('');
  const [zoom, setZoom] = useState(100);
  const [columns, setColumns] = useState(readColumns);
  const [activeDivider, setActiveDivider] = useState<number | null>(null);
  const [isFullscreen, setIsFullscreen] = useState(false);
  const pagesPane = useRef<HTMLElement>(null);
  const imagePane = useRef<HTMLDivElement>(null);
  const linesPane = useRef<HTMLDivElement>(null);
  const drag = useRef<{ index: number; x: number; widths: number[] } | null>(null);
  const paneId = useId();

  useEffect(() => {
    try {
      localStorage.setItem(columnsStorageKey, JSON.stringify(columns));
    } catch {
      // Resizing still works without saving the preference.
    }
  }, [columns]);

  useEffect(() => {
    const sync = () =>
      setIsFullscreen(
        Boolean(imagePane.current && document.fullscreenElement === imagePane.current),
      );
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);

  function paneWidths() {
    return [pagesPane, imagePane, linesPane].map(
      (pane) => pane.current?.getBoundingClientRect().width || 0,
    );
  }

  function resizeColumns(index: number, delta: number, widths = paneWidths()) {
    if (widths.some((width) => !width)) return;
    const next = [...widths];
    const clampedDelta = Math.max(
      minimumColumns[index] - widths[index],
      Math.min(widths[index + 1] - minimumColumns[index + 1], delta),
    );
    next[index] += clampedDelta;
    next[index + 1] -= clampedDelta;
    setColumns(next);
  }

  function endResize(event: PointerEvent<HTMLDivElement>) {
    drag.current = null;
    setActiveDivider(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  }

  function divider(index: number) {
    const label = index === 0 ? 'Độ rộng danh sách trang' : 'Độ rộng ảnh trang sách';
    return (
      <div
        className={`reader-column-divider ${activeDivider === index ? 'resizing' : ''}`}
        role="separator"
        aria-label={label}
        aria-orientation="vertical"
        aria-controls={`${paneId}-${index === 0 ? 'pages' : 'image'}`}
        aria-valuenow={Math.round(
          (columns[index] / columns.reduce((sum, width) => sum + width, 0)) * 100,
        )}
        aria-valuetext={`${Math.round((columns[index] / columns.reduce((sum, width) => sum + width, 0)) * 100)}% chiều ngang`}
        tabIndex={0}
        title="Kéo để chỉnh độ rộng · Nháy đúp để khôi phục · Phím ← → để điều chỉnh"
        onPointerDown={(event) => {
          if (event.button !== 0) return;
          event.preventDefault();
          event.currentTarget.focus();
          drag.current = { index, x: event.clientX, widths: paneWidths() };
          setActiveDivider(index);
          event.currentTarget.setPointerCapture(event.pointerId);
        }}
        onPointerMove={(event) => {
          if (drag.current?.index === index) {
            resizeColumns(index, event.clientX - drag.current.x, drag.current.widths);
          }
        }}
        onPointerUp={endResize}
        onPointerCancel={endResize}
        onLostPointerCapture={() => {
          drag.current = null;
          setActiveDivider(null);
        }}
        onDoubleClick={() => setColumns(defaultColumns)}
        onKeyDown={(event) => {
          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return;
          event.preventDefault();
          const step = event.shiftKey ? 50 : 10;
          const delta =
            event.key === 'Home'
              ? -Infinity
              : event.key === 'End'
                ? Infinity
                : event.key === 'ArrowLeft'
                  ? -step
                  : step;
          resizeColumns(index, delta);
        }}
      >
        <GripVertical size={12} aria-hidden="true" />
      </div>
    );
  }

  async function toggleFullscreen() {
    try {
      if (document.fullscreenElement === imagePane.current) await document.exitFullscreen();
      else await imagePane.current?.requestFullscreen();
    } catch (error) {
      onError(error);
    }
  }

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    api
      .pages(book.id)
      .then((data) => {
        if (cancelled) return;
        setPages(data);
        if (data.length > 0) {
          const firstWithContent = data.find((p) => p.source_text || p.target_text);
          setSelectedId(firstWithContent ? firstWithContent.id : data[0].id);
        }
      })
      .catch((err) => {
        if (!cancelled) onError(err);
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [book.id]);

  const cleanTitle = formatBookTitle(book.name);
  const selectedPage = pages.find((p) => p.id === selectedId);

  const filteredPages = pages.filter((p) => {
    if (!search) return true;
    return String(p.number).includes(search);
  });

  const doneCount = pages.filter((p) => p.status === 'done').length;

  const hanLines = selectedPage?.source_text
    ? selectedPage.source_text.split(/\r?\n/).filter((l) => l.trim().length > 0)
    : [];

  const viLines = selectedPage?.target_text
    ? selectedPage.target_text.split(/\r?\n/).filter((l) => l.trim().length > 0)
    : [];

  return (
    <div className="library-reader">
      <div className="library-reader-topbar">
        <div className="reader-topbar-left">
          <button type="button" className="secondary-button" onClick={onClose}>
            <ArrowLeft size={16} />
            Quay lại tủ sách
          </button>
          <div className="reader-title-group">
            <h2 className="reader-title" title={cleanTitle}>
              {cleanTitle}
            </h2>
            <div className="reader-badges">
              <span className="reader-stat-pill">
                {pages.length} trang · {doneCount} đã duyệt
              </span>
              <span className="safe-badge">
                <Eye size={13} />
                Trang sách & kết quả đã lưu
              </span>
            </div>
          </div>
        </div>
      </div>

      {loading ? (
        <div className="reader-loading">
          <LoaderCircle size={28} className="spin" />
          <p>Đang tải các trang sách…</p>
        </div>
      ) : (
        <div
          className="library-reader-body"
          style={
            {
              '--reader-pages-width': `${columns[0]}fr`,
              '--reader-image-width': `${columns[1]}fr`,
              '--reader-lines-width': `${columns[2]}fr`,
            } as CSSProperties
          }
        >
          <aside className="reader-pages-sidebar" ref={pagesPane} id={`${paneId}-pages`}>
            <div className="reader-search-wrap">
              <Search size={14} />
              <input
                aria-label="Tìm số trang"
                placeholder="Tìm trang…"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
              />
            </div>
            <div className="reader-pages-list">
              {filteredPages.map((p) => (
                <button
                  key={p.id}
                  type="button"
                  className={`reader-page-card ${p.id === selectedId ? 'selected' : ''}`}
                  aria-current={p.id === selectedId ? 'page' : undefined}
                  onClick={() => setSelectedId(p.id)}
                >
                  <div className="reader-page-thumb">
                    <img loading="lazy" src={`${p.image_url}?thumbnail=true`} alt="" />
                    {p.status === 'done' && (
                      <span className="thumb-done">
                        <Check size={11} />
                      </span>
                    )}
                  </div>
                  <div className="reader-page-meta">
                    <strong>Trang {String(p.number).padStart(3, '0')}</strong>
                    <small>{categories[p.category]}</small>
                    <span className="reader-content-indicator">
                      {p.source_text || p.target_text ? 'Đã có kết quả' : 'Chưa có kết quả đã lưu'}
                    </span>
                  </div>
                </button>
              ))}
              {!filteredPages.length && (
                <p className="empty-notice">Không tìm thấy trang phù hợp.</p>
              )}
            </div>
          </aside>

          {selectedPage ? (
            <>
              {divider(0)}
              <div className="reader-image-pane" ref={imagePane} id={`${paneId}-image`}>
                <div className="reader-image-controls">
                  <span>
                    <FileText size={14} />
                    <strong>Trang {String(selectedPage.number).padStart(3, '0')}</strong> /{' '}
                    {pages.length}
                  </span>
                  <div className="image-controls">
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Thu nhỏ"
                      onClick={() => setZoom(Math.max(50, zoom - 25))}
                    >
                      <Minus size={14} />
                    </button>
                    <span>{zoom}%</span>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label="Phóng to"
                      onClick={() => setZoom(Math.min(200, zoom + 25))}
                    >
                      <Plus size={14} />
                    </button>
                    <button
                      type="button"
                      className="icon-button"
                      aria-label={isFullscreen ? 'Thoát toàn màn hình' : 'Xem ảnh toàn màn hình'}
                      title={isFullscreen ? 'Thoát toàn màn hình (Esc)' : 'Xem ảnh toàn màn hình'}
                      aria-pressed={isFullscreen}
                      onClick={() => void toggleFullscreen()}
                    >
                      {isFullscreen ? <Minimize2 size={14} /> : <Maximize2 size={14} />}
                    </button>
                  </div>
                </div>
                <div className="reader-image-canvas">
                  <img
                    src={selectedPage.image_url}
                    alt={`Trang ${selectedPage.number}`}
                    draggable={false}
                    style={
                      {
                        '--reader-zoom': zoom / 100,
                        '--reader-image-ratio': selectedPage.width / selectedPage.height,
                      } as CSSProperties
                    }
                  />
                </div>
              </div>

              {divider(1)}
              <div className="reader-lines-pane" ref={linesPane}>
                <div className="reader-pane-header">
                  <div>
                    <h3>
                      <Eye size={17} />
                      Kết quả đã lưu · Trang {selectedPage.number}
                    </h3>
                    <p>
                      Nhãn: <strong>{categories[selectedPage.category]}</strong> · Trạng thái:{' '}
                      <strong>
                        {selectedPage.status === 'done' ? 'Đã xác nhận' : 'Chưa xác nhận'}
                      </strong>
                    </p>
                  </div>
                </div>

                <div className="reader-results-scroll">
                  <div className="reader-section">
                    <div className="reader-section-title">
                      <span>文</span>
                      <h4>Hán Nôm ({hanLines.length} dòng)</h4>
                    </div>
                    {hanLines.length > 0 ? (
                      <div className="reader-lines-list">
                        {hanLines.map((line, idx) => (
                          <div key={idx} className="reader-line-item">
                            <span className="line-num">{idx + 1}</span>
                            <span className="line-content han-text">{line}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="reader-no-text">Chưa có kết quả Hán Nôm cho trang này.</p>
                    )}
                  </div>

                  <div className="reader-section">
                    <div className="reader-section-title">
                      <span>Aa</span>
                      <h4>Quốc ngữ ({viLines.length} dòng)</h4>
                    </div>
                    {viLines.length > 0 ? (
                      <div className="reader-lines-list">
                        {viLines.map((line, idx) => (
                          <div key={idx} className="reader-line-item">
                            <span className="line-num">{idx + 1}</span>
                            <span className="line-content">{line}</span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <p className="reader-no-text">Chưa có kết quả Quốc ngữ cho trang này.</p>
                    )}
                  </div>
                </div>

                <div className="reader-safe-footer">
                  <p>
                    Tủ sách hiển thị ảnh gốc và kết quả đã lưu. Để chỉnh sửa văn bản, chọn tab Hiệu
                    đính OCR.
                  </p>
                </div>
              </div>
            </>
          ) : (
            <div className="reader-empty-selection">
              <p>Sách chưa có trang để hiển thị.</p>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
