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
}: {
  page: Page;
  disabled: boolean;
  onBoxes: (boxes: Box[]) => void;
  alignments: Alignment[];
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [fullscreenError, setFullscreenError] = useState('');
  const [orderInputs, setOrderInputs] = useState<Record<string, string>>({});
  const container = useRef<HTMLDivElement>(null);
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
    setOrderInputs(
      Object.fromEntries(
        boxes.map((box, index) => [
          box.export_group || box.id,
          String(box.export_order ?? index + 1),
        ]),
      ),
    );
  }, [page.id, page.export_boxes]);

  useEffect(() => {
    const hasAssignments = page.export_boxes.some((box) => box.alignment_id);
    if (alignmentMismatch) {
      if (hasAssignments)
        onBoxes(page.export_boxes.map(({ alignment_id: _alignmentId, ...box }) => box));
      return;
    }
    if (!alignments.length) return;
    const orders = Object.fromEntries(
      boxes.map((box, index) => [box.export_group || box.id, box.export_order ?? index + 1]),
    );
    const normalized = withOrders(page.export_boxes, orders);
    const assignments = new Map<string, string>();
    [...normalized]
      .sort((a, b) => (a.export_order || 0) - (b.export_order || 0))
      .forEach((box, index) => assignments.set(box.id, alignments[index].id));
    const updated = normalized.map((box) => ({
      ...box,
      alignment_id: assignments.get(box.id),
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
    onBoxes(updated);
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
        <div className="image-controls">
          <button
            type="button"
            className="icon-button"
            aria-label={drawing ? 'Tắt vẽ box' : 'Vẽ box'}
            aria-pressed={drawing}
            disabled={disabled}
            onClick={() => setDrawing((value) => !value)}
          >
            <SquareDashedMousePointer size={16} />
          </button>
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
      <ManuscriptViewer
        page={page}
        boxes={boxes}
        selected={selected}
        setSelected={setSelected}
        showBoxes
        tool={drawing ? 'draw' : 'select'}
        zoom={zoom}
        onBoxes={applyBoxes}
        onDrawn={() => setDrawing(false)}
        onDeleteSelected={disabled ? undefined : deleteSelected}
        readOnly={disabled}
      />
      <div className="alignment-export-order-list" aria-label="Thứ tự box xuất">
        {alignmentMismatch && (
          <div className="alignment-box-error" role="alert">
            Có {boxes.length} box và {alignments.length} cặp của trang này. Cần tạo đúng một cặp cho
            mỗi box để tự gán.
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
        Kéo box để di chuyển, kéo góc để đổi kích thước; nhấn Delete để xóa box đang chọn. Dùng nút
        vẽ để thêm box. Sửa số thứ tự hoặc dùng mũi tên để đổi thứ tự xuất; số phải liên tục, không
        trùng và box phải có chữ. Box nhãn xuất được lưu riêng, không làm thay đổi box OCR.
      </small>
    </div>
  );
}
