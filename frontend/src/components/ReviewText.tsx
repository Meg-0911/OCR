import { memo, useMemo } from 'react';
import type { Alignment, Box, ReviewKind } from '../types';
import { reviewColorsForText } from '../reviewColors';

const emptyBoxes: Box[] = [];

export default memo(function ReviewText({ text, boxes = emptyBoxes, side = 'source', colors, direction = 2, rows }: {
  text: string; boxes?: Box[]; side?: 'source' | 'target'; colors?: ReviewKind[]; direction?: 1 | 2; rows?: Alignment[];
}) {
  const runs = useMemo(() => {
    const kinds = colors || reviewColorsForText(text, boxes, side, direction, rows);
    const result: { kind: ReviewKind; text: string[] }[] = [];
    Array.from(text).forEach((char, index) => {
      const kind = kinds[index] || 'match';
      const previous = result.at(-1);
      if (previous?.kind === kind) previous.text.push(char);
      else result.push({ kind, text: [char] });
    });
    return result;
  }, [text, boxes, side, colors, direction, rows]);
  return <>{runs.map((run, index) =>
    <span key={index} className={`review-${run.kind}`}>{run.text.join('')}</span>)}</>;
});
