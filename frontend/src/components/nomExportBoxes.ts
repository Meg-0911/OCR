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
  if (boxes.length && boxes.every((box) => box.export_group)) {
    const groups = new Map<string, Box[]>();
    for (const box of boxes) {
      const group = box.export_group!;
      groups.set(group, [...(groups.get(group) || []), box]);
    }
    return [...groups.entries()]
      .sort(([, a], [, b]) => (a[0].export_order || 0) - (b[0].export_order || 0))
      .map(([group, members]) => {
        const xs = members.flatMap((box) => box.points.map((point) => point[0]));
        const ys = members.flatMap((box) => box.points.map((point) => point[1]));
        const ordered = [...members].sort(
          (a, b) => (a.export_character_order || 0) - (b.export_character_order || 0),
        );
        return {
          ...ordered[0],
          id: group,
          export_group: group,
          source_ids: ordered.map((box) => box.id),
          transcription: ordered.map((box) => box.transcription).join(''),
          points: [
            [Math.min(...xs), Math.min(...ys)],
            [Math.max(...xs), Math.min(...ys)],
            [Math.max(...xs), Math.max(...ys)],
            [Math.min(...xs), Math.max(...ys)],
          ],
        };
      });
  }
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
      export_group: run[0].id,
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
  return output.map((box, index) => ({ ...box, export_order: box.export_order ?? index + 1 }));
}

export function updateNomExportBoxes(
  original: Box[],
  updated: Box[],
  direction: 1 | 2,
  width: number,
  height: number,
): Box[] {
  const previousGroups = nomExportBoxes(original, direction, width, height);
  const normalized = new Map<string, Box>();
  for (const group of previousGroups) {
    group.source_ids.forEach((id, index) => {
      const box = original.find((item) => item.id === id);
      if (box)
        normalized.set(id, {
          ...box,
          export_group: group.export_group,
          export_order: group.export_order ?? previousGroups.indexOf(group) + 1,
          export_character_order: index,
        });
    });
  }
  const next = new Map(normalized);
  for (const group of previousGroups) {
    const changed = updated.find((box) => box.export_group === group.export_group);
    if (!changed) {
      for (const id of group.source_ids) next.delete(id);
      continue;
    }
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
    if (previousGroups.some((group) => group.export_group === box.export_group)) continue;
    if (!next.has(box.id)) {
      const nextOrder = Math.max(0, ...previousGroups.map((group) => group.export_order || 0)) + 1;
      next.set(box.id, {
        id: box.id,
        transcription: '',
        points: box.points,
        export_group: box.id,
        export_order: nextOrder,
        export_character_order: 0,
      });
    }
  }
  return [...next.values()];
}

export function updateExportOrders(
  boxes: Box[],
  orders: Record<string, number>,
  direction: 1 | 2,
  width: number,
  height: number,
): Box[] {
  const groups = nomExportBoxes(boxes, direction, width, height);
  const sourceGroups = new Map(
    groups.flatMap((group) => group.source_ids.map((id) => [id, group])),
  );
  const normalized = boxes.map((box) => {
    const group = sourceGroups.get(box.id);
    if (!group) return box;
    const groupId = group.export_group || group.id;
    return {
      ...box,
      export_group: groupId,
      export_order: orders[groupId] ?? group.export_order ?? groups.indexOf(group) + 1,
      export_character_order: group.source_ids.indexOf(box.id),
    };
  });
  return normalized.map((box) =>
    box.export_group && orders[box.export_group] !== undefined
      ? { ...box, export_order: orders[box.export_group] }
      : box,
  );
}
