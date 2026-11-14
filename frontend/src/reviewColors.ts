import type { Alignment, Box, ReviewKind } from './types';

export function boxReviewKindAt(box: Box, characterIndex: number): ReviewKind {
  const range = [...(box.review_marks || [])].reverse().find((item) =>
    item.start <= characterIndex && characterIndex < item.end,
  );
  return range?.kind || box.review_kind || 'match';
}

export function boxesInReviewOrder(boxes: Box[]) {
  return boxes.every((box) => box.review_order != null)
    ? [...boxes].sort((a, b) => a.review_order! - b.review_order!)
    : boxes;
}

export function reviewColorsForText(
  text: string,
  boxes: Box[],
  side: 'source' | 'target',
): ReviewKind[] {
  const characters = Array.from(text);
  const colors: ReviewKind[] = Array(characters.length).fill('match');
  if (side === 'source') {
    const boxColors = boxesInReviewOrder(boxes).flatMap((box) =>
      Array.from(box.transcription)
        .map((character, index) => ({ character, index }))
        .filter(({ character }) => /[\p{Script=Han}\p{Co}]|□/u.test(character))
        .map(({ index }) => boxReviewKindAt(box, index)),
    );
    let glyphIndex = 0;
    characters.forEach((character, characterIndex) => {
      if (!/[\p{Script=Han}\p{Co}]|□/u.test(character)) return;
      colors[characterIndex] = boxColors[glyphIndex] || 'match';
      glyphIndex++;
    });
    return colors;
  }

  const orderedBoxes = boxesInReviewOrder(boxes);
  let wordIndex = 0;
  for (const match of text.matchAll(/\S+/gu)) {
    if (!/[\p{L}\p{N}]/u.test(match[0])) continue;
    const start = Array.from(text.slice(0, match.index ?? 0)).length;
    const end = start + Array.from(match[0]).length;
    const box = orderedBoxes[wordIndex];
    colors.fill(box ? boxReviewKindAt(box, 0) : 'match', start, end);
    wordIndex++;
  }
  return colors;
}

export function reviewColorsForAlignmentRows(
  rows: Alignment[],
  boxes: Box[],
  side: 'source' | 'target',
): Map<string, ReviewKind[]> {
  const separator = side === 'target' ? ' ' : '';
  const stream = rows.map((row) => row[side]).join(separator);
  const streamColors = reviewColorsForText(stream, boxes, side);
  const separatorLength = Array.from(separator).length;
  const result = new Map<string, ReviewKind[]>();
  let offset = 0;
  for (const row of rows) {
    const length = Array.from(row[side]).length;
    result.set(row.id, streamColors.slice(offset, offset + length));
    offset += length + separatorLength;
  }
  return result;
}
