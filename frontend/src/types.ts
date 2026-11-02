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
};
export type Book = {
  id: string;
  name: string;
  filename: string;
  pages: number;
  done: number;
  demo: boolean;
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
};
export type SourceFile = { name: string; bytes: number };
