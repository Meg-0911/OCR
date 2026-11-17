import type { Alignment, Box, ReviewKind } from './types';
import { groupCharacterBoxes } from './components/boxText.ts';

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

export function sourceGlyphReviews(boxes: Box[]) {
  return boxesInReviewOrder(boxes).flatMap((box) => Array.from(box.transcription)
    .flatMap((character, index) => /[\p{Script=Han}\p{Co}]|□/u.test(character)
      ? [{ box, index, kind: boxReviewKindAt(box, index) }] : []));
}

function reviewGroups(boxes: Box[], direction: 1 | 2) {
  const ordered = boxesInReviewOrder(boxes);
  if (ordered.length && ordered.every((box) => box.export_group)) {
    const groups = new Map<string, Box[]>();
    for (const box of ordered) {
      const group = groups.get(box.export_group!);
      if (group) group.push(box);
      else groups.set(box.export_group!, [box]);
    }
    return [...groups.values()];
  }
  return ordered.some((box) => Array.from(box.transcription).length > 1)
    ? ordered.map((box) => [box]) : groupCharacterBoxes(ordered, direction);
}

export function targetGlyphReviews(text: string, boxes: Box[], direction: 1 | 2 = 2, rows?: Alignment[]) {
  let groups: Box[][] | undefined;
  if (rows?.length && rows.map((row) => row.target).join('\n') === text) {
    const assignedBoxes = new Map<string, Box[]>();
    for (const box of boxes) {
      if (!box.alignment_id) continue;
      const assigned = assignedBoxes.get(box.alignment_id);
      if (assigned) assigned.push(box);
      else assignedBoxes.set(box.alignment_id, [box]);
    }
    return rows.flatMap((row) => {
      let assigned = assignedBoxes.get(row.id) || [];
      if (!assigned.length && row.source && row.source_line_index != null) {
        groups ??= reviewGroups(boxes, direction);
        assigned = groups[row.source_line_index] || [];
      }
      const glyphs = sourceGlyphReviews(assigned);
      return (row.target.match(/\S+/gu) || []).filter((word) => /[\p{L}\p{N}]/u.test(word)).map((_, index) => glyphs[index]);
    });
  }
  const lineGroups = reviewGroups(boxes, direction);
  const lines = text.split('\n');
  if (lines.length === lineGroups.length) {
    return lines.flatMap((line, index) => {
      const glyphs = sourceGlyphReviews(lineGroups[index]);
      return (line.match(/\S+/gu) || []).filter((word) => /[\p{L}\p{N}]/u.test(word)).map((_, wordIndex) => glyphs[wordIndex]);
    });
  }
  return sourceGlyphReviews(boxes);
}

export function reviewColorsForText(
  text: string,
  boxes: Box[],
  side: 'source' | 'target',
  direction: 1 | 2 = 2,
  rows?: Alignment[],
  ignoreNumericWords = false,
): ReviewKind[] {
  if (rows?.length && rows.map((row) => row[side]).join('\n') === text) {
    const rowColors = reviewColorsForAlignmentRows(rows, boxes, side, direction, ignoreNumericWords);
    return rows.flatMap((row, index) => [
      ...withReviewMarks(row[side], rowColors.get(row.id) || [], row.marks, side),
      ...(index < rows.length - 1 ? ['match' as ReviewKind] : []),
    ]);
  }
  const characters = Array.from(text);
  const colors: ReviewKind[] = Array(characters.length).fill('match');
  if (side === 'source') {
    const boxColors = sourceGlyphReviews(boxes).map((glyph) => glyph.kind);
    let glyphIndex = 0;
    characters.forEach((character, characterIndex) => {
      if (!/[\p{Script=Han}\p{Co}]|□/u.test(character)) return;
      colors[characterIndex] = boxColors[glyphIndex] || 'match';
      glyphIndex++;
    });
    return colors;
  }

  const glyphs = sourceGlyphReviews(boxes);
  const ordered = boxesInReviewOrder(boxes);
  const groups = reviewGroups(boxes, direction);
  const lines = text.split('\n');
  if (lines.length > 1 && lines.length === groups.length) {
    let offset = 0;
    lines.forEach((line, index) => {
      const lineColors = reviewColorsForText(line, groups[index], 'target', direction, undefined, ignoreNumericWords);
      colors.splice(offset, lineColors.length, ...lineColors);
      offset += Array.from(line).length + 1;
    });
    return colors;
  }
  let wordIndex = 0;
  for (const match of text.matchAll(/\S+/gu)) {
    if (!(ignoreNumericWords ? /\p{L}/u : /[\p{L}\p{N}]/u).test(match[0])) continue;
    const start = Array.from(text.slice(0, match.index ?? 0)).length;
    const end = start + Array.from(match[0]).length;
    colors.fill(glyphs[wordIndex]?.kind || (!glyphs.length && ordered[wordIndex] ? boxReviewKindAt(ordered[wordIndex], 0) : 'match'), start, end);
    wordIndex++;
  }
  return colors;
}

