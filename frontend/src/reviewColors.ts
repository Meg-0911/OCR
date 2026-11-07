import type { Box, ReviewKind } from './types';

export function reviewColorsForText(
  text: string,
  boxes: Box[],
  side: 'source' | 'target',
): ReviewKind[] {
  const characters = Array.from(text);
  const colors: ReviewKind[] = Array(characters.length).fill('match');
  if (side === 'source') {
    const boxColors = boxes.flatMap((box) =>
      Array.from(box.transcription)
        .filter((character) => /[\p{Script=Han}\p{Co}]|□/u.test(character))
        .map(() => box.review_kind || 'match'),
    );
    let glyphIndex = 0;
    characters.forEach((character, characterIndex) => {
      if (!/[\p{Script=Han}\p{Co}]|□/u.test(character)) return;
      colors[characterIndex] = boxColors[glyphIndex] || 'match';
      glyphIndex++;
    });
    return colors;
  }
  let wordIndex = 0;
  for (const match of text.matchAll(/\S+/gu)) {
    if (!/[\p{L}\p{N}]/u.test(match[0])) continue;
    const start = Array.from(text.slice(0, match.index ?? 0)).length;
    const end = start + Array.from(match[0]).length;
    colors.fill(boxes[wordIndex]?.review_kind || 'match', start, end);
    wordIndex++;
  }
  return colors;
}
