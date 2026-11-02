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
  kind: 'move' | 'corner' | 'draw';
  start: [number, number];
  box?: Box;
  corner?: number;
};
export default function ManuscriptViewer({
  page,
  boxes,
  selected,
  setSelected,
  showBoxes,
  tool,
  zoom,
  onBoxes,
  onDrawn,
}: {
  page: Page;
  boxes: Box[];
  selected: string | null;
  setSelected: (id: string | null) => void;
  showBoxes: boolean;
  tool: 'select' | 'draw';
  zoom: number;
  onBoxes: (boxes: Box[]) => void;
  onDrawn: () => void;
}) {
  const svg = useRef<SVGSVGElement>(null);
  const drag = useRef<Drag | null>(null);
  const [preview, setPreview] = useState<Box | null>(null);
  const [imageError, setImageError] = useState(false);
  useEffect(() => {
    setImageError(false);
  }, [page.id]);
  function position(event: PointerEvent<SVGSVGElement>): [number, number] {
    const rect = event.currentTarget.getBoundingClientRect();
    return [
      Math.max(0, Math.min(page.width, ((event.clientX - rect.left) / rect.width) * page.width)),
      Math.max(0, Math.min(page.height, ((event.clientY - rect.top) / rect.height) * page.height)),
    ];
  }
  function start(event: PointerEvent<SVGSVGElement>) {
    if (event.button !== 0) return;
    const point = position(event);
    const target = event.target as SVGElement;
    const box = boxes.find((b) => b.id === target.dataset.box);
    if (tool === 'draw') drag.current = { kind: 'draw', start: point };
    else if (box) {
      setSelected(box.id);
      drag.current = {
        kind: target.dataset.corner !== undefined ? 'corner' : 'move',
        start: point,
        box: structuredClone(box),
        corner: Number(target.dataset.corner),
      };
    } else {
      setSelected(null);
      return;
    }
    event.currentTarget.setPointerCapture(event.pointerId);
  }
  function move(event: PointerEvent<SVGSVGElement>) {
    const state = drag.current;
    if (!state) return;
    const point = position(event);
    if (state.kind === 'draw') {
      const x = Math.min(state.start[0], point[0]),
        y = Math.min(state.start[1], point[1]);
      const right = Math.max(state.start[0], point[0]),
        bottom = Math.max(state.start[1], point[1]);
      setPreview({
        id: 'drawing',
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
      if (drag.current.kind === 'draw' && b.width > 8 && b.height > 8) {
        const created = { ...preview, id: crypto.randomUUID() };
        onBoxes([...boxes, created]);
        setSelected(created.id);
        onDrawn();
      } else if (drag.current.kind !== 'draw')
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
            aria-label={`Bản quét trang ${page.number} với ${boxes.length} vùng chữ`}
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
            {showBoxes &&
              rendered.map((box, index) => {
                const b = bounds(box),
                  active = selected === box.id;
                return (
                  <g key={box.id}>
                    <polygon
                      data-box={box.id}
                      points={box.points.map((p) => p.join(',')).join(' ')}
                      className={`bounding-box ${active ? 'active' : ''}`}
                      strokeWidth={active ? 3 : 2}
                    />
                    <g pointerEvents="none">
                      <rect
                        x={b.x}
                        y={Math.max(0, b.y - 24)}
                        width={29}
                        height={24}
                        rx={3}
                        fill={active ? '#234d42' : '#68836f'}
                      />
                      <text
                        x={b.x + 14.5}
                        y={Math.max(0, b.y - 24) + 17}
                        fill="white"
                        fontSize={14}
                        textAnchor="middle"
                        fontFamily="sans-serif"
                      >
                        {String(index + 1).padStart(2, '0')}
                      </text>
                    </g>
                    {active &&
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
          </svg>
        )}
      </div>
    </div>
  );
}
