import type { BoxReference } from '../types';

export function sliceReferences(refs: BoxReference[] | undefined, start: number, end: number): BoxReference[] {
  let cursor = 0;
  return (refs || []).flatMap((ref) => {
    const size = ref.end - ref.start;
    const left = Math.max(start - cursor, 0);
    const right = Math.min(end - cursor, size);
    cursor += size;
    return right > left ? [{ ...ref, start: ref.start + left, end: ref.start + right }] : [];
  });
}

export function referencesForPart(refs: BoxReference[] | undefined, original: string, part: string, last = false) {
  const index = last ? original.lastIndexOf(part) : original.indexOf(part);
  if (index < 0) return [];
  const start = Array.from(original.slice(0, index)).length;
  return sliceReferences(refs, start, start + Array.from(part).length);
}
