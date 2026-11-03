import { ArrowRight } from 'lucide-react';
import type { Book } from '../types';

export default function BookCard({ book, onOpen }: { book: Book; onOpen: () => void }) {
  const selected = book.pages - (book.excluded || 0);
  const percent = selected ? Math.round((book.done / selected) * 100) : 0;
  return (
    <article className="book-card">
      <div className="book-card-top">
        <div className="book-cover">
          {book.first_page_id && (
            <img
              loading="lazy"
              src={`/api/pages/${book.first_page_id}/image?thumbnail=true`}
              alt={`Trang đầu ${book.name}`}
            />
          )}
        </div>
        <span className="local-badge">
          PDF cục bộ{book.reference_file ? ' · Có Quốc ngữ TXT' : ''}
        </span>
      </div>
      <h3>{book.name}</h3>
      <p title={book.filename}>{book.filename}</p>
      <div className="book-card-progress">
        <span>
          {book.done} / {selected} trang đã duyệt · {book.excluded || 0} bỏ qua
        </span>
        <strong>{percent}%</strong>
      </div>
      <div className="progress-track">
        <span style={{ width: `${percent}%` }} />
      </div>
      <button className="secondary-button" onClick={onOpen}>
        Tiếp tục hiệu đính
        <ArrowRight size={16} />
      </button>
    </article>
  );
}
