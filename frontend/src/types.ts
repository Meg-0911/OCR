export type Category = 'ch' | 'vi' | 'intro' | 'ref' | 'toc' | 'blank' | 'misc';
export type Box = { id: string; transcription: string; points: [number, number][] };
export type Page = {
  id: string;
  book_id: string;
  number: number;
  category: Category;
  status: 'pending' | 'done';
  width: number;
  height: number;
  boxes: Box[];
  image_url: string;
  version: number;
  reading_direction: 1 | 2;
  source_text: string;
  target_text: string;
  vi_boxes: Box[];
  ocr_skip: boolean;
  target_origin: string;
};
export type Book = {
  id: string;
  name: string;
  filename: string;
  pages: number;
  done: number;
  excluded?: number;
  first_page_id: string | null;
  reference_file: string | null;
  created_at: string;
};
export type Alignment = {
  id: string;
  sentence_id: string;
  source: string;
  target: string;
  reviewed: boolean;
};
export type PairStats = {
  target: number;
  pairs: number;
  reviewed_pairs: number;
  remaining: number;
  duplicate_pairs: number;
  incomplete_pairs: number;
};
export type Workspace = {
  books: Book[];
  pair_stats: PairStats;
  ocr_ready: boolean;
  storage: string;
  source_folder: string;
  source_errors: { filename: string; message: string }[];
  dictionary: { ready: boolean; source: string; nom_available: boolean; url: string };
  vietnamese_ocr: { ready: boolean; engine: string; setup: string; external?: boolean };
  resume?: BookSession;
};
export type BookSession = {
  book_id?: string;
  page_id?: string | null;
  view?: 'overview' | 'library' | 'review' | 'alignment' | 'export';
  alignment_page?: string | null;
};
export type PagePlan = { page_id: string; category: Category; ocr_skip: boolean };
export type SourceFile = {
  name: string;
  bytes: number;
  book_id: string | null;
  reference_file: string | null;
};
export type TextReference = { filename: string; text: string };
export type OCRSettings = {
  ocr_id: 1 | 2 | 3 | 4;
  lang_type: 0 | 1 | 2;
  reading_direction: 1 | 2;
  epitaph: 0 | 1;
  tag: string | null;
  mode?: 'han' | 'vi' | 'bilingual';
  vi_psm?: 3 | 6 | 11;
  source_regions?: [number, number, number, number][];
  target_regions?: [number, number, number, number][];
};
export type OCRResult = {
  page_id: string;
  version: number;
  result_id: string;
  boxes: Box[];
  text_lines: string[];
  warnings: string[];
  reading_direction: 1 | 2;
  settings?: OCRSettings;
  cached?: boolean;
  vi_boxes?: Box[];
  vi_text_lines?: string[];
  completed_languages?: ('han' | 'vi')[];
};
export type BookLayout = {
  source_regions: [number, number, number, number][];
  target_regions: [number, number, number, number][];
};
export type OCRJob = {
  id: string;
  book_id: string;
  status: 'running' | 'pausing' | 'paused' | 'failed' | 'completed';
  total: number;
  completed: number;
  error: string | null;
  pages: { page_id: string; number: number; status: string; error: string | null }[];
};
export type DictionaryEntry = {
  character: string;
  codepoint: string;
  source: string;
  source_url: string | null;
  language: string;
  definitions: string[];
  readings: string[];
  mandarin: string;
  variants: { character: string; kind: string; definitions: string[]; readings: string[] }[];
};
export type DictionaryLookup = {
  query: string;
  found: boolean;
  entry: DictionaryEntry | null;
  fallback: boolean;
  notice: string;
};
