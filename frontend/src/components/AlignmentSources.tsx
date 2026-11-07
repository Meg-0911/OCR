import { useState } from 'react';
import { Plus } from 'lucide-react';
import type { MouseEvent } from 'react';
import type { Page, ReviewKind, TextReference } from '../types';
import { reviewColorsForText } from '../reviewColors';

export default function AlignmentSources({
  page,
  pages,
  reference,
  busy,
  onCreate,
}: {
  page?: Page;
  pages: Page[];
  reference: TextReference | null;
  busy: boolean;
  onCreate: (source: string, target: string) => void;
}) {
  const targets = pages.filter((p) => p.category === 'vi');
  const [targetId, setTargetId] = useState(
    targets.find((p) => p.number === page?.number)?.id || targets[0]?.id || '',
  );
  const [sourceSelection, setSourceSelection] = useState('');
  const [targetSelection, setTargetSelection] = useState('');
  const sourceText =
    page?.source_text || page?.boxes.map((box) => box.transcription).join('\n') || '';
  const targetText =
    page?.target_text ||
    reference?.text ||
    targets
      .find((p) => p.id === targetId)
      ?.boxes.map((box) => box.transcription)
      .join('\n') ||
    '';
  const sourceColors = page
    ? reviewColorsForText(sourceText, page.boxes, 'source')
    : [];
  const targetColors = page
    ? reviewColorsForText(targetText, page.boxes, 'target')
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
          <div className="alignment-source-image-heading">
            <strong>Ảnh gốc · trang {page.number}</strong>
            <a href={page.image_url} target="_blank" rel="noreferrer">
              Mở ảnh kích thước đầy đủ
            </a>
          </div>
          <a
            className="alignment-source-image"
            href={page.image_url}
            target="_blank"
            rel="noreferrer"
            aria-label={`Mở ảnh gốc trang ${page.number} kích thước đầy đủ`}
          >
            <img src={page.image_url} alt={`Ảnh gốc trang ${page.number}`} />
          </a>
        </div>
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
          {page?.target_text
            ? `OCR cùng trang ${page.number}`
            : reference
              ? reference.filename
              : 'văn bản trang đã lưu'}
          {!reference && !page?.target_text && (
            <select
              aria-label="Trang Quốc ngữ đối chiếu"
              value={targetId}
              onChange={(event) => {
                setTargetId(event.target.value);
                setTargetSelection('');
              }}
            >
              <option value="">Chọn trang Quốc ngữ</option>
              {targets.map((p) => (
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
        Tự căn toàn sách ghép theo số trang và thứ tự dòng; hãy kiểm tra lại trên ảnh vì đây chỉ là
        gợi ý, không xác nhận tương đồng ngữ nghĩa.
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
