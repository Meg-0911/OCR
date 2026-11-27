import type { Box, BoxReference, Page, QuickCard } from '../types';
import { sliceReferences } from './alignmentReferences.ts';

export type ReviewSide = 'source' | 'target';
type Point = [number, number];
export type ImageRegion = { points: Point[]; approximate: boolean };

function segment(box: Box, start: number, end: number, vertical: boolean): ImageRegion {
  const size = Array.from(box.transcription).length;
  if (!size || start === 0 && end === size) return { points: box.points, approximate: false };
  const left = Math.max(0, Math.min(1, start / size));
  const right = Math.max(left, Math.min(1, end / size));
  const [tl, tr, br, bl] = box.points;
  const lerp = (a: Point, b: Point, t: number): Point => [a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t];
  return { approximate: true, points: vertical
    ? [lerp(tl, bl, left), lerp(tr, br, left), lerp(tr, br, right), lerp(tl, bl, right)]
    : [lerp(tl, tr, left), lerp(tl, tr, right), lerp(bl, br, right), lerp(bl, br, left)] };
}

export function reviewImageRegions(card: QuickCard, page: Page, side: ReviewSide) {
  const boxes = side === 'source' ? page.boxes : page.vi_boxes;
  const byId = new Map(boxes.map(box => [box.id, box]));
  let refs: BoxReference[] = (card.row[`${side}_refs`] || []).filter(ref => byId.has(ref.box_id));
  if (!refs.length) {
    let assigned = boxes.filter(box => box.alignment_id === card.row_id);
    if (!assigned.length) {
      const matches = boxes.filter(box => box.transcription.trim() === card.row[side].trim());
      // Never use a line index on another page, or choose between repeated phrases by guesswork.
      if (matches.length === 1 && card.row[side].trim()) assigned = matches;
    }
    if (assigned.map(box => box.transcription).join('').trim() === card.row[side].trim())
      refs = assigned.map(box => ({ box_id: box.id, start: 0, end: Array.from(box.transcription).length }));
  }
  const valid = refs.filter(ref => ref.start >= 0 && ref.end > ref.start && ref.end <= Array.from(byId.get(ref.box_id)!.transcription).length);
  const line = [...new Set(refs.map(ref => ref.box_id))].map(id => ({ points: byId.get(id)!.points, approximate: false }));
  const linkedText = valid.map(ref => Array.from(byId.get(ref.box_id)!.transcription).slice(ref.start, ref.end).join('')).join('');
  // Corrected text with outdated offsets may still identify a line, but cannot locate a word safely.
  const canLocateWord = linkedText === card.row[side] && valid.length === refs.length;
  const [start, end] = card.ranges?.[side] || [0, Array.from(card.row[side]).length];
  const selected = canLocateWord && card.index !== null ? sliceReferences(valid, start, end) : valid;
  const focus = !canLocateWord ? line : selected.map(ref => {
    const box = byId.get(ref.box_id)!;
    const vertical = side === 'source' && (box.box_axis === 'vertical' || !box.box_axis && page.reading_direction === 1);
    return segment(box, ref.start, ref.end, vertical);
  });
  return { line, focus, canLocateWord, approximate: focus.some(region => region.approximate) };
}

export function imageRegionBounds(regions: ImageRegion[], page: Pick<Page, 'width' | 'height'>, padding = 16) {
  const points = regions.flatMap(region => region.points);
  if (!points.length) return [0, 0, page.width, page.height];
  const x = Math.max(0, Math.min(...points.map(p => p[0])) - padding);
  const y = Math.max(0, Math.min(...points.map(p => p[1])) - padding);
  const right = Math.min(page.width, Math.max(...points.map(p => p[0])) + padding);
  const bottom = Math.min(page.height, Math.max(...points.map(p => p[1])) + padding);
  return [x, y, Math.max(1, right - x), Math.max(1, bottom - y)];
}
