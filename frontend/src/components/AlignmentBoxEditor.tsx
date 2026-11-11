import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDown,
  ArrowUp,
  Maximize2,
  Minus,
  Plus,
  SquareDashedMousePointer,
  Trash2,
} from 'lucide-react';
import type { Alignment, Box, Page } from '../types';
import ManuscriptViewer from './ManuscriptViewer';

function withOrders(boxes: Box[], orders: Record<string, number>): Box[] {
  return boxes.map((box, index) => {
    const group = box.export_group || box.id;
    return {
      ...box,
      export_group: group,
      export_order: orders[group] ?? box.export_order ?? index + 1,
      export_character_order: box.export_character_order ?? 0,
    };
  });
}

export default function AlignmentBoxEditor({
  page,
  disabled,
  onBoxes,
  alignments,
  targetRow,
  targetAxis,
  targetRequestId,
}: {
  page: Page;
  disabled: boolean;
  onBoxes: (boxes: Box[]) => void;
  alignments: Alignment[];
  targetRow?: Alignment;
  targetAxis?: 'vertical' | 'horizontal';
  targetRequestId?: string;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [targetRowId, setTargetRowId] = useState(targetRow?.id || '');
  const [drawAxis, setDrawAxis] = useState<'vertical' | 'horizontal'>(targetAxis || 'horizontal');
  const [zoom, setZoom] = useState(100);
  const [fullscreenError, setFullscreenError] = useState('');
  const [orderInputs, setOrderInputs] = useState<Record<string, string>>({});
  const orderPage = useRef(page.id);
  const container = useRef<HTMLDivElement>(null);
  const drawnSelection = useRef<string | null>(null);
  const boxes = useMemo(
    () => withOrders(page.export_boxes, {}).sort((a, b) => (a.export_order || 0) - (b.export_order || 0)),
    [page.export_boxes],
  );
  const selectedBox = boxes.find((box) => box.id === selected);
  const orderErrors = useMemo(() => {
    const values = boxes.map((box, index) => ({
      box,
      raw: orderInputs[box.export_group || box.id] ?? String(box.export_order ?? index + 1),
    }));
    const errors: Record<string, string> = {};
    for (const { box, raw } of values) {
      const key = box.export_group || box.id;
      if (!box.transcription.trim()) errors[key] = 'Box chưa có chữ.';
      if (!raw.trim()) errors[key] = 'Số thứ tự không được để trống.';
      else if (!/^[1-9]\d*$/u.test(raw)) errors[key] = 'Nhập số nguyên dương.';
      else if (values.filter((item) => item.raw === raw).length > 1)
        errors[key] = 'Số thứ tự bị trùng.';
    }
    const numbers = values
      .map((item) => (/^[1-9]\d*$/u.test(item.raw) ? Number(item.raw) : null))
      .filter((value): value is number => value !== null);
    if (
      numbers.length === values.length &&
      new Set(numbers).size === values.length &&
      [...numbers].sort((a, b) => a - b).some((number, index) => number !== index + 1)
    )
      for (const { box } of values) {
        const key = box.export_group || box.id;
        errors[key] ||= 'Thứ tự phải liên tục từ 1.';
      }
    return errors;
  }, [boxes, orderInputs]);
  const alignmentMismatch = boxes.length !== alignments.length;

  useEffect(() => {
    if (!targetRow) return;
    setTargetRowId(targetRow.id);
    setDrawAxis(targetAxis || 'horizontal');
    setDrawing(true);
  }, [targetRow?.id, targetAxis, targetRequestId]);

  useEffect(() => {
    const changedPage = orderPage.current !== page.id;
    orderPage.current = page.id;
    setOrderInputs((current) => Object.fromEntries(
        boxes.map((box, index) => [
          box.export_group || box.id,
          changedPage ? String(box.export_order ?? index + 1) :
            current[box.export_group || box.id] ?? String(box.export_order ?? index + 1),
        ]),
      ));
  }, [page.id, page.export_boxes]);

  useEffect(() => {
    const validIds = new Set(alignments.map((row) => row.id));
    const orphaned = page.export_boxes.some((box) => box.alignment_id && !validIds.has(box.alignment_id));
    if (orphaned) {
      onBoxes(page.export_boxes.map((box) =>
        box.alignment_id && !validIds.has(box.alignment_id)
          ? { ...box, alignment_id: undefined }
          : box));
      return;
    }
    if (alignmentMismatch || !alignments.length) return;
    const orders = Object.fromEntries(
      boxes.map((box, index) => [box.export_group || box.id, box.export_order ?? index + 1]),
    );
    const normalized = withOrders(page.export_boxes, orders);
    const assigned = new Set(normalized.map((box) => box.alignment_id).filter(Boolean));
    const available = alignments.filter((row) => !assigned.has(row.id));
    const assignments = new Map<string, string>();
    [...normalized].filter((box) => !box.alignment_id)
      .sort((a, b) => (a.export_order || 0) - (b.export_order || 0))
      .forEach((box, index) => { if (available[index]) assignments.set(box.id, available[index].id); });
    const updated = normalized.map((box) => ({
      ...box,
      alignment_id: box.alignment_id || assignments.get(box.id),
    }));
    if (updated.some((box, index) => box.alignment_id !== page.export_boxes[index]?.alignment_id))
      onBoxes(updated);
  }, [
    alignmentMismatch,
    alignments,
    boxes,
    onBoxes,
    page.export_boxes,
  ]);

  function applyBoxes(updated: Box[]) {
    const added = updated.find((box) => !page.export_boxes.some((old) => old.id === box.id));
    if (!added) {
      onBoxes(updated);
      return;
    }
    const row = alignments.find((item) => item.id === targetRowId);
    const linked = row ? boxes.find((box) => box.alignment_id === row.id) : undefined;
    const slot = row ? boxes[alignments.findIndex((item) => item.id === row.id)] : undefined;
    const existing = linked || (slot && !slot.alignment_id ? slot : undefined);
    const base = updated.filter((box) => box.id !== added.id);
    const candidate: Box = existing
      ? { ...existing, points: added.points, transcription: row!.source, alignment_id: row!.id, box_axis: drawAxis }
      : {
          ...added,
          transcription: row?.source || '',
          alignment_id: row?.id,
          box_axis: drawAxis,
          export_group: added.id,
          export_character_order: 0,
        };
    const next = existing
      ? base.map((box) => box.id === existing.id ? candidate : box)
      : [...base, candidate];
    drawnSelection.current = candidate.id;
    onBoxes(withOrders(next, Object.fromEntries(next.map((box, index) => [box.export_group || box.id, index + 1]))));
  }

  function updateText(text: string) {
    if (!selectedBox) return;
    onBoxes(page.export_boxes.map((box) => (
      box.id === selectedBox.id ? { ...box, transcription: text } : box
    )));
  }

  function deleteSelected() {
    if (disabled || !selectedBox) return;
    const remaining = boxes.filter((box) => box.id !== selectedBox.id);
    const orders = Object.fromEntries(remaining.map((box, index) => [box.id, index + 1]));
    onBoxes(withOrders(remaining, orders));
    setSelected(null);
  }

  function applyOrderInputs(next: Record<string, string>) {
    if (boxes.some((box) => !box.transcription.trim())) return;
    const parsed: Record<string, number> = {};
    for (const box of boxes) {
      const group = box.export_group || box.id;
      const value = next[group] ?? String(box.export_order ?? boxes.indexOf(box) + 1);
      if (!/^[1-9]\d*$/u.test(value) || Object.values(parsed).includes(Number(value))) return;
      parsed[group] = Number(value);
    }
    const values = Object.values(parsed).sort((a, b) => a - b);
    if (values.some((value, index) => value !== index + 1)) return;
    onBoxes(withOrders(boxes, parsed));
  }

  function changeOrder(groupId: string, value: string) {
    const next = { ...orderInputs, [groupId]: value };
    setOrderInputs(next);
    applyOrderInputs(next);
  }

  function moveBox(index: number, offset: -1 | 1) {
    const destination = index + offset;
    if (
      destination < 0 ||
      destination >= boxes.length ||
      Object.keys(orderErrors).length ||
      boxes.some((box) => !box.transcription.trim())
    )
      return;
    const orders = Object.fromEntries(
      boxes.map((box, position) => [box.export_group || box.id, position + 1]),
    );
    const currentGroup = boxes[index].export_group || boxes[index].id;
    const destinationGroup = boxes[destination].export_group || boxes[destination].id;
    [orders[currentGroup], orders[destinationGroup]] = [
      orders[destinationGroup],
      orders[currentGroup],
    ];
    const next = Object.fromEntries(
      Object.entries(orders).map(([key, value]) => [key, String(value)]),
    );
    setOrderInputs(next);
    onBoxes(withOrders(boxes, orders));
  }

  async function toggleFullscreen() {
    try {
      if (!document.fullscreenElement) await container.current?.requestFullscreen();
      else await document.exitFullscreen();
      setFullscreenError('');
    } catch (error) {
      setFullscreenError(
        error instanceof Error ? error.message : 'Không thể mở ảnh toàn màn hình.',
      );
    }
  }

  return (
    <div className="alignment-box-editor" ref={container}>
      <div className="alignment-box-toolbar">
        <span>
          {boxes.length} box nhãn xuất · {page.boxes.length} box chữ OCR
        </span>
        <div className="alignment-sentence-draw">
          <label>
            Bounding cho câu
            <select
              aria-label="Chọn câu để vẽ bounding box"
              value={targetRowId}
              disabled={disabled}
              onChange={(event) => setTargetRowId(event.target.value)}
            >
              <option value="">Box tự do</option>
              {alignments.map((row) => (
                <option key={row.id} value={row.id}>
                  {row.sentence_id} · {row.source.slice(0, 24) || 'chưa có chữ Nôm'}
                </option>
              ))}
            </select>
          </label>
          <button
            type="button"
            className="secondary-button"
            aria-pressed={drawing && drawAxis === 'vertical'}
            disabled={disabled}
            onClick={() => {
              setDrawing((active) => !(active && drawAxis === 'vertical'));
              setDrawAxis('vertical');
            }}
          >
            <SquareDashedMousePointer size={14} /> Vẽ box dọc
          </button>
          <button
            type="button"
            className="secondary-button"
            aria-pressed={drawing && drawAxis === 'horizontal'}
            disabled={disabled}
            onClick={() => {
              setDrawing((active) => !(active && drawAxis === 'horizontal'));
              setDrawAxis('horizontal');
            }}
          >
            <SquareDashedMousePointer size={14} /> Vẽ box ngang
          </button>
          <small>{drawing ? 'Kéo trên ảnh để bao trọn một câu.' : 'Chọn câu và chiều box, rồi kéo trên ảnh.'}</small>
        </div>
        <div className="image-controls">
          <button
            type="button"
            className="icon-button"
            aria-label="Xóa box đang chọn"
            disabled={disabled || !selectedBox}
            onClick={deleteSelected}
          >
            <Trash2 size={15} />
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Thu nhỏ"
            disabled={zoom <= 50}
            onClick={() => setZoom((value) => Math.max(50, value - 25))}
          >
            <Minus size={15} />
          </button>
          <button type="button" className="zoom-reset" onClick={() => setZoom(100)}>
            {zoom}%
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Phóng to"
            disabled={zoom >= 300}
            onClick={() => setZoom((value) => Math.min(300, value + 25))}
          >
            <Plus size={15} />
          </button>
          <button
            type="button"
            className="icon-button"
            aria-label="Ảnh toàn màn hình"
            onClick={() => void toggleFullscreen()}
          >
            <Maximize2 size={16} />
          </button>
        </div>
      </div>
      {!alignments.length && (
        <small className="alignment-box-help" role="status">
          Chưa có cặp câu trên trang này. Thêm cặp ở bên dưới để vẽ bounding cho từng câu.
        </small>
      )}
      <ManuscriptViewer
        page={page}
        boxes={boxes}
        boxNumber={(box, index) =>
          orderInputs[box.export_group || box.id] ?? box.export_order ?? index + 1
        }
        selected={selected}
        setSelected={setSelected}
        showBoxes
        tool={drawing ? 'draw' : 'select'}
        zoom={zoom}
        onBoxes={applyBoxes}
        onDrawn={() => {
          setDrawing(false);
          if (drawnSelection.current) setSelected(drawnSelection.current);
          drawnSelection.current = null;
        }}
        onDeleteSelected={disabled ? undefined : deleteSelected}
        readOnly={disabled}
      />
      <div className="alignment-export-order-list" aria-label="Thứ tự box xuất">
        {alignmentMismatch && (
          <div className="alignment-box-error" role="status">
            Đã vẽ {boxes.filter((box) => box.alignment_id).length}/{alignments.length} box gắn với câu.
            Chọn từng câu rồi vẽ box dọc hoặc ngang trên ảnh.
          </div>
        )}
        {boxes.map((box, index) => {
          const groupId = box.export_group || box.id;
          const pair = alignments.find((item) => item.id === box.alignment_id);
          return (
            <div className="alignment-export-order-row" key={groupId}>
              <input
                type="text"
                inputMode="numeric"
                aria-label={`Số thứ tự box ${index + 1}`}
                aria-invalid={Boolean(orderErrors[groupId])}
                value={orderInputs[groupId] ?? String(box.export_order ?? index + 1)}
                disabled={disabled}
                onFocus={() => setSelected(box.id)}
                onChange={(event) => changeOrder(groupId, event.target.value)}
              />
              <span className="alignment-export-order-text">
                {box.transcription || 'Chưa gán chữ'}
                {box.box_axis && <small> · {box.box_axis === 'vertical' ? 'Dọc' : 'Ngang'}</small>}
              </span>
              {pair && (
                <small className="alignment-box-pair">
                  ↔ {pair.sentence_id}: {pair.source || 'chưa có Hán Nôm'} ·{' '}
                  {pair.target || 'chưa có Quốc ngữ'}
                </small>
              )}
              <button
                type="button"
                aria-label={`Đưa box ${index + 1} lên`}
                disabled={disabled || index === 0 || Boolean(Object.keys(orderErrors).length)}
                onClick={() => moveBox(index, -1)}
              >
                <ArrowUp size={14} />
              </button>
              <button
                type="button"
                aria-label={`Đưa box ${index + 1} xuống`}
                disabled={
                  disabled || index === boxes.length - 1 || Boolean(Object.keys(orderErrors).length)
                }
                onClick={() => moveBox(index, 1)}
              >
                <ArrowDown size={14} />
              </button>
              {orderErrors[groupId] && (
                <small className="alignment-box-error" role="alert">
                  {orderErrors[groupId]}
                </small>
              )}
            </div>
          );
        })}
      </div>
      {selectedBox && (
        <label className="alignment-box-transcription">
          Chữ của box nhãn đang chọn
          <input
            value={selectedBox.transcription}
            disabled={disabled}
            onChange={(event) => updateText(event.target.value)}
          />
        </label>
      )}
      {fullscreenError && (
        <small className="alignment-box-error" role="alert">
          {fullscreenError}
        </small>
      )}
      <small className="alignment-box-help">
        Chọn câu ở danh sách hoặc trong thanh công cụ, chọn vẽ dọc/ngang rồi kéo trên ảnh để bao trọn câu.
        Kéo box để di chuyển, kéo góc để đổi kích thước; nhấn Delete để xóa box đang chọn. Sửa số thứ tự hoặc dùng mũi tên để đổi thứ tự xuất; số phải liên tục, không
        trùng và box phải có chữ. Box nhãn xuất được lưu riêng, không làm thay đổi box OCR.
      </small>
    </div>
  );
}
