import { useEffect, useState } from 'react';
import { api } from '../api';
import type { BookLayout, Box, Page } from '../types';

export default function BookLayoutPanel({
  bookId,
  page,
  box,
  disabled,
  onSaved,
  onError,
}: {
  bookId: string;
  page?: Page;
  box?: Box;
  disabled: boolean;
  onSaved: () => void;
  onError: (error: unknown) => void;
}) {
  const [layout, setLayout] = useState<BookLayout>({ source_regions: [], target_regions: [] });
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  useEffect(() => {
    let cancelled = false;
    api
      .bookLayout(bookId)
      .then((profile) => {
        if (!cancelled) setLayout(profile);
      })
      .catch(onError);
    return () => {
      cancelled = true;
    };
  }, [bookId]);
  function add(language: 'source_regions' | 'target_regions') {
    if (!page || !box) return;
    const xs = box.points.map((p) => p[0] / page.width),
      ys = box.points.map((p) => p[1] / page.height);
    const region: [number, number, number, number] = [
      Math.min(...xs),
      Math.min(...ys),
      Math.max(...xs),
      Math.max(...ys),
    ];
    setLayout((current) => ({ ...current, [language]: [...current[language], region] }));
    setMessage('Chưa lưu mẫu mới.');
  }
  async function save() {
    setBusy(true);
    try {
      setLayout(await api.saveBookLayout(bookId, layout));
      setMessage(
        'Đã lưu vùng mẫu cho quyển. Các lượt OCR mới dùng mẫu này; bản hiệu đính và tác vụ đang chạy được giữ nguyên.',
      );
      onSaved();
    } catch (error) {
      onError(error);
    } finally {
      setBusy(false);
    }
  }
  return (
    <details className="book-layout-panel">
      <summary>
        Vùng mẫu cho cả quyển (tùy chọn) · {layout.source_regions.length} vùng Nôm /{' '}
        {layout.target_regions.length} vùng Quốc ngữ
      </summary>
      <p>
        Mặc định không cần vẽ: hai engine tự nhận dạng trên cùng ảnh; phần chữ Nôm đã có tọa độ được
        che khi đọc Quốc ngữ. Nếu cần giới hạn vùng, vẽ/chọn vùng trên một trang mẫu, gán ngôn ngữ
        rồi lưu cho cả quyển. Mẫu là vùng đọc theo tỷ lệ ảnh, không sao chép chữ hoặc box nhãn của
        trang này sang các trang khác.
      </p>
      <div className="button-group">
        <button
          className="secondary-button"
          disabled={disabled || busy || !box}
          onClick={() => add('source_regions')}
        >
          Gán vùng đang chọn cho Nôm
        </button>
        <button
          className="secondary-button"
          disabled={disabled || busy || !box}
          onClick={() => add('target_regions')}
        >
          Gán vùng đang chọn cho Quốc ngữ
        </button>
      </div>
      {(['source_regions', 'target_regions'] as const).map((key) => (
        <div key={key}>
          <strong>{key === 'source_regions' ? 'Nôm' : 'Quốc ngữ'}:</strong>
          {layout[key].length === 0
            ? ' toàn trang (tự động)'
            : layout[key].map((region, index) => (
                <span className="layout-region" key={index}>
                  {region.map((value) => `${Math.round(value * 100)}%`).join(' · ')}
                  <button
                    disabled={disabled || busy}
                    onClick={() =>
                      setLayout((current) => ({
                        ...current,
                        [key]: current[key].filter((_, i) => i !== index),
                      }))
                    }
                    aria-label={`Bỏ vùng ${index + 1}`}
                  >
                    ×
                  </button>
                </span>
              ))}
        </div>
      ))}
      <div className="button-group">
        <button
          className="secondary-button"
          disabled={disabled || busy}
          onClick={() => {
            setLayout({ source_regions: [], target_regions: [] });
            setMessage('Bấm Lưu mẫu để trở về chế độ tự động.');
          }}
        >
          Bỏ vùng mẫu
        </button>
        <button className="primary-button" disabled={disabled || busy} onClick={() => void save()}>
          Lưu mẫu cho toàn bộ quyển
        </button>
      </div>
      {message && <p role="status">{message}</p>}
    </details>
  );
}
