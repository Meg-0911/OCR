import type { Alignment, Box } from '../types';

export function characterCount(text: string) {
  return Array.from(text.normalize('NFC').replace(/[\p{P}\s]/gu, '')).length;
}

export function allocateAlignmentOcrBoxes(ocrBoxes: Box[], alignments: Alignment[]) {
  const ordered = ocrBoxes.every((box) => box.review_order != null)
    ? [...ocrBoxes].sort((a, b) => a.review_order! - b.review_order!)
    : ocrBoxes;
  const matches = new Map<string, Box[]>();
  let cursor = 0;

  for (const row of alignments) {
    const count = characterCount(row.source);
    if (!count) continue;
    if (cursor + count > ordered.length) break;
    matches.set(row.id, ordered.slice(cursor, cursor + count));
    cursor += count;
  }
  return matches;
}

export function boundsFromOcrBoxes(boxes: Box[], axis: 'vertical' | 'horizontal') {
  if (!boxes.length) return null;
  const x0 = Math.min(...boxes.flatMap((box) => box.points.map((point) => point[0])));
  const y0 = Math.min(...boxes.flatMap((box) => box.points.map((point) => point[1])));
  const x1 = Math.max(...boxes.flatMap((box) => box.points.map((point) => point[0])));
  const y1 = Math.max(...boxes.flatMap((box) => box.points.map((point) => point[1])));
  const transverse = axis === 'vertical' ? 0 : 1;
  const centers = boxes.map((box) => box.points.reduce((sum, point) => sum + point[transverse], 0) / box.points.length);
  const widths = boxes.map((box) => Math.max(...box.points.map((point) => point[transverse])) - Math.min(...box.points.map((point) => point[transverse])));
  if (Math.max(...centers) - Math.min(...centers) > Math.max(...widths) * .75) return null;
  return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]] as [number, number][];
}
