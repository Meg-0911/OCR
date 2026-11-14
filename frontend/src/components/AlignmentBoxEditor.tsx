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
import { allocateAlignmentOcrBoxes, boundsFromOcrBoxes } from './alignmentOcrBoxes';
import { groupCharacterBoxes } from './boxText';

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

function pageBoxesFromOne(boxes: Box[]): Box[] {
  const ordered = withOrders(boxes, {}).sort((a, b) => (a.export_order || 0) - (b.export_order || 0));
  const groups = new Map<string, number>();
  return ordered.map((box) => {
    const group = box.export_group || box.id;
    if (!groups.has(group)) groups.set(group, groups.size + 1);
    return { ...box, export_order: groups.get(group)! };
  });
}

function boundsForOcrSpan(boxes: Box[]): Box['points'] | null {
  if (!boxes.length) return null;
  const x0 = Math.min(...boxes.flatMap((box) => box.points.map((point) => point[0])));
  const y0 = Math.min(...boxes.flatMap((box) => box.points.map((point) => point[1])));
  const x1 = Math.max(...boxes.flatMap((box) => box.points.map((point) => point[0])));
  const y1 = Math.max(...boxes.flatMap((box) => box.points.map((point) => point[1])));
  if (x0 === x1 || y0 === y1) return null;
  return [[x0, y0], [x1, y0], [x1, y1], [x0, y1]];
}

function isLegacyPlaceholder(box: Box) {
  return !box.box_axis;
}

