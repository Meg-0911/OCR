import type { ReviewKind } from './types';

// Clean the visible alignment text together with its colors. Removing a digit
// or punctuation must not move the red mark onto the next surviving character.
export function cleanAlignmentText(value: string, side: 'source' | 'target', colors: ReviewKind[] = []) {
  const lines: { characters: string[]; colors: ReviewKind[] }[] = [];
  let line = { characters: [] as string[], colors: [] as ReviewKind[] };
  let pendingSpace = false;
  const finishLine = () => {
    if (line.characters.length) lines.push(line);
    line = { characters: [], colors: [] };
    pendingSpace = false;
  };
  Array.from(value).forEach((character, index) => {
    if (character === '\r' || character === '\n') {
      finishLine();
      return;
    }
    if (/[\p{N}\p{P}\p{Cf}]/u.test(character)) return;
    if (/\s/u.test(character)) {
      if (side === 'target' && line.characters.length) pendingSpace = true;
      return;
    }
    if (/\p{Cc}/u.test(character)) return;
    if (pendingSpace) {
      line.characters.push(' ');
      line.colors.push('match');
      pendingSpace = false;
    }
    for (const cleaned of side === 'target' ? character.toLowerCase() : character) {
      line.characters.push(cleaned);
      line.colors.push(colors[index] || 'match');
    }
  });
  finishLine();
  return {
    text: lines.map((item) => item.characters.join('')).join('\n'),
    colors: lines.flatMap((item, index) => index ? ['match' as ReviewKind, ...item.colors] : item.colors),
  };
}
