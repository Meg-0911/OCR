import type {
  Alignment,
  Book,
  BookLayout,
  Box,
  Category,
  DictionaryEntry,
  DictionaryLookup,
  DictionaryReverseMatch,
  OCRJob,
  OCRResult,
  OCRSettings,
  Page,
  SourceFile,
  TextReference,
  Workspace,
  BookSession,
  PagePlan,
  TextSources,
  TextReference as UploadedText,
} from './types';

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`/api${path}`, init);
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error.detail === 'string'
        ? error.detail
        : Array.isArray(error.detail)
          ? error.detail
              .map(
                (item: { loc?: (string | number)[]; msg?: string }) =>
                  `${item.loc?.filter((field) => field !== 'body').join('.') || 'Dữ liệu'}: ${item.msg || 'không hợp lệ'}`,
              )
              .join('; ')
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
  savePageLinks: (page: string, linked_page_ids: string[]) =>
    request<Page[]>(`/pages/${page}/links`, json('PUT', { linked_page_ids })),
  patchPage: (
    page: string,
    patch: Partial<
      Pick<
        Page,
        | 'source_text'
        | 'target_text'
        | 'boxes'
        | 'export_boxes'
        | 'vi_boxes'
        | 'category'
        | 'reading_direction'
        | 'ocr_skip'
        | 'source_regions'
        | 'target_regions'
        | 'ocr_languages'
      >
    >,
  ) => request<Page>(`/pages/${page}`, json('PATCH', patch)),
  bookSession: (book: string) => request<BookSession>(`/books/${book}/session`),
  saveSession: (book: string, state: BookSession) =>
    request<BookSession>(`/books/${book}/session`, json('PUT', state)),
  savePlan: (book: string, pages: PagePlan[]) =>
    request<Page[]>(`/books/${book}/plan`, json('PUT', { pages })),
  startWorkflow: (book: string, settings: OCRSettings, plan: PagePlan[]) =>
    request<OCRJob>(`/books/${book}/workflow`, json('POST', { ...settings, plan })),
  sources: () => request<SourceFile[]>('/sources'),
  syncSources: () => request<Workspace>('/sources/sync', { method: 'POST' }),
  reference: (book: string) => request<TextReference | null>(`/books/${book}/reference`),
  textSources: (book: string) => request<TextSources>(`/books/${book}/text-sources`),
  saveTextSource: (book: string, language: 'han' | 'vi', source: UploadedText) =>
    request<TextSources>(`/books/${book}/text-sources/${language}`, json('PUT', source)),
  importSource: (name: string) => request<Book>('/books/import', json('POST', { filename: name })),
  upload: async (file: File) => {
    const body = new FormData();
    body.append('file', file);
    return request<Book>('/books/upload', { method: 'POST', body });
  },
  savePage: (
    page: Page,
    boxes: Box[],
    done: boolean,
    category: Category,
    reading_direction: 1 | 2 = page.reading_direction,
    texts: Partial<Pick<Page, 'source_text' | 'target_text' | 'vi_boxes'>> = {},
  ) =>
    request<Page>(
      `/pages/${page.id}`,
      json('PUT', { boxes, export_boxes: page.export_boxes, done, category, version: page.version, reading_direction, ...texts }),
    ),
  duplicatePage: (page: string) => request<Page>(`/pages/${page}/duplicate`, { method: 'POST' }),
  latestOCR: (page: string) => request<OCRResult | null>(`/pages/${page}/ocr`),
  recognizePage: (page: string, settings: OCRSettings & { version: number; force: boolean; reuse_saved_settings?: boolean }) =>
    request<OCRResult>(`/pages/${page}/ocr`, json('POST', settings)),
  recognizeBox: (page: string, box: Box, language: 'han' | 'vi', reading_direction: 1 | 2) =>
    request<{ box_id: string; language: 'han' | 'vi'; text: string }>(`/pages/${page}/ocr-region`,
      json('POST', { box, language, reading_direction })),
  ocrJob: (book: string) => request<OCRJob | null>(`/books/${book}/ocr-job`),
  bookLayout: (book: string) => request<BookLayout>(`/books/${book}/layout`),
  saveBookLayout: (book: string, layout: BookLayout) =>
    request<BookLayout>(`/books/${book}/layout`, json('PUT', layout)),
  startOCRJob: (
    book: string,
    settings: OCRSettings,
    start_page: number,
    end_page: number,
    include_unclassified: boolean,
  ) =>
    request<OCRJob>(
      `/books/${book}/ocr-job`,
      json('POST', { ...settings, start_page, end_page, include_unclassified }),
    ),
  controlOCRJob: (job: string, action: 'pause' | 'resume') =>
    request<OCRJob>(`/ocr-jobs/${job}/${action}`, { method: 'POST' }),
  lookupCharacter: (character: string) =>
    request<DictionaryLookup>(`/dictionary/lookup?character=${encodeURIComponent(character)}`),
  searchDictionary: (query: string) =>
    request<DictionaryEntry[]>(`/dictionary/search?q=${encodeURIComponent(query)}`),
  reverseSearchDictionary: (query: string) =>
    request<DictionaryReverseMatch[]>(`/dictionary/reverse?q=${encodeURIComponent(query)}`),
  alignments: (book: string) => request<Alignment[]>(`/books/${book}/alignments`),
  saveAlignments: (book: string, rows: Alignment[]) =>
    request<Alignment[]>(`/books/${book}/alignments`, json('PUT', { rows })),
  exportUrl: (book: string, format: 'csv' | 'xlsx' | 'labels') =>
    `/api/books/${book}/export?format=${format}`,
  resultUrl: (
    book: string,
    file: 'summary.json' | 'pages.json' | 'alignments.json' | 'pairs.csv' | 'events.jsonl',
  ) => `/api/books/${book}/results/${file}`,
};
