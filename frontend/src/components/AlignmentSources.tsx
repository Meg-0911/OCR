import { useState } from 'react';
import { Plus } from 'lucide-react';
import type { Page, TextReference } from '../types';

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

  return (
    <details className="alignment-sources" open>
      <summary>Nguồn đối chiếu của sách</summary>
      <div className="alignment-source-grid">
        <label>
          Hán Nôm · {page ? `trang ${page.number}` : 'chọn trang nguồn phía trên'}
          {page && (
            <a href={page.image_url} target="_blank" rel="noreferrer">
              Mở ảnh gốc trang này
            </a>
          )}
          <textarea
            className="han-text"
            readOnly
            aria-label="Văn bản Hán Nôm đã lưu"
            value={sourceText}
            placeholder="Chạy OCR, hiệu đính và lưu trang Hán Nôm trước khi chọn câu."
            onSelect={(event) => {
              const input = event.currentTarget;
              setSourceSelection(input.value.slice(input.selectionStart, input.selectionEnd));
            }}
          />
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
          <textarea
            readOnly
            aria-label="Văn bản Quốc ngữ đối chiếu"
            value={targetText}
            placeholder="Sách này chưa có TXT đối chiếu. Nhập văn bản ở trang Quốc ngữ hoặc thêm cặp thủ công."
            onSelect={(event) => {
              const input = event.currentTarget;
              setTargetSelection(input.value.slice(input.selectionStart, input.selectionEnd));
            }}
          />
        </label>
      </div>
      <p>
        Chọn đoạn tương ứng trong mỗi ô rồi tạo cặp. TXT chỉ là nguồn đối chiếu của PDF; nội dung
        không tự ghép theo số dòng hoặc dấu trang.
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
