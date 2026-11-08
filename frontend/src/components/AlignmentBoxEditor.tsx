import { useMemo, useRef, useState } from 'react';
import { Maximize2, Minus, Plus, SquareDashedMousePointer, Trash2 } from 'lucide-react';
import type { Box, Page } from '../types';
import ManuscriptViewer from './ManuscriptViewer';
import { nomExportBoxes, updateNomExportBoxes } from './nomExportBoxes';

export default function AlignmentBoxEditor({
  page,
  disabled,
  onBoxes,
}: {
  page: Page;
  disabled: boolean;
  onBoxes: (boxes: Box[]) => void;
}) {
  const [selected, setSelected] = useState<string | null>(null);
  const [drawing, setDrawing] = useState(false);
  const [zoom, setZoom] = useState(100);
  const [fullscreenError, setFullscreenError] = useState('');
  const container = useRef<HTMLDivElement>(null);
  const boxes = useMemo(
    () => nomExportBoxes(page.boxes, page.reading_direction, page.width, page.height),
    [page.boxes, page.reading_direction, page.width, page.height],
  );
  const selectedBox = boxes.find((box) => box.id === selected);
  const selectedIsSingle = selectedBox?.source_ids.length === 1;

  function applyBoxes(updated: Box[]) {
    onBoxes(
      updateNomExportBoxes(page.boxes, updated, page.reading_direction, page.width, page.height),
    );
  }

  function updateText(text: string) {
    if (!selectedBox || !selectedIsSingle) return;
    onBoxes(
      page.boxes.map((box) =>
        box.id === selectedBox.source_ids[0] ? { ...box, transcription: text } : box,
      ),
    );
  }

  function deleteSelected() {
    if (!selectedBox) return;
    onBoxes(page.boxes.filter((box) => !selectedBox.source_ids.includes(box.id)));
    setSelected(null);
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
          {boxes.length} box hàng/cột để xuất · {page.boxes.length} box chữ gốc
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
        readOnly={disabled}
      />
      {selectedBox && selectedIsSingle && (
        <label className="alignment-box-transcription">
          Chữ trong box đang chọn
          <input
            value={selectedBox.transcription}
            disabled={disabled}
            onChange={(event) => updateText(Array.from(event.target.value).slice(0, 1).join(''))}
          />
        </label>
      )}
      {fullscreenError && (
        <small className="alignment-box-error" role="alert">
          {fullscreenError}
        </small>
      )}
      <small className="alignment-box-help">
        Kéo box để di chuyển, kéo góc để đổi kích thước; dùng nút vẽ để thêm box. Chỉnh sửa được lưu
        cùng box chữ của trang và áp dụng khi xuất Label.txt.
      </small>
    </div>
  );
}
