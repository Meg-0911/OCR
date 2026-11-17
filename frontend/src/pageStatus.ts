import type { Page } from './types';

export function pageStatusLabel(page: Page) {
  if (page.ocr_skip || page.category === 'blank') return 'Bỏ qua';
  if (page.status === 'done') return 'Đã hoàn thành';
  if (page.review_state === 'in_progress' || page.edited_fields?.length) return 'Chưa hoàn thành';
  if (page.category === 'misc') return 'Chưa phân loại';
  return 'Chưa kiểm tra';
}
