import { useMemo, useState } from 'react';
import type { Alignment, Page } from '../types';
import { linkedLines, reorderLinkedTargets, type Dragged } from './linkedAlignment';

export default function LinkedAlignmentWorkspace({ page, pages, bookName, rows, busy, onReviewPage, onRows }: {
  page: Page;
  pages: Page[];
  bookName: string;
  rows: Alignment[];
  busy: boolean;
  onReviewPage: (reviewed: boolean) => void;
  onRows: (rows: Alignment[], immediate?: boolean) => void;
}) {
  const [search, setSearch] = useState('');
  const [visiblePages, setVisiblePages] = useState<string[] | null>(null);
  const [dragged, setDragged] = useState<Dragged | null>(null);
  const [selected, setSelected] = useState<Dragged | null>(null);
  const linkedPages = useMemo(() => [page, ...pages.filter((item) => page.linked_page_ids.includes(item.id))]
    .filter((item) => !item.ocr_skip).sort((a, b) => a.number - b.number), [page, pages]);
  const targets = useMemo(() => linkedPages.filter((item) => item.ocr_languages.includes('vi'))
    .flatMap((item) => linkedLines(item.target_text || item.vi_boxes.map((box) => box.transcription).join('\n'))
      .map((text, lineIndex) => ({ text, pageId: item.id, lineIndex }))), [linkedPages]);
  const prefix = `${bookName}.${String(page.number).padStart(3, '0')}.`;
  const pageRows = rows.filter((row) => row.sentence_id.startsWith(prefix));
  const claimedElsewhere = new Set(rows.filter((row) => !row.sentence_id.startsWith(prefix) &&
    row.target_page_id && row.target_line_index != null)
    .map((row) => `${row.target_page_id}:${row.target_line_index}`));
  const availableTargets = targets.filter((target) => !claimedElsewhere.has(`${target.pageId}:${target.lineIndex}`));

  const assigned = new Set(pageRows.filter((row) => row.target_page_id && row.target_line_index != null)
    .map((row) => `${row.target_page_id}:${row.target_line_index}`));
  const unassigned = availableTargets.filter((target) => !assigned.has(`${target.pageId}:${target.lineIndex}`));
  const pairedRows = pageRows.map((row, index) => ({ row, index })).filter(({ row }) => !!row.target);
  const unmatchedSource = pageRows.map((row, index) => ({ row, index })).filter(({ row }) => !row.target);
  const allReviewed = pageRows.every((row) => row.reviewed);
  const reviewedCount = pageRows.filter((row) => row.reviewed).length;
  const visible = visiblePages || [page.id, ...linkedPages.filter((item) => item.id !== page.id && item.ocr_languages.includes('vi')).slice(0, 1).map((item) => item.id)];

  function assign(item: Dragged, destination: number) {
    const updated = reorderLinkedTargets(pageRows, item, destination);
    const updates = new Map(updated.map((row) => [row.id, row]));
    onRows(rows.map((row) => updates.get(row.id) || row));
    setDragged(null);
    setSelected(null);
  }

  if (!pageRows.length) return null;

  return (
    <section className="linked-alignment" aria-label="Ghép dòng giữa các trang">
      <div className="linked-alignment-title">
        <h3>Ghép dòng trên ảnh · Hán Nôm {String(page.number).padStart(3, '0')} ↔ Quốc ngữ {linkedPages.filter((item) => item.ocr_languages.includes('vi')).map((item) => String(item.number).padStart(3, '0')).join(', ')}</h3>
        <div><span>{reviewedCount}/{pageRows.length} cặp đã xác nhận</span><button type="button" className="secondary-button" disabled={busy} onClick={() => onReviewPage(!allReviewed)}>{allReviewed ? 'Mở lại trang để đọc lại' : 'Xác nhận xong trang'}</button></div>
      </div>
      <p>Kéo dòng Quốc ngữ tới dòng Hán Nôm tương ứng. Thứ tự mặc định là dòng 1 ↔ dòng 1; kéo B lên dòng 1 sẽ đẩy A xuống dòng 2. Mỗi cặp giữ ID theo trang Hán Nôm.</p>
      <div className="linked-alignment-controls">
        <input type="search" aria-label="Tìm nội dung trong trang liên kết" placeholder="Tìm dòng hoặc số trang…" value={search} onChange={(event) => setSearch(event.target.value)} />
        {linkedPages.filter((item) => item.ocr_languages.includes('vi')).map((item) => (
          <label key={item.id}>
            <input type="checkbox" checked={visible.includes(item.id)} onChange={(event) =>
              setVisiblePages(event.target.checked ? [...visible, item.id] : visible.filter((id) => id !== item.id))} />
            Quốc ngữ trang {item.number}
          </label>
        ))}
      </div>
      <div className="linked-alignment-grid linked-alignment-head"><span>Hán Nôm · trang {page.number}</span><span>Quốc ngữ đã ghép</span></div>
      {pairedRows.map(({ row, index }) => (
        <div className="linked-alignment-grid linked-alignment-pair" key={row.id}>
          <div className="linked-alignment-source">
            <small>{row.sentence_id}</small>
            <span className="han-text">{row.source}</span>
          </div>
          <div className="linked-alignment-target"
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => { event.preventDefault(); if (dragged) assign(dragged, index); }}>
            {row.target && <button type="button" draggable
              onDragStart={() => setDragged({ rowId: row.id, target: { text: row.target, pageId: row.target_page_id || null, lineIndex: row.target_line_index ?? null } })}
              onClick={() => setSelected({ rowId: row.id, target: { text: row.target, pageId: row.target_page_id || null, lineIndex: row.target_line_index ?? null } })}>
              {row.target} <small>· trang {pages.find((item) => item.id === row.target_page_id)?.number || page.number}</small>
            </button>}
            {selected && <button type="button" className="secondary-button" onClick={() => assign(selected, index)}>Gắn vào dòng {index + 1}</button>}
          </div>
        </div>
      ))}
      {!pairedRows.length && <p>Chưa có dòng nào được ghép.</p>}
      {(!!unmatchedSource.length || !!unassigned.length) && <div className="linked-alignment-pool">
        <strong>Dòng riêng từng trang để ghép thêm · Hán Nôm {unmatchedSource.length} · Quốc ngữ {unassigned.length}</strong>
        {!!unmatchedSource.length && <div className="linked-alignment-column">
          <small>Hán Nôm · trang {page.number}</small>
          {unmatchedSource.map(({ row, index }) => <div className="linked-alignment-unmatched" key={row.id}
            onDragOver={(event) => event.preventDefault()}
            onDrop={(event) => { event.preventDefault(); if (dragged) assign(dragged, index); }}>
            <span className="han-text">{row.source}</span>
            {selected && <button type="button" className="secondary-button" onClick={() => assign(selected, index)}>Gắn dòng đã chọn</button>}
          </div>)}
        </div>}
        {linkedPages.filter((item) => visible.includes(item.id) && item.ocr_languages.includes('vi')).map((item) => {
          const matches = unassigned.filter((target) => target.pageId === item.id &&
            (!search || target.text.toLocaleLowerCase('vi').includes(search.toLocaleLowerCase('vi')) || String(item.number).includes(search)));
          return matches.length ? <div key={item.id} className="linked-alignment-column"><small>Trang {item.number}</small>
            {matches.map((target) => <button type="button" key={target.lineIndex} draggable
              onDragStart={() => setDragged({ target })}
              onClick={() => setSelected({ target })}>{target.text}</button>)}
          </div> : null;
        })}
      </div>}
    </section>
  );
}
