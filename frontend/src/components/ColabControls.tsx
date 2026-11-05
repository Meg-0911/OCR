import { useRef, useState } from 'react';

export default function ColabControls(props: {
  bookId: string;
  disabled: boolean;
  beforeStart: () => Promise<void>;
  onRefresh: () => void;
  onError: (error: unknown) => void;
}) {
  const input = useRef<HTMLInputElement>(null);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState('');
  async function exchange(file?: File) {
    setBusy(true);
    setMessage('');
    try {
      await props.beforeStart();
      const path = `/api/books/${encodeURIComponent(props.bookId)}`;
      if (file) {
        const body = new FormData();
        body.append('file', file);
        const response = await fetch(`${path}/colab-results`, { method: 'POST', body });
        const data = await response.json();
        if (!response.ok) throw new Error(data.detail || 'Không nhập được kết quả Colab');
        setMessage(`Đã nhập ${data.imported}/${data.exported} trang; cần duyệt lại.`);
        props.onRefresh();
      } else {
        const response = await fetch(`${path}/colab-bundle`);
        if (!response.ok) {
          const data = await response.json();
          throw new Error(data.detail || 'Không xuất được gói Colab');
        }
        const url = URL.createObjectURL(await response.blob());
        const link = document.createElement('a');
        link.href = url;
        link.download = 'vietocr-colab-input.zip';
        link.click();
        setTimeout(() => URL.revokeObjectURL(url), 10000);
        setMessage('Đã xuất. Chạy notebook trên Colab rồi nhập ZIP kết quả tại đây.');
      }
    } catch (error) {
      props.onError(error);
    } finally {
      setBusy(false);
      if (input.current) input.current.value = '';
    }
  }
  return (
    <div className="workbench-ocr-controls">
      <a href="/api/colab/notebook" download>Notebook VietOCR GPU</a>
      <a href="/api/colab/source" download>Mã chạy Colab</a>
      <button className="secondary-button" disabled={busy || props.disabled} onClick={() => void exchange()}>
        Xuất ảnh cho Colab
      </button>
      <button className="secondary-button" disabled={busy || props.disabled} onClick={() => input.current?.click()}>
        Nhập kết quả Colab
      </button>
      <input ref={input} type="file" accept=".zip" hidden onChange={event => {
        const file = event.target.files?.[0];
        if (file) void exchange(file);
      }} />
      <span role="status">{busy ? 'Đang xử lý gói Colab…' : message}</span>
    </div>
  );
}
