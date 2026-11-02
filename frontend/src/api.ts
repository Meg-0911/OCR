import type { Alignment, Book, Box, Category, Page, SourceFile, Workspace } from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === 'string'
        ? error.detail
        : 'Không thể xử lý yêu cầu. Vui lòng thử lại.',
    );
  }
  return response.json();
}
function json(method: string, body: unknown): RequestInit {
  return { method, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) };
}
export const api = {
  workspace: () => request<Workspace>('/workspace'),
  pages: (book: string) => request<Page[]>(`/books/${book}/pages`),
  sources: () => request<SourceFile[]>('/sources'),
  importSource: (name: string) => request<Book>('/books/import', json('POST', { filename: name })),
  upload: async (file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<Book>('/books/upload', { method: 'POST', body });
  },
  savePage: (page: Page, boxes: Box[], done: boolean, category: Category) =>
    request<Page>(
      `/pages/${page.id}`,
      json('PUT', { boxes, done, category, version: page.version }),
    ),
  duplicatePage: (page: string) => request<Page>(`/pages/${page}/duplicate`, { method: 'POST' }),
  alignments: (book: string) => request<Alignment[]>(`/books/${book}/alignments`),
  saveAlignments: (book: string, rows: Alignment[]) =>
    request<Alignment[]>(`/books/${book}/alignments`, json('PUT', { rows })),
  exportUrl: (book: string, format: 'csv' | 'xlsx' | 'labels') =>
    `/api/books/${book}/export?format=${format}`,
};