export default function AlignmentBoxEditor({
  page,
  disabled,
  onBoxes,
  alignments,
  targetRow,
  targetAxis,
  targetRequestId,
  onTargetHandled,
}: {
  page: Page;
  disabled: boolean;
  onBoxes: (boxes: Box[]) => void;
  alignments: Alignment[];
  targetRow?: Alignment;
  targetAxis?: 'vertical' | 'horizontal';
  targetRequestId?: string;
  onTargetHandled?: () => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedIds, setSelectedIds] = useState<string[]>([]);
  const [drawing, setDrawing] = useState(false);
  const [targetRowId, setTargetRowId] = useState(targetRow?.id || alignments[0]?.id || '');
  const [drawAxis, setDrawAxis] = useState<'vertical' | 'horizontal'>(targetAxis || 'horizontal');
  const [zoom, setZoom] = useState(100);
  const [fullscreenError, setFullscreenError] = useState('');
  const [orderInputs, setOrderInputs] = useState<Record<string, string>>({});
  const container = useRef<HTMLDivElement>(null);
  const drawnSelection = useRef<string | null>(null);
  const handledTargetRequest = useRef<string | null>(null);
  const validAlignmentIds = useMemo(() => new Set(alignments.map((row) => row.id)), [alignments]);
  const boxes = useMemo(
    () => pageBoxesFromOne(page.ocr_granularity === 'phrase' && alignments.length
      ? page.export_boxes.filter((box) => box.alignment_id && validAlignmentIds.has(box.alignment_id))
      : page.export_boxes),
    [page.export_boxes, page.ocr_granularity, alignments.length, validAlignmentIds],
  );
  const selectedBox = boxes.find((box) => box.id === selected);
  const selectedGroupCount = new Set(boxes
    .filter((box) => selectedIds.includes(box.id))
    .map((box) => box.export_group || box.id)).size;
  const orderErrors = useMemo(() => {
    const values = boxes.map((box, index) => ({
      box,
      raw: orderInputs[box.export_group || box.id] ?? String(box.export_order ?? index + 1),
    }));
    const errors: Record<string, string> = {};
    for (const { box, raw } of values) {
      const key = box.export_group || box.id;
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
  const linkedCount = alignments.filter((row) => boxes.some((box) => box.alignment_id === row.id)).length;
  const alignmentMismatch = linkedCount !== alignments.length;
  const ocrMatches = useMemo(
    () => allocateAlignmentOcrBoxes(page.boxes, alignments, page.ocr_granularity),
    [page.boxes, alignments, page.ocr_granularity],
  );
  const [drawHint, setDrawHint] = useState('');

  function isOcrDerivedPhraseBox(box: Box) {
    if (page.ocr_granularity !== 'phrase' || box.alignment_id || !box.box_axis) return false;
    const expected = box.transcription.replace(/\s/gu, '');
    if (!expected) return false;
    const represented = new Map(alignments
      .filter((row) => row.source_page_id === page.id && row.source_line_index != null)
      .map((row) => [row.source_line_index, row.source.replace(/\s/gu, '')]));
    const bounds = (points: Box['points']) => [
      Math.min(...points.map((point) => point[0])), Math.min(...points.map((point) => point[1])),
      Math.max(...points.map((point) => point[0])), Math.max(...points.map((point) => point[1])),
    ];
    for (let start = 0; start < page.boxes.length; start++) {
      let text = '';
      const members: Box[] = [];
      for (let index = start; index < page.boxes.length; index++) {
        if (represented.get(index) !== page.boxes[index].transcription.replace(/\s/gu, '')) break;
        members.push(page.boxes[index]);
        text += page.boxes[index].transcription;
        if (text.replace(/\s/gu, '').length > expected.length) break;
        if (text.replace(/\s/gu, '') !== expected) continue;
        const points = boundsFromOcrBoxes(members, box.box_axis);
        if (points && bounds(points).every((value, offset) =>
          Math.abs(value - bounds(box.points)[offset]) < .01)) return true;
      }
    }
    return false;
  }

  useEffect(() => {
    setSelected(null);
    setSelectedIds([]);
  }, [page.id]);

  function orderedExportBoxes(next: Box[]) {
    const rowOrder = new Map(alignments.map((row, index) => [row.id, index]));
    const sorted = [...next].sort((a, b) =>
      (rowOrder.get(a.alignment_id || '') ?? alignments.length + (a.export_order || 0)) -
      (rowOrder.get(b.alignment_id || '') ?? alignments.length + (b.export_order || 0)));
    return withOrders(sorted, Object.fromEntries(
      sorted.map((box, index) => [box.export_group || box.id, index + 1]),
    ));
  }

  function createFromOcr(row: Alignment, axis: 'vertical' | 'horizontal') {
    const matched = ocrMatches.get(row.id);
    const points = matched && boundsFromOcrBoxes(matched, axis);
    if (!matched || !points) {
      const withoutPlaceholders = page.export_boxes.filter((box) => !isLegacyPlaceholder(box));
      if (withoutPlaceholders.length !== page.export_boxes.length) onBoxes(withoutPlaceholders);
      setDrawing(true);
      setDrawHint(matched
        ? 'Các chữ OCR không nằm cùng một dòng/cột theo chiều đã chọn. Chọn chiều khác hoặc kéo thủ công; giữ Shift để vẽ đè box cũ.'
        : 'Không đủ box OCR cho số ký tự của cặp này. Kiểm tra thứ tự và số box, hoặc kéo thủ công; giữ Shift để vẽ đè box cũ.');
      return;
    }
    const base = page.export_boxes.filter((box) => !isLegacyPlaceholder(box) &&
      !isOcrDerivedPhraseBox(box));
    const existing = base.find((box) => box.alignment_id === row.id);
    const id = existing?.id || crypto.randomUUID();
    const candidate: Box = {
      ...(existing || { id, export_group: id, export_character_order: 0 }),
      transcription: row.source,
      points,
      alignment_id: row.id,
      box_axis: axis,
    };
    onBoxes(orderedExportBoxes(existing
      ? base.map((box) => box.id === id ? candidate : box)
      : [...base, candidate]));
    setSelected(id);
    setDrawing(false);
    setDrawHint(`Đã đếm ${matched.length} box OCR và tạo khung cho câu ${row.sentence_id}.`);
  }

  function chooseAxis(axis: 'vertical' | 'horizontal') {
    setDrawAxis(axis);
    const row = alignments.find((item) => item.id === targetRowId);
    if (row) createFromOcr(row, axis);
    else {
      const withoutPlaceholders = page.export_boxes.filter((box) => !isLegacyPlaceholder(box));
      if (withoutPlaceholders.length !== page.export_boxes.length) onBoxes(withoutPlaceholders);
      setDrawing(true);
      setDrawHint('Chọn câu trước khi tạo box từ chữ OCR. Có thể kéo thủ công trên ảnh.');
    }
  }

  function createAllFromOcr() {
    if (!alignments.length) {
      if (
        page.export_boxes.length &&
        !window.confirm(`Tạo box theo dòng/cột OCR sẽ thay thế ${page.export_boxes.length} box nhãn xuất hiện có trên trang. Tiếp tục?`)
      )
        return;
      const axis = page.reading_direction === 1 ? 'vertical' : 'horizontal';
      const generated: Box[] = [];
      let skipped = 0;
      for (const group of page.ocr_granularity === 'phrase'
        ? page.boxes.map((box) => [box])
        : groupCharacterBoxes(page.boxes, page.reading_direction)) {
        const points = boundsFromOcrBoxes(group, axis);
        if (!points) {
          skipped++;
          continue;
        }
        const id = crypto.randomUUID();
        generated.push({
          id,
          transcription: group.map((box) => box.transcription).join(''),
          points,
          export_group: id,
          export_order: generated.length + 1,
          export_character_order: 0,
          box_axis: axis,
        });
      }
      if (generated.length) {
        onBoxes(orderedExportBoxes(generated));
        setDrawing(false);
        setDrawHint(`Đã tự tạo ${generated.length} box theo dòng/cột OCR.${skipped ? ` Bỏ qua ${skipped} nhóm không khớp chiều đọc; hãy kiểm tra thủ công.` : ''}`);
      } else {
        setDrawHint('Không thể gom box OCR thành dòng/cột theo chiều đọc của trang. Hãy kiểm tra chiều đọc hoặc vẽ thủ công.');
      }
      return;
    }

    const next = page.export_boxes.filter((box) => !box.alignment_id && box.box_axis &&
      !isOcrDerivedPhraseBox(box));
    let created = 0;
    let updated = 0;
    let spanning = 0;
    for (const row of alignments) {
      const existing = page.export_boxes.find((box) => box.alignment_id === row.id);
      const matched = ocrMatches.get(row.id);
      if (!matched) {
        if (existing?.box_axis) next.push(existing);
        continue;
      }
      const preferred = page.reading_direction === 1 ? 'vertical' : 'horizontal';
      const alternate = preferred === 'vertical' ? 'horizontal' : 'vertical';
      const preferredBounds = boundsFromOcrBoxes(matched, preferred);
      const alternateBounds = preferredBounds ? null : boundsFromOcrBoxes(matched, alternate);
      const axis = preferredBounds ? preferred : alternateBounds ? alternate : preferred;
      const points = preferredBounds || alternateBounds || boundsForOcrSpan(matched);
      if (!points) {
        if (existing?.box_axis) next.push(existing);
        continue;
      }
      if (!preferredBounds && !alternateBounds) spanning++;
      const id = existing?.id || crypto.randomUUID();
      next.push({
        ...existing, id, export_group: existing?.export_group || id,
        export_character_order: 0,
        transcription: row.source, points, alignment_id: row.id, box_axis: axis,
      });
      if (existing) updated++;
      else created++;
    }
    if (created || updated || next.length !== page.export_boxes.length) onBoxes(orderedExportBoxes(next));
    setDrawing(false);
    setDrawHint(created || updated
      ? `Đã tạo ${created}, cập nhật ${updated} box bằng cách đếm box OCR theo số ký tự từng cặp. Kiểm tra các cặp còn thiếu nếu nhóm vượt dòng/cột.`
      : 'Chưa tạo thêm box. Các cặp đã có box, hoặc số box OCR không đủ cho số ký tự cần đếm.');
  }

  useEffect(() => {
    if (!targetRow || !targetRequestId || handledTargetRequest.current === targetRequestId) return;
    handledTargetRequest.current = targetRequestId;
    setTargetRowId(targetRow.id);
    setDrawAxis(targetAxis || 'horizontal');
    createFromOcr(targetRow, targetAxis || 'horizontal');
    onTargetHandled?.();
  }, [targetRow?.id, targetAxis, targetRequestId]);

  useEffect(() => {
    setOrderInputs(Object.fromEntries(
      boxes.map((box, index) => [box.export_group || box.id, String(box.export_order ?? index + 1)]),
    ));
  }, [page.id, page.export_boxes]);

  useEffect(() => {
    if (targetRequestId) return;
    if (page.ocr_granularity === 'phrase' && alignments.length) {
      const assigned = page.export_boxes.filter((box) =>
        box.box_axis && box.alignment_id && validAlignmentIds.has(box.alignment_id));
      if (assigned.length !== page.export_boxes.length) {
        onBoxes(pageBoxesFromOne(assigned));
        return;
      }
    }
    const orphaned = page.export_boxes.some((box) => box.alignment_id && !validAlignmentIds.has(box.alignment_id));
    if (orphaned) {
      onBoxes(page.export_boxes.map((box) =>
        box.alignment_id && !validAlignmentIds.has(box.alignment_id)
          ? { ...box, alignment_id: undefined }
          : box));
      return;
    }
  }, [
    alignments,
    validAlignmentIds,
    onBoxes,
    page.export_boxes,
    targetRequestId,
  ]);

  function applyBoxes(updated: Box[]) {
    const added = updated.find((box) => !page.export_boxes.some((old) => old.id === box.id));
    if (!added) {
      onBoxes(updated);
      return;
    }
    const row = alignments.find((item) => item.id === targetRowId);
    const base = updated.filter((box) => box.id !== added.id && !isLegacyPlaceholder(box));
    const existing = row ? base.find((box) => box.alignment_id === row.id) : undefined;
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
    onBoxes(orderedExportBoxes(next));
  }

  function deleteSelected() {
    if (disabled || !selectedBox) return;
    const selectedSet = new Set(selectedIds.length > 1 ? selectedIds : [selectedBox.id]);
    const remaining = boxes.filter((box) => !selectedSet.has(box.id));
    const orders = Object.fromEntries(remaining.map((box, index) => [box.export_group || box.id, index + 1]));
    onBoxes(withOrders(remaining, orders));
    setSelected(null);
    setSelectedIds([]);
  }

  function applyOrderInputs(next: Record<string, string>) {
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
      Object.keys(orderErrors).length
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

  function renumberSelected() {
    const chosenGroups = new Set(boxes
      .filter((box) => selectedIds.includes(box.id))
      .map((box) => box.export_group || box.id));
    if (chosenGroups.size < 2) return;
    const groups = [...new Set(boxes.map((box) => box.export_group || box.id))];
    const representatives = groups.map((group) => boxes.find((box) =>
      (box.export_group || box.id) === group)!);
    const spatialOrder = groupCharacterBoxes(
      representatives.filter((box) => chosenGroups.has(box.export_group || box.id)),
      page.reading_direction,
      false,
    ).flat().map((box) => box.export_group || box.id);
    let cursor = 0;
    const nextGroups = groups.map((group) => chosenGroups.has(group) ? spatialOrder[cursor++] : group);
    const orders = Object.fromEntries(nextGroups.map((group, index) => [group, index + 1]));
    setOrderInputs(Object.fromEntries(Object.entries(orders).map(([group, order]) => [group, String(order)])));
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
              onChange={(event) => {
                setTargetRowId(event.target.value);
                setDrawHint('');
              }}
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
            disabled={disabled || !page.boxes.length}
            onClick={createAllFromOcr}
          >
            Tạo box từ OCR
          </button>
          <button
            type="button"
            className="secondary-button"
            disabled={disabled || selectedGroupCount < 2}
            onClick={renumberSelected}
          >
            Đánh số lại ({selectedGroupCount})
          </button>
          <button
            type="button"
            className="secondary-button"
            aria-pressed={drawing && drawAxis === 'vertical'}
            disabled={disabled}
            onClick={() => {
              if (drawing && drawAxis === 'vertical') setDrawing(false);
              else chooseAxis('vertical');
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
              if (drawing && drawAxis === 'horizontal') setDrawing(false);
              else chooseAxis('horizontal');
            }}
          >
            <SquareDashedMousePointer size={14} /> Vẽ box ngang
          </button>
          <small role="status">{drawHint || (drawing
            ? 'Kéo trên ảnh để bao trọn một câu.'
            : 'Chọn câu và chiều box để lấy khung từ các chữ OCR đã rà.')}</small>
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
          Chưa có cặp câu trên trang này. Tạo box từ OCR để tự gom theo dòng/cột, hoặc thêm cặp bên dưới để tạo box cho từng câu.
        </small>
      )}
      <ManuscriptViewer
        page={page}
        boxes={boxes}
        boxNumber={(box, index) =>
          orderInputs[box.export_group || box.id] ?? box.export_order ?? index + 1
        }
        selected={selected}
        setSelected={(id) => {
          setSelected(id);
          setSelectedIds(id ? [id] : []);
          if (id) setDrawing(false);
        }}
        selectedIds={selectedIds}
        onSelectionChange={(ids) => setSelectedIds(ids)}
        allowAltDraw
        showBoxes
        tool={drawing ? 'draw' : 'select'}
        zoom={zoom}
        onBoxes={applyBoxes}
        onDrawn={() => {
          setDrawing(false);
          if (drawnSelection.current) {
            setSelected(drawnSelection.current);
            setSelectedIds([drawnSelection.current]);
          }
          drawnSelection.current = null;
        }}
        onDeleteSelected={disabled ? undefined : deleteSelected}
        readOnly={disabled}
      />
      <div className="alignment-export-order-list" aria-label="Thứ tự box xuất">
        {alignmentMismatch && (
          <div className="alignment-box-error" role="status">
            Đã tạo {linkedCount}/{alignments.length} box gắn với câu.
            Bấm Tạo box từ OCR hoặc chọn từng câu để tạo box dọc/ngang.
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
                onFocus={() => {
                  setSelected(box.id);
                  setSelectedIds([box.id]);
                }}
                onChange={(event) => changeOrder(groupId, event.target.value)}
              />
              <span className="alignment-export-order-text">
                {pair
                  ? `${ocrMatches.get(pair.id)?.length ?? 0} box chữ OCR`
                  : 'Box chưa gắn cặp'}
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
      {fullscreenError && (
        <small className="alignment-box-error" role="alert">
          {fullscreenError}
        </small>
      )}
      <small className="alignment-box-help">
        Chọn câu ở danh sách hoặc trong thanh công cụ, rồi bấm box dọc/ngang để đếm các box OCR theo số ký tự Hán Nôm của câu và tạo khung theo thứ tự đã đánh số. Không cần chữ trong từng box OCR.
        Kéo box để di chuyển, kéo góc để đổi kích thước; chọn box rồi nhấn Delete hoặc nút thùng rác để xóa. Sửa số thứ tự hoặc dùng mũi tên để đổi thứ tự xuất; số không được
        trùng. Box nhãn xuất được lưu riêng, không làm thay đổi box OCR.
      </small>
    </div>
  );
}
