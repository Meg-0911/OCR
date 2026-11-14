import type { Alignment, Box } from '../types';

export function characterCount(text: string) {
  return Array.from(text.normalize('NFC').replace(/[\p{P}\s]/gu, '')).length;
}

export function allocateAlignmentOcrBoxes(ocrBoxes: Box[], alignments: Alignment[], granularity: 'character' | 'phrase' | null = 'character') {
  const ordered = ocrBoxes.every((box) => box.review_order != null)
    ? [...ocrBoxes].sort((a, b) => a.review_order! - b.review_order!)
    : ocrBoxes;
  const matches = new Map<string, Box[]>();
  if (granularity === 'phrase') {
    const used = new Set<number>();
    for (const row of alignments) {
      const normalized = row.source.replace(/\s/gu, '');
      const index = row.source_line_index != null &&
        ordered[row.source_line_index]?.transcription.replace(/\s/gu, '') === normalized
        ? row.source_line_index
        : ordered.findIndex((box, position) => !used.has(position) &&
          box.transcription.replace(/\s/gu, '') === normalized);
      if (index >= 0 && !used.has(index)) {
        matches.set(row.id, [ordered[index]]);
        used.add(index);
      }
    }
    return matches;
  }
  const stream: { character: string; boxIndex: number }[] = [];
  ordered.forEach((box, boxIndex) => {
    for (const character of box.transcription.normalize('NFC').replace(/[\p{P}\s]/gu, ''))
      stream.push({ character, boxIndex });
  });
  let streamCursor = 0;
  let boxCursor = 0;
  for (const row of alignments) {
    const expected = Array.from(row.source.normalize('NFC').replace(/[\p{P}\s]/gu, ''));
    if (!expected.length) continue;
    const exactAtCursor = expected.every((character, offset) =>
      stream[streamCursor + offset]?.character === character);
    if (exactAtCursor) {
      const matched = stream.slice(streamCursor, streamCursor + expected.length);
      const firstBox = matched[0].boxIndex;
      const lastBox = matched.at(-1)!.boxIndex;
      matches.set(row.id, ordered.slice(firstBox, lastBox + 1));
      streamCursor += expected.length;
      boxCursor = lastBox + 1;
      continue;
    }

    // Ignore punctuation-only boxes when OCR text is available. If OCR text is
    // blank or no longer matches the corrected source, fall back to box counts.
    if (streamCursor + expected.length <= stream.length) {
      const matched = stream.slice(streamCursor, streamCursor + expected.length);
      const firstBox = matched[0].boxIndex;
      const lastBox = matched.at(-1)!.boxIndex;
      matches.set(row.id, ordered.slice(firstBox, lastBox + 1));
      streamCursor += expected.length;
      boxCursor = lastBox + 1;
      continue;
    }

    const count = characterCount(row.source);
    if (!count || boxCursor + count > ordered.length) continue;
    matches.set(row.id, ordered.slice(boxCursor, boxCursor + count));
    boxCursor += count;
    while (streamCursor < stream.length && stream[streamCursor].boxIndex < boxCursor) streamCursor++;
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