export function reviewColorsForLines(text: string, boxes: Box[], side: 'source' | 'target', direction: 1 | 2 = 2, rows?: Alignment[]) {
  text = text.replace(/\r\n/gu, '\n');
  const colors = reviewColorsForText(text, boxes, side, direction, rows);
  let offset = 0;
  return text.split(/\r?\n/u).flatMap((line) => {
    const length = Array.from(line).length;
    const lineColors = colors.slice(offset, offset + length);
    offset += length + 1;
    return line.trim() ? [lineColors] : [];
  });
}

export function reviewColorsForAlignmentRows(
  rows: Alignment[],
  boxes: Box[],
  side: 'source' | 'target',
  direction: 1 | 2 = 2,
  ignoreNumericWords = false,
): Map<string, ReviewKind[]> {
  const orderedRows = [...rows].sort((a, b) => Number(a.sentence_id?.split('.').at(-1) || 0) - Number(b.sentence_id?.split('.').at(-1) || 0));
  let streamColors: ReviewKind[] | undefined;
  let glyphs: ReturnType<typeof sourceGlyphReviews> | undefined;
  let text: string | undefined;
  const result = new Map<string, ReviewKind[]>();
  let groups: Box[][] | undefined;
  const assignedBoxes = new Map<string, Box[]>();
  for (const box of boxes) {
    if (!box.alignment_id) continue;
    const assigned = assignedBoxes.get(box.alignment_id);
    if (assigned) assigned.push(box);
    else assignedBoxes.set(box.alignment_id, [box]);
  }
  let offset = 0;
  for (const row of orderedRows) {
    const length = Array.from(row.source).length;
    let assigned = assignedBoxes.get(row.id) || [];
    if (!assigned.length && row.source_line_index != null) {
      groups ??= reviewGroups(boxes, direction);
      assigned = groups[row.source_line_index] || [];
    }
    let colors: ReviewKind[];
    if (assigned.length) colors = reviewColorsForText(row.source, assigned, 'source');
    else if (row.source_page_id) {
      glyphs ??= sourceGlyphReviews(boxes);
      text ??= glyphs.map((glyph) => Array.from(glyph.box.transcription)[glyph.index]).join('');
      const wanted = Array.from(row.source).filter((char) => /[\p{Script=Han}\p{Co}]|□/u.test(char)).join('');
      const start = wanted ? text.indexOf(wanted) : -1;
      const at = start >= 0 && text.indexOf(wanted, start + 1) < 0 ? Array.from(text.slice(0, start)).length : -1;
      let cursor = 0;
      colors = Array.from(row.source).map((char) => /[\p{Script=Han}\p{Co}]|□/u.test(char)
        ? at < 0 ? 'unknown' : glyphs![at + cursor++]?.kind || 'unknown' : 'match');
    } else {
      if (row.review_colors?.source) colors = row.review_colors.source;
      else {
        streamColors ??= reviewColorsForText(orderedRows.map((item) => item.source).join(''), boxes, 'source');
        colors = streamColors.slice(offset, offset + length);
      }
    }
    if (side === 'source') result.set(row.id, colors);
    else {
      const glyphColors = Array.from(row.source).flatMap((char, index) =>
        /[\p{Script=Han}\p{Co}]|□/u.test(char) ? [colors[index]] : []);
      const targetColors: ReviewKind[] = Array(Array.from(row.target).length).fill('match');
      let wordIndex = 0;
      for (const match of row.target.matchAll(/\S+/gu)) {
        if (!(ignoreNumericWords ? /\p{L}/u : /[\p{L}\p{N}]/u).test(match[0])) continue;
        const start = Array.from(row.target.slice(0, match.index ?? 0)).length;
        targetColors.fill(glyphColors[wordIndex++] || 'match', start, start + Array.from(match[0]).length);
      }
      result.set(row.id, targetColors);
    }
    offset += length;
  }
  return result;
}

export function withReviewMarks(value: string, base: (ReviewKind | undefined)[], marks: Alignment['marks'], side: 'source' | 'target') {
  const kinds = Array.from(value).map((_, index) => base[index] || 'match');
  for (const mark of marks || []) kinds.fill(mark.kind, mark[`${side}_start`], mark[`${side}_end`]);
  return kinds;
}
