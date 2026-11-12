import type { Alignment, Page } from '../types';

export type Target = { text: string; pageId: string | null; lineIndex: number | null };
export type Dragged = { rowId?: string; target: Target };

export function linkedLines(text: string) {
  return text.split(/\r?\n/u).map((line) => line.trim()).filter(Boolean);
}

export function defaultLinkedRows(page: Page, bookName: string, targets: Target[], id: () => string): Alignment[] {
  const sourceLines = linkedLines(page.source_text || page.boxes.map((box) => box.transcription).join('\n'));
  const prefix = `${bookName}.${String(page.number).padStart(3, '0')}.`;
  return sourceLines.map((source, index) => ({
    id: id(),
    sentence_id: `${prefix}${index + 1}`,
    source,
    target: targets[index]?.text || '',
    source_page_id: page.id,
    source_line_index: index,
    target_page_id: targets[index]?.pageId || null,
    target_line_index: targets[index]?.lineIndex ?? null,
    page_linked: true,
    reviewed: false,
    marks: [],
  }));
}

export function reorderLinkedTargets(pageRows: Alignment[], item: Dragged, destination: number): Alignment[] {
  const assignments: Target[] = pageRows.map((row) => ({
    text: row.target,
    pageId: row.target_page_id || null,
    lineIndex: row.target_line_index ?? null,
  }));
  const previous = item.rowId ? pageRows.findIndex((row) => row.id === item.rowId) : -1;
  if (previous >= 0) assignments.splice(previous, 1);
  assignments.splice(destination, 0, item.target);
  return pageRows.map((row, index) => {
    const target = assignments[index] || { text: '', pageId: null, lineIndex: null };
    if (row.target === target.text && row.target_page_id === target.pageId && row.target_line_index === target.lineIndex) return row;
    return { ...row, target: target.text, target_page_id: target.pageId,
      target_line_index: target.lineIndex, reviewed: false, marks: [] };
  });
}
