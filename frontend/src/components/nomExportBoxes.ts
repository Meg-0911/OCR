import type { Box } from '../types';

export type NomExportBox = Box & { source_ids: string[] };

function extent(box: Box, axis: number): [number, number] {
  const values = box.points.map((point) => point[axis]);
  return [Math.min(...values), Math.max(...values)];
}

function orderedBoxes(boxes: Box[], direction: 1 | 2, width?: number, height?: number): Box[] {
  if (width && height && width > height && boxes.length) {
    const middle = width / 2;
    const left = boxes.filter(
      (box) => box.points.reduce((sum, point) => sum + point[0], 0) / 4 < middle,
    );
    const right = boxes.filter((box) => !left.includes(box));
    if (left.length && right.length)
      return [...orderedBoxes(left, direction), ...orderedBoxes(right, direction)];
  }
  const axis = direction === 1 ? 0 : 1;
  const groups: Box[][] = [];
  for (const box of [...boxes].sort((a, b) => {
    const centerA = (extent(a, axis)[0] + extent(a, axis)[1]) / 2;
    const centerB = (extent(b, axis)[0] + extent(b, axis)[1]) / 2;
    return direction === 1 ? centerB - centerA : centerA - centerB;
  })) {
    const center = (item: Box) => (extent(item, axis)[0] + extent(item, axis)[1]) / 2;
    const size = (item: Box) => extent(item, axis)[1] - extent(item, axis)[0];
    const group = groups.find(
      (items) =>
        Math.abs(center(items[0]) - center(box)) < Math.max(size(items[0]), size(box)) * 0.5,
    );
    if (group) group.push(box);
    else groups.push([box]);
  }
  const travel = direction === 1 ? 1 : 0;
  return groups.flatMap((group) =>
    group.sort((a, b) => extent(a, travel)[0] - extent(b, travel)[0]),
  );
}

export function nomExportBoxes(
  boxes: Box[],
  direction: 1 | 2,
  width?: number,
  height?: number,
): NomExportBox[] {
  const ordered = orderedBoxes(boxes, direction, width, height);
  const axis = direction === 1 ? 0 : 1;
  const travel = direction === 1 ? 1 : 0;
  const sameLine = (a: Box, b: Box) => {
    const aExtent = extent(a, axis);
    const bExtent = extent(b, axis);
    const aSize = aExtent[1] - aExtent[0];
    const bSize = bExtent[1] - bExtent[0];
    return (
      Math.abs((aExtent[0] + aExtent[1] - bExtent[0] - bExtent[1]) / 2) <
      Math.max(aSize, bSize) * 0.5
    );
  };
  const output: NomExportBox[] = [];
  let run: Box[] = [];
  const flush = () => {
    if (!run.length) return;
    const xs = run.flatMap((box) => box.points.map((point) => point[0]));
    const ys = run.flatMap((box) => box.points.map((point) => point[1]));
    output.push({
      id: run[0].id,
      source_ids: run.map((box) => box.id),
      transcription: run.map((box) => box.transcription).join(''),
      points: [
        [Math.min(...xs), Math.min(...ys)],
        [Math.max(...xs), Math.min(...ys)],
        [Math.max(...xs), Math.max(...ys)],
        [Math.min(...xs), Math.max(...ys)],
      ],
    });
    run = [];
  };
  for (const box of ordered) {
    if (run.length) {
      const previous = run[run.length - 1];
      const previousExtent = extent(previous, travel);
      const currentExtent = extent(box, travel);
      const gap = currentExtent[0] - previousExtent[1];
      const span = Math.max(
        previousExtent[1] - previousExtent[0],
        currentExtent[1] - currentExtent[0],
      );
      if (
        previous.transcription.length > 1 ||
        box.transcription.length > 1 ||
        !previous.transcription.trim() ||
        !box.transcription.trim() ||
        !sameLine(run[0], box) ||
        gap > span * 0.75 ||
        /\s$/u.test(previous.transcription) ||
        /^\s/u.test(box.transcription)
      )
        flush();
    }
    run.push(box);
  }
  flush();
  return output;
}

export function updateNomExportBoxes(
  original: Box[],
  updated: Box[],
  direction: 1 | 2,
  width: number,
  height: number,
): Box[] {
  const previousGroups = nomExportBoxes(original, direction, width, height);
  const nextGroups = new Map(
    nomExportBoxes(updated, direction, width, height).map((box) => [box.id, box]),
  );
  const next = new Map(original.map((box) => [box.id, box]));
  for (const group of previousGroups) {
    const changed = nextGroups.get(group.id);
    if (!changed) continue;
    const moved = group.points.some(
      (point, index) =>
        point[0] !== changed.points[index][0] || point[1] !== changed.points[index][1],
    );
    if (!moved) continue;
    const oldLeft = group.points[0][0];
    const oldTop = group.points[0][1];
    const oldWidth = group.points[1][0] - oldLeft;
    const oldHeight = group.points[2][1] - oldTop;
    const newLeft = changed.points[0][0];
    const newTop = changed.points[0][1];
    const newWidth = changed.points[1][0] - newLeft;
    const newHeight = changed.points[2][1] - newTop;
    for (const id of group.source_ids) {
      const box = next.get(id);
      if (!box) continue;
      next.set(id, {
        ...box,
        points: box.points.map(([x, y]) => [
          newLeft + ((x - oldLeft) / oldWidth) * newWidth,
          newTop + ((y - oldTop) / oldHeight) * newHeight,
        ]),
      });
    }
  }
  for (const box of updated) {
    if (previousGroups.some((group) => group.id === box.id)) continue;
    if (!next.has(box.id)) next.set(box.id, { id: box.id, transcription: '', points: box.points });
  }
  return [...next.values()];
}
