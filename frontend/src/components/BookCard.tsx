import { ArrowRight } from 'lucide-react';
import type { Book } from '../types';

export default function BookCard({ book, onOpen }: { book: Book; onOpen: () => void }) {
  const percent = book.pages ? Math.round((book.done / book.pages) * 100) : 0;
  return (
    <article className="book-card">
      <div className="book-card-top">
        <div className="book-cover">
          <span>文</span>
          <small>HÁN NÔM</small>
          <div />
        </div>
        <span className={book.demo ? 'sample-badge' : 'local-badge'}>
          {book.demo ? 'Minh họa' : 'PDF cục bộ'}
        </span>
      </div>
      <h3>{book.name}</h3>
      <p title={book.filename}>{book.filename}</p>
      <div className="book-card-progress">
        <span>
          {book.done} / {book.pages} trang đã duyệt
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
