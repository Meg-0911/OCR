import { useEffect, useRef, useState, type PointerEvent } from 'react';
import { CircleHelp } from 'lucide-react';
import type { Box, Page } from '../types';

function bounds(box: Box) {
  const xs = box.points.map((p) => p[0]),
    ys = box.points.map((p) => p[1]);
  return {
    x: Math.min(...xs),
    y: Math.min(...ys),
    width: Math.max(...xs) - Math.min(...xs),
    height: Math.max(...ys) - Math.min(...ys),
  };
}

type Drag = {
  kind: 'move' | 'corner' | 'draw' | 'select-area';
  start: [number, number];
  box?: Box;
  corner?: number;
};
export default function ManuscriptViewer({
  page,
  boxes,
  boxNumber,
  selected,
  setSelected,
  showBoxes,
  tool,
  zoom,
  onBoxes,
  onDrawn,
  allowAltDraw = false,
  selectedIds = [],
  onSelectionChange,
  readOnly = false,
  showFullPageRegion = false,
  onDeleteSelected,
}: {
  page: Page;
  boxes: Box[];
  boxNumber?: (box: Box, index: number) => number | string;
  selected: string | null;
  setSelected: (id: string | null) => void;
  showBoxes: boolean;
  tool: 'select' | 'draw';
  zoom: number;
  onBoxes: (boxes: Box[]) => void;
  onDrawn: () => void;
  allowAltDraw?: boolean;
  selectedIds?: string[];
  onSelectionChange?: (ids: string[]) => void;
  readOnly?: boolean;
  showFullPageRegion?: boolean;
  onDeleteSelected?: () => void;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<Drag | null>(null);
  const [preview, setPreview] = useState<Box | null>(null);
  const [imageError, setImageError] = useState(false);
  useEffect(() => {
    setImageError(false);
  }, [page.id]);
  useEffect(() => {
    if (!selected || !svg.current) return;
    const frame = requestAnimationFrame(() => {
      if (drag.current) return;
      const box = Array.from(
        svg.current?.querySelectorAll<SVGPolygonElement>('[data-box]') || [],
      ).find((element) => element.dataset.box === selected);
      box?.scrollIntoView({ block: 'center', inline: 'center', behavior: 'smooth' });
    });
    return () => cancelAnimationFrame(frame);
  }, [selected, page.id, zoom]);
  function position(event: PointerEvent<SVGSVGElement>): [number, number] {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(page.width, ((event.clientX - rect.left) / rect.width) * page.width)),
      Math.max(0, Math.min(page.height, ((event.clientY - rect.top) / rect.height) * page.height)),
    ];
  }
  function start(event: PointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    if (readOnly && tool === 'draw') return;
    const point = position(event);
    const target = event.target as SVGElement;
    const box = boxes.find((b) => b.id === target.dataset.box);
    if (allowAltDraw ? event.altKey && !readOnly : tool === 'draw' && (!box || event.shiftKey))
      drag.current = { kind: 'draw', start: point };
    else if (box) {
      setSelected(box.id);
      onSelectionChange?.([box.id]);
      if (onDeleteSelected) event.currentTarget.focus();
      if (readOnly) return;
      drag.current = {
        kind: target.dataset.corner !== undefined ? 'corner' : 'move',
        start: point,
        box: structuredClone(box),
        corner: Number(target.dataset.corner),
      };
    } else {
      setSelected(null);
      if (!allowAltDraw || readOnly) return;
      onSelectionChange?.([]);
      drag.current = { kind: 'select-area', start: point };
    }
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event: PointerEvent<SVGSVGElement>) {
    const state = drag.current;
    if (!state) return;
    const point = position(event);
    if (state.kind === 'draw' || state.kind === 'select-area') {
      const x = Math.min(state.start[0], point[0]),
        y = Math.min(state.start[1], point[1]);
      const right = Math.max(state.start[0], point[0]),
        bottom = Math.max(state.start[1], point[1]);
      setPreview({
        id: state.kind === 'draw' ? 'drawing' : 'selecting',
        transcription: '',
        points: [
          [x, y],
          [right, y],
          [right, bottom],
          [x, bottom],
        ],
      });
    } else if (state.box) {
      const original = state.box;
      if (state.kind === 'move') {
        const b = bounds(original);
        const dx = Math.max(-b.x, Math.min(page.width - b.x - b.width, point[0] - state.start[0]));
        const dy = Math.max(
          -b.y,
          Math.min(page.height - b.y - b.height, point[1] - state.start[1]),
        );
        setPreview({ ...original, points: original.points.map(([x, y]) => [x + dx, y + dy]) });
      } else {
        // Resize axis-aligned boxes through the opposite corner; preserve a nonzero area.
        const opposite = original.points[((state.corner || 0) + 2) % 4];
        if (Math.abs(point[0] - opposite[0]) < 8 || Math.abs(point[1] - opposite[1]) < 8) return;
        const x = Math.min(point[0], opposite[0]),
          y = Math.min(point[1], opposite[1]),
          right = Math.max(point[0], opposite[0]),
          bottom = Math.max(point[1], opposite[1]);
        setPreview({
          ...original,
          points: [
            [x, y],
            [right, y],
            [right, bottom],
            [x, bottom],
          ],
        });
      }
    }
  }
  function end(event: PointerEvent<SVGSVGElement>) {
    if (!drag.current) return;
    if (preview) {
      const b = bounds(preview);
      if (drag.current.kind === 'select-area' && b.width > 8 && b.height > 8) {
        const ids = boxes.filter((box) => {
          const item = bounds(box);
          return item.x < b.x + b.width && item.x + item.width > b.x &&
            item.y < b.y + b.height && item.y + item.height > b.y;
        }).map((box) => box.id);
        setSelected(ids[0] || null);
        onSelectionChange?.(ids);
      } else if (drag.current.kind === 'draw' && b.width > 8 && b.height > 8) {
        const created = { ...preview, id: crypto.randomUUID() };
        onBoxes([...boxes, created]);
        setSelected(created.id);
        onSelectionChange?.([created.id]);
        onDrawn();
      } else if ((drag.current.kind === 'move' || drag.current.kind === 'corner') &&
          drag.current.box && JSON.stringify(preview.points) !== JSON.stringify(drag.current.box.points))
        onBoxes(boxes.map((box) => (box.id === preview.id ? preview : box)));
    }
    drag.current = null;
    setPreview(null);
    if (event.currentTarget.hasPointerCapture(event.pointerId))
      event.currentTarget.releasePointerCapture(event.pointerId);
  }
  const rendered = boxes.map((box) => (preview?.id === box.id ? preview : box));
  if (preview?.id === 'drawing') rendered.push(preview);
  return (
    <div className={`manuscript-stage ${tool === 'draw' ? 'drawing' : ''}`}>
      <div className="manuscript-wrapper" style={{ width: `${zoom}%` }}>
        {imageError ? (
          <div className="image-error">
            <CircleHelp size={25} />
            <p>Không tải được bản quét.</p>
            <button className="secondary-button" onClick={() => setImageError(false)}>
              Thử lại
            </button>
          </div>
        ) : (
          <svg
            ref={svg}
            viewBox={`0 0 ${page.width} ${page.height}`}
            className="manuscript"
            role="img"
            tabIndex={onDeleteSelected ? 0 : undefined}
            aria-label={`Bản quét trang ${page.number} với ${boxes.length} vùng chữ`}
            onKeyDown={(event) => {
              if (event.key === 'Delete' && onDeleteSelected) {
                event.preventDefault();
                event.stopPropagation();
                onDeleteSelected();
              }
            }}
            onPointerDown={start}
            onPointerMove={move}
            onPointerUp={end}
            onPointerCancel={() => {
              drag.current = null;
              setPreview(null);
            }}
          >
            <image
              href={page.image_url}
              width={page.width}
              height={page.height}
              onError={() => setImageError(true)}
            />
            {showBoxes && showFullPageRegion && (
              <rect
                x={2}
                y={2}
                width={page.width - 4}
                height={page.height - 4}
                className="reading-region-outline"
                pointerEvents="none"
              />
            )}
            {showBoxes &&
              rendered.map((box, index) => {
                const b = bounds(box),
                  active = selected === box.id;
                const number = boxNumber?.(box, index) ?? index + 1;
                const label = typeof number === 'number' ? String(number).padStart(2, '0') : number;
                return (
                  <g key={box.id}>
                    <polygon
                      data-box={box.id}
                      points={box.points.map((p) => p.join(',')).join(' ')}
                      className={`bounding-box ${box.box_axis ? `axis-${box.box_axis}` : ''} ${active || selectedIds.includes(box.id) ? 'active' : ''}`}
                      strokeWidth={active ? 3 : 2}
                    />
                    <g pointerEvents="none">
                      <rect
                        x={b.x}
                        y={Math.max(0, b.y - 24)}
                        width={29}
                        height={24}
                        rx={3}
                        fill={box.box_axis === 'vertical' ? '#995b25' : box.box_axis === 'horizontal' ? '#345f90' : active ? '#234d42' : '#68836f'}
                      />
                      <text
                        x={b.x + 14.5}
                        y={Math.max(0, b.y - 24) + 17}
                        fill="white"
                        fontSize={14}
                        textAnchor="middle"
                        fontFamily="sans-serif"
                      >
                        {label}
                      </text>
                    </g>
                    {active &&
                      !readOnly &&
                      box.points.map(([x, y], corner) => (
                        <rect
                          key={corner}
                          data-box={box.id}
                          data-corner={corner}
                          x={x - 6}
                          y={y - 6}
                          width={12}
                          height={12}
                          fill="white"
                          stroke="#234d42"
                          strokeWidth={2}
                          className="resize-handle"
                        />
                      ))}
                  </g>
                );
              })}
            {preview?.id === 'selecting' && (
              <rect
                x={bounds(preview).x}
                y={bounds(preview).y}
                width={bounds(preview).width}
                height={bounds(preview).height}
                fill="rgba(35, 77, 66, .12)"
                stroke="#234d42"
                strokeDasharray="8 5"
                pointerEvents="none"
              />
            )}
          </svg>
        )}
      </div>
    </div>
  );
}
