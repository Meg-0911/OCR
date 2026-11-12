import { useState } from 'react';
import { Plus } from 'lucide-react';
import type { MouseEvent } from 'react';
import type { Alignment, Page, ReviewKind, TextReference } from '../types';
import { reviewColorsForText } from '../reviewColors';
import AlignmentBoxEditor from './AlignmentBoxEditor';
import ManuscriptViewer from './ManuscriptViewer';

export default function AlignmentSources({
  page,
  pages,
  reference,
  busy,
  onCreate,
  onBoxes,
  alignments,
  targetRow,
  targetAxis,
  targetRequestId,
  onTargetHandled,
}: {
  page?: Page;
  pages: Page[];
  reference: TextReference | null;
  busy: boolean;
  onCreate: (source: string, target: string) => void;
  onBoxes: (page: Page, boxes: Page['boxes']) => void;
  alignments: Alignment[];
  targetRow?: Alignment;
  targetAxis?: 'vertical' | 'horizontal';
  targetRequestId?: string;
  onTargetHandled?: () => void;
}) {
  const targets = pages.filter((p) => p.id !== page?.id && p.ocr_languages.includes('vi'));
  const [targetId, setTargetId] = useState(
    targets.find((p) => page?.linked_page_ids.includes(p.id))?.id ||
    targets.find((p) => p.number === page?.number)?.id || '',
  );
  const [sourceSelection, setSourceSelection] = useState('');
  const [targetSelection, setTargetSelection] = useState('');
  const sourceText = page?.ocr_granularity === 'phrase'
    ? page.boxes.map((box) => box.transcription).join('\n')
    : page?.source_text || page?.boxes.map((box) => box.transcription).join('\n') || '';
  const selectedTarget = targets.find((p) => p.id === targetId);
  const imageTarget = page?.linked_page_ids.length ? selectedTarget : page?.vi_boxes.length ? page : selectedTarget;
  const targetText = page?.linked_page_ids.length
    ? selectedTarget?.target_text || selectedTarget?.vi_boxes.map((box) => box.transcription).join('\n') || page.target_text || ''
    : page?.target_text || reference?.text || selectedTarget?.target_text ||
      selectedTarget?.vi_boxes.map((box) => box.transcription).join('\n') || '';
  const sourceColors = page
    ? reviewColorsForText(sourceText, page.boxes, 'source')
    : [];
  const targetColors = page
    ? reviewColorsForText(targetText, page.linked_page_ids.length ? selectedTarget?.vi_boxes || [] : page.boxes, 'target')
    : [];
  function selectedText(event: MouseEvent<HTMLDivElement>, setter: (value: string) => void) {
    const selection = window.getSelection();
    if (!selection || !event.currentTarget.contains(selection.anchorNode)) return;
    setter(selection.toString());
  }
  function coloredText(value: string, colors: ReviewKind[]) {
    return Array.from(value).map((character, index) => (
      <span className={`review-${colors[index] || 'match'}`} key={index}>
        {character}
      </span>
    ));
  }

  return (
    <details className="alignment-sources" open>
      <summary>Nguồn đối chiếu của sách</summary>
      {page && (
        <div className="alignment-source-image-panel">
          <div className="alignment-source-image-pair">
            <div>
              <div className="alignment-source-image-heading">
                <strong>Ảnh Hán Nôm · trang {String(page.number).padStart(3, '0')}</strong>
                <a href={page.image_url} target="_blank" rel="noreferrer">Mở ảnh gốc</a>
              </div>
              <AlignmentBoxEditor
                page={page}
                disabled={busy}
                alignments={alignments}
                targetRow={targetRow}
                targetAxis={targetAxis}
                targetRequestId={targetRequestId}
                onTargetHandled={onTargetHandled}
                onBoxes={(boxes) => onBoxes(page, boxes)}
              />
            </div>
            {imageTarget && <div>
              <div className="alignment-source-image-heading">
                <strong>Ảnh Quốc ngữ · trang {String(imageTarget.number).padStart(3, '0')}</strong>
                <a href={imageTarget.image_url} target="_blank" rel="noreferrer">Mở ảnh gốc</a>
              </div>
              <div className="alignment-target-image">
                <ManuscriptViewer page={imageTarget} boxes={imageTarget.vi_boxes}
                  selected={null} setSelected={() => {}} showBoxes tool="select" zoom={100}
                  onBoxes={() => {}} onDrawn={() => {}} readOnly />
              </div>
            </div>}
          </div>
        </div>
      )}
      {!page && (
        <p role="status">Chọn trang có chữ Nôm ở thanh phía trên để hiện ảnh và công cụ vẽ bounding theo từng câu.</p>
      )}
      <div className="alignment-source-grid">
        <label>
          Hán Nôm · {page ? `trang ${page.number}` : 'chọn trang nguồn phía trên'}
          <div
            className="alignment-source-text han-text"
            aria-label="Văn bản Hán Nôm đã lưu"
            onMouseUp={(event) => selectedText(event, setSourceSelection)}
          >
            {sourceText
              ? coloredText(sourceText, sourceColors)
              : 'Chạy OCR, Gán nhãn và lưu trang Hán Nôm trước khi chọn câu.'}
          </div>
        </label>
        <label>
          Quốc ngữ ·{' '}
          {page?.linked_page_ids.length
            ? `trang ${selectedTarget?.number || 'liên kết'}`
            : page?.target_text
            ? `OCR cùng trang ${page.number}`
            : reference
              ? reference.filename
              : 'văn bản trang đã lưu'}
          {(!!page?.linked_page_ids.length || (!reference && !page?.target_text)) && (
            <select
              aria-label="Trang Quốc ngữ đối chiếu"
              value={targetId}
              onChange={(event) => {
                setTargetId(event.target.value);
                setTargetSelection('');
              }}
            >
              <option value="">Chọn trang Quốc ngữ</option>
              {targets.filter((p) => !page?.linked_page_ids.length || page.linked_page_ids.includes(p.id)).map((p) => (
                <option key={p.id} value={p.id}>
                  Trang {p.number}
                </option>
              ))}
            </select>
          )}
          <div
            className="alignment-source-text"
            aria-label="Văn bản Quốc ngữ đối chiếu"
            onMouseUp={(event) => selectedText(event, setTargetSelection)}
          >
            {targetText
              ? coloredText(targetText, targetColors)
              : 'Sách này chưa có TXT đối chiếu. Nhập văn bản ở trang Quốc ngữ hoặc thêm cặp thủ công.'}
          </div>
        </label>
      </div>
      <p>
        Cặp được tự ghép theo trang và thứ tự dòng OCR. Kiểm tra lại trên ảnh trước khi xác nhận
        vì thứ tự dòng không bảo đảm hai vế tương ứng về nghĩa.
      </p>
      <div className="alignment-source-selection">
        <button
          className="secondary-button"
          disabled={busy || !page || !sourceText.trim() || !targetText.trim()}
          onClick={() => onCreate(sourceText.trim(), targetText.trim())}
        >
          Tạo cặp nháp từ toàn bộ trang để tách/gộp sau
        </button>
        <span>
          Đã chọn: {sourceSelection.length} ký tự Hán Nôm · {targetSelection.length} ký tự Quốc ngữ
        </span>
        <button
          className="secondary-button"
          disabled={busy || !page || !sourceSelection.trim() || !targetSelection.trim()}
          onClick={() => {
            onCreate(sourceSelection.trim(), targetSelection.trim());
            setSourceSelection('');
            setTargetSelection('');
          }}
        >
          <Plus size={15} />
          Tạo cặp từ đoạn đã chọn
        </button>
      </div>
    </details>
  );
}
