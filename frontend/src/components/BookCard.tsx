import { ArrowRight, BookOpen } from 'lucide-react';
import type { Book } from '../types';

export function formatBookTitle(name?: string) {
  if (!name) return '';
  return name.replace(/\.pdf$/i, '').trim();
}

type Props = {
  book: Book;
  onOpen: () => void;
  onInspect?: () => void;
  actionLabel?: string;
};

export default function BookCard({ book, onOpen, onInspect, actionLabel }: Props) {
  const selected = book.pages - (book.excluded || 0);
  const percent = selected ? Math.round((book.done / selected) * 100) : 0;
  const cleanTitle = formatBookTitle(book.name);
  const completed = selected > 0 && book.done >= selected;

  return (
    <article className="book-card">
      <div className="book-card-top">
        <div className="book-cover">
          {book.first_page_id && (
            <img
              loading="lazy"
              src={`/api/pages/${book.first_page_id}/image?thumbnail=true&v=${book.input_revision || ''}`}
              alt={`Trang đầu ${cleanTitle}`}
            />
          )}
        </div>
        <span className="local-badge">
          {book.has_pdf === false ? 'Ảnh cục bộ' : 'PDF cục bộ'}{book.reference_file ? ' · Có Quốc ngữ TXT' : ''}
        </span>
      </div>
      <h3 className="book-card-title" title={cleanTitle}>
        {cleanTitle}
      </h3>
      {book.has_new_data && (
        <span className="book-new-data-badge">
          Đã có dữ liệu mới · {book.new_data_pages} trang · {book.new_data_lines} dòng
        </span>
      )}
      {book.pair_stats && <p>{book.pair_stats.pairs} cụm được tính · {book.pair_stats.pending_error_pairs || 0} cụm lỗi chờ xác nhận</p>}
      <div className="book-card-progress">
        <span>
          {book.done} / {selected} trang đã hoàn thành · {book.excluded || 0} bỏ qua
        </span>
        <strong>{percent}%</strong>
      </div>
      <div className="progress-track">
        <span style={{ width: `${percent}%` }} />
      </div>
      {completed && <span className="book-completed-badge">Đã hoàn thành quyển</span>}
      <div className="book-card-actions">
        {onInspect && (
          <button
            type="button"
            className="secondary-button inspect-btn"
            onClick={onInspect}
            title="Mở lướt xem sách và kiểm tra kết quả từng dòng không chạy OCR"
          >
            <BookOpen size={15} />
            Mở xem sách
          </button>
        )}
        <button
          type="button"
          className={onInspect ? 'primary-button-outline' : 'secondary-button'}
          onClick={onOpen}
        >
          {actionLabel || (onInspect ? 'OCR & Gán nhãn' : 'Tiếp tục Gán nhãn')}
          <ArrowRight size={15} />
        </button>
      </div>
    </article>
  );
}
