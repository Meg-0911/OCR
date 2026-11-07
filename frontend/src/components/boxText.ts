import type { Box } from '../types';

export function groupCharacterBoxes(boxes: Box[], direction: 1 | 2) {
  const axis = direction === 1 ? 0 : 1;
  const center = (box: Box) => box.points.reduce((sum, point) => sum + point[axis], 0) / box.points.length;
  const size = (box: Box) => Math.max(...box.points.map(point => point[axis])) - Math.min(...box.points.map(point => point[axis]));
  const groups: Box[][] = [];
  for (const box of [...boxes].sort((a, b) => direction === 1 ? center(b) - center(a) : center(a) - center(b))) {
    const row = groups.find(items => Math.abs(center(items[0]) - center(box)) < Math.max(size(items[0]), size(box)) * .5);
    if (row) row.push(box);
    else groups.push([box]);
  }
  return groups.map(row => row.sort((a, b) =>
    Math.min(...a.points.map(p => p[direction === 1 ? 1 : 0])) - Math.min(...b.points.map(p => p[direction === 1 ? 1 : 0]))));
}

export function replaceBoxText(boxes: Box[], text: string, id: string, value: string, direction: 1 | 2, han: boolean) {
  const next = boxes.map(box => box.id === id ? { ...box, transcription: value } : box);
  const lines = groupCharacterBoxes(boxes, direction);
  const currentFromBoxes = lines.map(row => row.map(box => box.transcription).join('')).join('');
  if (han && text.replace(/\s/g, '') === currentFromBoxes.replace(/\s/g, ''))
    return { boxes: next, text: groupCharacterBoxes(next, direction).map(row => row.map(box => box.transcription).join('')).join('\n') };
  let cursor = 0;
  for (const box of boxes) {
    const start = box.transcription ? text.indexOf(box.transcription, cursor) : -1;
    if (box.id === id) {
      if (start >= 0)
        return { boxes: next, text: text.slice(0, start) + value + text.slice(start + box.transcription.length) };
      // A merge or split can leave the page text with a different box boundary.
      // Use the selected box's placeholder rank instead of silently keeping □.
      if (han && text.includes('□') && box.transcription.includes('□')) {
        const readingOrder = lines.flat();
        const before = readingOrder.slice(0, readingOrder.findIndex(item => item.id === id));
        const rank = before.reduce((sum, item) => sum + [...item.transcription].filter(char => char === '□').length, 0);
        let position = -1;
        for (let i = 0; i <= rank; i++) position = text.indexOf('□', position + 1);
        if (position >= 0) {
          const unknowns = [...box.transcription].filter(char => char === '□').length;
          let end = position + 1;
          while (end < text.length && text[end] === '□' && end - position < unknowns) end++;
          return { boxes: next, text: text.slice(0, position) + value + text.slice(end) };
        }
      }
      return { boxes: next, text: !box.transcription ? [text, value].filter(Boolean).join('\n') : text };
    }
    if (start >= 0) cursor = start + box.transcription.length;
  }
  return { boxes: next, text };
}

// Locate repeated transcriptions in reading order, preserving independent page edits.
export function removeBoxAndText(boxes: Box[], text: string, id: string) {
  const remaining = boxes.filter((box) => box.id !== id);
  let cursor = 0;
  for (const box of boxes) {
    const start = box.transcription ? text.indexOf(box.transcription, cursor) : -1;
    if (box.id !== id) {
      if (start >= 0) cursor = start + box.transcription.length;
      continue;
    }
    if (start < 0) return { boxes: remaining, text };
    let from = start;
    let to = start + box.transcription.length;
    const startsLine = from === 0 || text[from - 1] === '\n';
    const endsLine = to === text.length || text[to] === '\n' || text.slice(to, to + 2) === '\r\n';
    if (startsLine && endsLine) {
      if (text.slice(to, to + 2) === '\r\n') to += 2;
      else if (text[to] === '\n') to += 1;
      else if (from > 0) from -= text.slice(from - 2, from) === '\r\n' ? 2 : 1;
    }
    return { boxes: remaining, text: text.slice(0, from) + text.slice(to) };
  }
  return { boxes, text };
}
