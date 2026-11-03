import { CheckCheck, Plus } from 'lucide-react';
import type { PairStats } from '../types';

const number = (value: number) => value.toLocaleString('vi-VN');

export default function PairProgress({
  stats,
  onImport,
}: {
  stats: PairStats;
  onImport: () => void;
}) {
  const reached = stats.remaining === 0;
  const percentage = Math.min(100, Math.floor((stats.pairs / stats.target) * 100));

  return (
    <section
      className={`pair-progress ${reached ? 'target-reached' : ''}`}
      aria-label="Mục tiêu ngữ liệu song ngữ"
    >
      <div className="pair-progress-count">
        <span className="pair-progress-label">CẶP NÔM – QUỐC NGỮ ĐÃ LƯU</span>
        <div>
          <strong>{number(stats.pairs)}</strong>
          <span>/ {number(stats.target)} cặp</span>
        </div>
        <div
          className="progress-track"
          role="progressbar"
          aria-label="Tiến độ mục tiêu cặp câu"
          aria-valuemin={0}
          aria-valuemax={stats.target}
          aria-valuenow={Math.min(stats.pairs, stats.target)}
          aria-valuetext={`${number(stats.pairs)} trên ${number(stats.target)} cặp`}
        >
          <span style={{ width: `${percentage}%` }} />
        </div>
      </div>
      <div className="pair-progress-details">
        <strong aria-live="polite" aria-atomic="true">
          {reached ? (
            <>
              <CheckCheck size={16} />
              Đã đủ mục tiêu {number(stats.target)} cặp
            </>
          ) : (
            `Còn thiếu ${number(stats.remaining)} cặp`
          )}
        </strong>
        <p>
          {reached
            ? 'Tiếp tục đối chiếu và kiểm tra chất lượng các cặp đã lưu.'
            : 'Tiếp tục căn chỉnh hoặc bổ sung tài liệu để đủ số lượng yêu cầu.'}
        </p>
        <span>Toàn bộ sách thật · Đã đọc lại {number(stats.reviewed_pairs)} cặp</span>
      </div>
      <button className="secondary-button" onClick={onImport}>
        <Plus size={15} />
        Bổ sung tài liệu
      </button>
      <div className="pair-progress-rule">
        Chỉ tính các cặp đã lưu, đủ hai vế; không tính cặp trùng văn bản.
        {(stats.incomplete_pairs > 0 || stats.duplicate_pairs > 0) &&
          ` Đang bỏ qua ${number(stats.incomplete_pairs)} cặp thiếu nội dung và ${number(stats.duplicate_pairs)} cặp trùng.`}
      </div>
    </section>
  );
}
