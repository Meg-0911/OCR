import { useEffect, useRef, useState } from 'react';
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Boxes,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Download,
  Eye,
  EyeOff,
  FileCheck2,
  FileText,
  FolderOpen,
  GripVertical,
  LayoutDashboard,
  Library,
  Link2,
  LoaderCircle,
  Maximize2,
  Minus,
  MousePointer2,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RotateCcw,
  Save,
  ScanLine,
  Search,
  Settings2,
  ShieldCheck,
  SlidersHorizontal,
  SplitSquareVertical,
  SquareDashedMousePointer,
  Trash2,
  Upload,
  X,
} from 'lucide-react';
import { api } from './api';
import ManuscriptViewer from './components/ManuscriptViewer';
import AlignmentRow from './components/AlignmentRow';
import BookCard from './components/BookCard';
import Stat from './components/Stat';
import PairProgress from './components/PairProgress';
import AlignmentSources from './components/AlignmentSources';
import BookOCRPanel from './components/BookOCRPanel';
import BookLayoutPanel from './components/BookLayoutPanel';
import DictionaryPanel, { CharacterStrip } from './components/DictionaryPanel';
import type {
  Alignment,
  Book,
  Box,
  Category,
  Page,
  SourceFile,
  TextReference,
  Workspace,
  OCRJob,
  OCRResult,
  BookSession,
} from './types';

type View = 'overview' | 'library' | 'review' | 'alignment' | 'export';
type Draft = {
  boxes: Box[];
  category: Category;
  reading_direction?: 1 | 2;
  source_text?: string;
  target_text?: string;
  vi_boxes?: Box[];
  ocr_skip?: boolean;
  dirty_fields?: string[];
};
function draftPatch(draft: Draft) {
  const keys = draft.dirty_fields || [
    'boxes',
    'category',
    'reading_direction',
    'source_text',
    'target_text',
    'vi_boxes',
    'ocr_skip',
  ];
  return Object.fromEntries(
    keys
      .filter((key) => key in draft && key !== 'dirty_fields')
      .map((key) => [key, draft[key as keyof Draft]]),
  ) as Partial<
    Pick<
      Page,
      | 'boxes'
      | 'category'
      | 'reading_direction'
      | 'source_text'
      | 'target_text'
      | 'vi_boxes'
      | 'ocr_skip'
    >
  >;
}
const categories: Record<Category, string> = {
  ch: 'Hán Nôm',
  vi: 'Quốc ngữ',
  intro: 'Giới thiệu',
  ref: 'Chú thích',
  toc: 'Mục lục',
  blank: 'Trang trắng',
  misc: 'Chưa phân loại / Khác',
};
const nav = [
  { id: 'overview', label: 'Tổng quan', icon: LayoutDashboard },
  { id: 'library', label: 'Tủ sách', icon: Library },
  { id: 'review', label: 'Hiệu đính OCR', icon: ScanLine },
  { id: 'alignment', label: 'Căn chỉnh song ngữ', icon: SplitSquareVertical },
  { id: 'export', label: 'Xuất dữ liệu', icon: ArrowDownToLine },
] as const;

function readDrafts(): Record<string, Draft> {
  try {
    return JSON.parse(localStorage.getItem('nom-drafts-v1') || '{}');
  } catch {
    return {};
  }
}
function readableSize(bytes: number) {
  return `${(bytes / 1048576).toFixed(1)} MB`;
}
function readSidebarCollapsed() {
  try {
    return localStorage.getItem('nom-sidebar-collapsed') === 'true';
  } catch {
    return false;
  }
}
function readSession(book?: string): BookSession {
  try {
    return JSON.parse(localStorage.getItem(book ? `nom-session-${book}` : 'nom-session') || '{}');
  } catch {
    return {};
  }
}

export default function App() {
  const [nomFontStatus, setNomFontStatus] = useState('Đang tải font Nôm…');
  useEffect(() => {
    let cancelled = false;
    document.fonts
      .load('20px "Nom Workspace Nom"', '𠊛喃漢')
      .then((faces) => {
        if (!cancelled)
          setNomFontStatus(
            faces.length ? 'Nôm Na Tống · đã tải' : 'Không tìm thấy font Nôm trong bản build',
          );
      })
      .catch(() => {
        if (!cancelled) setNomFontStatus('Không tải được font Nôm · thử Ctrl + F5');
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const [view, setView] = useState<View>('review');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [bookId, setBookId] = useState('');
  const [pages, setPages] = useState<Page[]>([]);
  const [pageId, setPageId] = useState('');
  const [category, setCategory] = useState<string>('ch');
  const [status, setStatus] = useState('all');
  const [pageSearch, setPageSearch] = useState('');
  const [drafts, setDrafts] = useState<Record<string, Draft>>(readDrafts);
  const [selectedBox, setSelectedBox] = useState<string | null>(null);
  const [showBoxes, setShowBoxes] = useState(false);
  const [tool, setTool] = useState<'select' | 'draw'>('select');
  const [zoom, setZoom] = useState(100);
  const [busy, setBusy] = useState(false);
  const [loadingPages, setLoadingPages] = useState(false);
  const [connectionError, setConnectionError] = useState('');
  const [toast, setToast] = useState<{ message: string; error?: boolean } | null>(null);
  const [modal, setModal] = useState<'import' | 'guide' | 'settings' | null>(null);
  const [sources, setSources] = useState<SourceFile[]>([]);
  const [sourceSearch, setSourceSearch] = useState('');
  const [sourceLoading, setSourceLoading] = useState(false);
  const [rows, setRows] = useState<Alignment[]>([]);
  const [rowsDirty, setRowsDirty] = useState(false);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const alignmentTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const alignmentSaves = useRef(new Map<string, Promise<Alignment[]>>());
  const [alignmentLoading, setAlignmentLoading] = useState(false);
  const [alignmentPage, setAlignmentPage] = useState('');
  const [reference, setReference] = useState<TextReference | null>(null);
  const [librarySearch, setLibrarySearch] = useState('');
  const [dictionaryCharacter, setDictionaryCharacter] = useState<string | null>(null);
  const [bookJob, setBookJob] = useState<OCRJob | null>(null);
  const [pageOCR, setPageOCR] = useState<OCRResult | null>(null);
  const [autosaveState, setAutosaveState] = useState('Mọi chỉnh sửa được lưu tự động.');
  const draftsRef = useRef(drafts);
  draftsRef.current = drafts;
  const savingDrafts = useRef(new Map<string, Promise<Page>>());
  const sessionRestored = useRef(false);
  const sessionSaves = useRef<Promise<unknown>>(Promise.resolve());
  const currentBookRef = useRef(bookId);
  currentBookRef.current = bookId;
  const [dictionarySelection, setDictionarySelection] = useState<{
    pageId: string;
    boxId: string;
    index: number;
    character: string;
  } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const activeBook = workspace?.books.find((b) => b.id === bookId);
  const page = pages.find((p) => p.id === pageId);
  const draft = page
    ? {
        ...page,
        ...(drafts[page.id] ? draftPatch(drafts[page.id]) : {}),
      }
    : null;
  const filteredPages = pages.filter(
    (p) =>
      (category === 'all' || p.category === category) &&
      (status === 'all' || p.status === status) &&
      (!pageSearch || String(p.number).padStart(3, '0').includes(pageSearch)),
  );
  const reviewablePages = pages.filter((p) => !p.ocr_skip && p.category !== 'blank');
  const pendingCount = reviewablePages.filter((p) => p.status === 'pending').length;
  const doneCount = reviewablePages.length - pendingCount;
  const progress = reviewablePages.length
    ? Math.round((doneCount / reviewablePages.length) * 100)
    : 0;

  function replaceDictionaryCharacter(character: string) {
    const selected = dictionarySelection;
    const box = draft?.boxes.find((box) => box.id === selected?.boxId);
    const text = selected?.boxId === 'page-source' ? draft?.source_text : box?.transcription;
    if (
      !page ||
      !draft ||
      !selected ||
      selected.pageId !== page.id ||
      text === undefined ||
      text.slice(selected.index, selected.index + selected.character.length) !== selected.character
    ) {
      notify('Vị trí chữ đã thay đổi. Bấm lại chữ cần sửa trước khi thay.', true);
      return;
    }
    if (selected.boxId === 'page-source')
      updateDraft({
        source_text:
          text.slice(0, selected.index) +
          character +
          text.slice(selected.index + selected.character.length),
      });
    else
      updateDraft({
        boxes: draft.boxes.map((b) =>
          b.id === selected.boxId
            ? {
                ...b,
                transcription:
                  b.transcription.slice(0, selected.index) +
                  character +
                  b.transcription.slice(selected.index + selected.character.length),
              }
            : b,
        ),
      });
    setDictionarySelection({ ...selected, character });
    setDictionaryCharacter(character);
    notify('Đã thay chữ. Chỉnh sửa sẽ tự lưu; Ctrl + S để lưu ngay.');
  }

  async function refreshBookPages() {
    try {
      const id = bookId;
      const next = await api.pages(id);
      if (currentBookRef.current !== id) return;
      setPages((previous) =>
        next.map((p) => {
          const old = previous.find((q) => q.id === p.id);
          return old && old.version > p.version ? old : p;
        }),
      );
      void loadWorkspace();
    } catch (error) {
      fail(error);
    }
  }

  useEffect(() => {
    if (!modal) return;
    const dialog = document.querySelector<HTMLElement>('[role="dialog"]');
    if (!dialog) return;
    const previous = document.activeElement as HTMLElement | null;
    const focusable = () =>
      Array.from(
        dialog.querySelectorAll<HTMLElement>(
          'button:not(:disabled), input:not([hidden]), select:not(:disabled), textarea, a[href]',
        ),
      );
    focusable()[0]?.focus();
    const handleKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) setModal(null);
      if (event.key !== 'Tab') return;
      const elements = focusable();
      const first = elements[0],
        last = elements[elements.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last?.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first?.focus();
      }
    };
    document.addEventListener('keydown', handleKey);
    return () => {
      document.removeEventListener('keydown', handleKey);
      previous?.focus();
    };
  }, [modal, busy]);

  function notify(message: string, error = false) {
    setToast({ message, error });
    if (toastTimer.current) clearTimeout(toastTimer.current);
    toastTimer.current = setTimeout(() => setToast(null), 6000);
  }
  function fail(error: unknown) {
    notify(error instanceof Error ? error.message : 'Đã có lỗi xảy ra.', true);
  }
  function toggleSidebar() {
    const next = !sidebarCollapsed;
    setSidebarCollapsed(next);
    try {
      localStorage.setItem('nom-sidebar-collapsed', String(next));
    } catch {
      /* Collapsing still works without browser storage. */
    }
  }
  function updateDraft(patch: Partial<Draft>) {
    if (!page || !draft) return;
    setDrafts((previous) => {
      const updated = {
        ...previous,
        [page.id]: {
          ...draft,
          ...previous[page.id],
          ...patch,
          dirty_fields: Array.from(
            new Set([
              ...(previous[page.id]?.dirty_fields ||
                (previous[page.id] ? Object.keys(previous[page.id]) : [])),
              ...Object.keys(patch),
            ]),
          ),
        },
      };
      try {
        localStorage.setItem('nom-drafts-v1', JSON.stringify(updated));
      } catch {
        notify(
          'Không lưu được bản nháp trên trình duyệt. Hãy bấm Lưu bản nháp để lưu vào máy.',
          true,
        );
      }
      return updated;
    });
  }
  async function saveDraftNow(id: string): Promise<Page | undefined> {
    const inflight = savingDrafts.current.get(id);
    if (inflight) {
      await inflight;
      return saveDraftNow(id);
    }
    const snapshot = draftsRef.current[id];
    if (!snapshot) return;
    setAutosaveState('Đang lưu chỉnh sửa…');
    const task = api.patchPage(id, draftPatch(snapshot));
    savingDrafts.current.set(id, task);
    try {
      const updated = await task;
      if (draftsRef.current[id] === snapshot) {
        const next = { ...draftsRef.current };
        delete next[id];
        draftsRef.current = next;
      }
      setPages((previous) =>
        previous.map((p) => (p.id === id && p.version <= updated.version ? updated : p)),
      );
      setDrafts((previous) => {
        if (previous[id] !== snapshot) return previous;
        const next = { ...previous };
        delete next[id];
        draftsRef.current = next;
        try {
          localStorage.setItem('nom-drafts-v1', JSON.stringify(next));
        } catch {
          /* server copy saved */
        }
        return next;
      });
      setAutosaveState('Đã lưu chỉnh sửa vào máy.');
      return updated;
    } catch (error) {
      setAutosaveState('Chưa lưu được vào máy; bản nháp còn trên trình duyệt.');
      throw error;
    } finally {
      savingDrafts.current.delete(id);
    }
  }
  async function saveBookDrafts() {
    for (const p of pages) await saveDraftNow(p.id);
  }
  useEffect(() => {
    if (busy || !pages.length) return;
    const ids = pages.filter((p) => drafts[p.id]).map((p) => p.id);
    if (!ids.length) return;
    const timer = setTimeout(() => {
      void (async () => {
        for (const id of ids) await saveDraftNow(id);
      })().catch(fail);
    }, 800);
    return () => clearTimeout(timer);
  }, [drafts, busy, bookId, loadingPages]);
  async function loadWorkspace() {
    try {
      const result = await api.workspace();
      setWorkspace(result);
      if (!sessionRestored.current) {
        sessionRestored.current = true;
        const local = readSession();
        const resume = result.books.some((b) => b.id === local.book_id) ? local : result.resume;
        if (resume?.view) setView(resume.view);
      }
      setConnectionError('');
      setBookId((current) =>
        current && result.books.some((b) => b.id === current)
          ? current
          : result.books.find((b) => b.id === readSession().book_id)?.id ||
            result.books.find((b) => b.id === result.resume?.book_id)?.id ||
            result.books[0]?.id ||
            '',
      );
    } catch (error) {
      setConnectionError(error instanceof Error ? error.message : 'Không kết nối được backend.');
    }
  }
  useEffect(() => {
    void loadWorkspace();
  }, []);
  useEffect(() => {
    if (!bookId) return;
    let cancelled = false;
    setLoadingPages(true);
    setPages([]);
    setPageId('');
    setAlignmentPage('');
    setBookJob(null);
    Promise.all([api.pages(bookId), api.bookSession(bookId)])
      .then(([result, savedSession]) => {
        if (cancelled) return;
        const localSession = readSession(bookId);
        const session = result.some((p) => p.id === localSession.page_id)
          ? localSession
          : savedSession;
        setPages(result);
        const first =
          result.find((p) => p.id === session.page_id) ||
          result.find((p) => p.status === 'pending' && p.category === 'ch') ||
          result.find((p) => p.status === 'pending') ||
          result[0];
        setPageId(first?.id || '');
        setCategory('all');
        if (session.alignment_page) setAlignmentPage(session.alignment_page);
        setStatus('all');
        setPageSearch('');
      })
      .catch((error) => {
        if (!cancelled) fail(error);
      })
      .finally(() => {
        if (!cancelled) setLoadingPages(false);
      });
    return () => {
      cancelled = true;
    };
  }, [bookId]);
  useEffect(() => {
    if (!bookId || loadingPages || !pageId || !pages.some((p) => p.id === pageId)) return;
    const state = { book_id: bookId, page_id: pageId, view, alignment_page: alignmentPage || null };
    try {
      localStorage.setItem('nom-session', JSON.stringify(state));
      localStorage.setItem(`nom-session-${bookId}`, JSON.stringify(state));
    } catch {
      /* server session below */
    }
    const timer = setTimeout(() => {
      sessionSaves.current = sessionSaves.current
        .catch(() => {})
        .then(() => api.saveSession(bookId, state))
        .catch(() => {});
    }, 350);
    return () => clearTimeout(timer);
  }, [bookId, pageId, view, alignmentPage, loadingPages]);
  useEffect(() => {
    setSelectedBox(null);
    setTool('select');
    setZoom(100);
  }, [pageId]);
  useEffect(() => {
    setPageOCR(null);
    if (!pageId) return;
    let cancelled = false;
    api
      .latestOCR(pageId)
      .then((result) => {
        if (!cancelled) setPageOCR(result);
      })
      .catch(() => {});
    return () => {
      cancelled = true;
    };
  }, [pageId, page?.version]);
  useEffect(() => {
    if (!filteredPages.some((p) => p.id === pageId)) setPageId(filteredPages[0]?.id || '');
  }, [pages, category, status, pageSearch, pageId]);
  useEffect(() => {
    if (!bookId || view !== 'alignment') return;
    let cancelled = false;
    setAlignmentLoading(true);
    setRows([]);
    setReference(null);
    Promise.all([api.alignments(bookId), api.reference(bookId)])
      .then(([result, referenceText]) => {
        if (cancelled) return;
        setReference(referenceText);
        let cached: Alignment[] | null = null;
        try {
          cached = JSON.parse(localStorage.getItem(`nom-alignment-${bookId}`) || 'null');
        } catch {
          /* use saved rows */
        }
        setRows(cached || result);
        setRowsDirty(!!cached);
        if (cached) queueRows(bookId, cached);
      })
      .catch(fail)
      .finally(() => {
        if (!cancelled) setAlignmentLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [bookId, view]);
  function persistRows(id: string, snapshot: Alignment[]) {
    const previous = alignmentSaves.current.get(id) || Promise.resolve([]);
    const task = previous.catch(() => []).then(() => api.saveAlignments(id, snapshot));
    alignmentSaves.current.set(id, task);
    return task.then((saved) => {
      if (currentBookRef.current !== id || rowsRef.current !== snapshot) return;
      setRows(saved);
      setRowsDirty(false);
      try {
        localStorage.removeItem(`nom-alignment-${id}`);
      } catch {
        /* saved on server */
      }
      void loadWorkspace();
    });
  }
  function queueRows(id: string, snapshot: Alignment[]) {
    clearTimeout(alignmentTimers.current.get(id));
    alignmentTimers.current.set(
      id,
      setTimeout(() => void persistRows(id, snapshot).catch(fail), 1200),
    );
  }

  function chooseCategory(next: string) {
    setCategory(next);
    const first = pages.find(
      (p) => (next === 'all' || p.category === next) && (status === 'all' || p.status === status),
    );
    if (first) setPageId(first.id);
  }
  async function savePage(done: boolean) {
    if (!page || !draft) return;
    setBusy(true);
    try {
      await saveDraftNow(page.id);
      const current = (await api.pages(bookId)).find((p) => p.id === page.id)!;
      const updated = done
        ? await api.savePage(
            current,
            current.boxes,
            true,
            current.category,
            current.reading_direction,
          )
        : current;
      setPages((previous) => previous.map((p) => (p.id === updated.id ? updated : p)));
      if (done) {
        const currentIndex = filteredPages.findIndex((p) => p.id === page.id);
        const next = [
          ...filteredPages.slice(currentIndex + 1),
          ...filteredPages.slice(0, currentIndex),
        ].find((p) => p.status === 'pending');
        if (next) setPageId(next.id);
        notify(
          next
            ? 'Đã hoàn thành và mở trang tiếp theo.'
            : 'Đã hoàn thành trang. Không còn trang chờ trong bộ lọc này.',
        );
      } else notify('Đã lưu bản nháp vào máy.');
      void loadWorkspace();
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    const listener = (event: KeyboardEvent) => {
      if (
        (event.ctrlKey || event.metaKey) &&
        event.key.toLowerCase() === 's' &&
        view === 'review'
      ) {
        event.preventDefault();
        if (!busy) void savePage(false);
      }
    };
    document.addEventListener('keydown', listener);
    return () => document.removeEventListener('keydown', listener);
  });

  async function openImport() {
    setModal('import');
    setSourceLoading(true);
    try {
      setSources(await api.sources());
    } catch (error) {
      fail(error);
    } finally {
      setSourceLoading(false);
    }
  }
  async function syncFolder() {
    setBusy(true);
    try {
      const result = await api.syncSources();
      setWorkspace(result);
      setBookId((current) =>
        result.books.some((book) => book.id === current) ? current : result.books[0]?.id || '',
      );
      if (modal === 'import') setSources(await api.sources());
      notify(
        `Đã quét thư mục: ${result.books.length} sách PDF${result.source_errors.length ? `, ${result.source_errors.length} file cần kiểm tra` : ''}.`,
      );
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  async function importFile(file: string | File) {
    setBusy(true);
    try {
      const book = typeof file === 'string' ? await api.importSource(file) : await api.upload(file);
      await loadWorkspace();
      setBookId(book.id);
      setView('review');
      setModal(null);
      notify(`Đã nhập ${book.pages} trang. Phân loại trang để bắt đầu hiệu đính.`);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  function selectBook(book: Book, nextView: View = 'review') {
    if (book.id !== bookId) {
      void saveBookDrafts().catch(fail);
      if (rowsDirty) {
        clearTimeout(alignmentTimers.current.get(bookId));
        void persistRows(bookId, rows).catch(fail);
      }
    }
    setBookId(book.id);
    setView(nextView);
  }
  function changeRows(next: Alignment[]) {
    setRows(next);
    rowsRef.current = next;
    setRowsDirty(true);
    queueRows(bookId, next);
    try {
      localStorage.setItem(`nom-alignment-${bookId}`, JSON.stringify(next));
    } catch {
      notify('Không lưu được bản nháp căn chỉnh trên trình duyệt. Hãy lưu ngay vào máy.', true);
    }
  }
  async function saveRows() {
    setBusy(true);
    try {
      clearTimeout(alignmentTimers.current.get(bookId));
      await persistRows(bookId, rows);
      await loadWorkspace();
      notify('Đã lưu các cặp căn chỉnh vào máy.');
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  function newRow(source = '', target = '') {
    const sourcePage =
      pages.find((p) => p.id === alignmentPage) || pages.find((p) => p.category === 'ch');
    if (!sourcePage || !activeBook) {
      notify('Cần phân loại ít nhất một trang Hán Nôm trước khi tạo cặp.', true);
      return;
    }
    const prefix = `${activeBook.name}.${String(sourcePage.number).padStart(3, '0')}.`;
    const sequence =
      Math.max(
        0,
        ...rows
          .filter((r) => r.sentence_id.startsWith(prefix))
          .map((r) => Number(r.sentence_id.slice(prefix.length)) || 0),
      ) + 1;
    changeRows([
      ...rows,
      {
        id: crypto.randomUUID(),
        sentence_id: prefix + sequence,
        source,
        target,
        reviewed: false,
      },
    ]);
  }
  async function download(format: 'csv' | 'xlsx' | 'labels') {
    if (!activeBook) return;
    if (format === 'labels' && pages.some((p) => drafts[p.id])) {
      notify('Hãy lưu các bản nháp trang vào máy trước khi xuất nhãn.', true);
      return;
    }
    try {
      if (format !== 'labels' && localStorage.getItem(`nom-alignment-${bookId}`)) {
        notify('Hãy lưu căn chỉnh vào máy trước khi xuất CSV hoặc Excel.', true);
        return;
      }
    } catch {
      /* Browser storage may be unavailable; the server export remains usable. */
    }
    setBusy(true);
    try {
      const response = await fetch(api.exportUrl(bookId, format));
      if (!response.ok) {
        const error = await response.json();
        throw new Error(error.detail);
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = `${activeBook.name}${format === 'labels' ? '_labels.zip' : '.' + format}`;
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      notify('Đã xuất file. Bản sao cũng được lưu trong backend/data/output_alignment/.');
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className={`app-shell ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
      <aside id="main-sidebar" className="sidebar" aria-label="Thanh điều hướng">
        <a
          href="#"
          className="brand"
          onClick={(event) => {
            event.preventDefault();
            setView('overview');
          }}
          aria-label="Nôm, trang tổng quan"
        >
          <span className="brand-seal">文</span>
          <span className="brand-word">
            nôm<span className="brand-period">.</span>
            <small>KHÔNG GIAN NGỮ LIỆU</small>
          </span>
        </a>
        <div className="workspace-label">
          WORKSPACE <span>LOCAL</span>
        </div>
        <nav aria-label="Điều hướng chính">
          {nav.map((item) => (
            <button
              key={item.id}
              className={`nav-item ${view === item.id ? 'active' : ''}`}
              aria-label={item.label}
              title={item.label}
              onClick={() => setView(item.id)}
            >
              <item.icon size={19} strokeWidth={1.7} />
              <span>{item.label}</span>
              {item.id === 'review' && pendingCount > 0 && (
                <span className="nav-count">{pendingCount}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <button
            onClick={() => {
              setDictionarySelection(null);
              setDictionaryCharacter('');
            }}
          >
            <BookOpen size={18} />
            Tra từ điển
          </button>
          <button onClick={() => setModal('guide')}>
            <CircleHelp size={18} />
            Hướng dẫn sử dụng
            <ChevronRight size={15} />
          </button>
          <button onClick={() => setModal('settings')}>
            <Settings2 size={18} />
            Thiết lập không gian
          </button>
        </div>
      </aside>
      <div className="app-body">
        <header className="topbar">
          <div className="topbar-left">
            <button
              className="icon-button sidebar-toggle"
              aria-label={sidebarCollapsed ? 'Mở thanh điều hướng' : 'Thu gọn thanh điều hướng'}
              title={sidebarCollapsed ? 'Mở thanh điều hướng' : 'Thu gọn thanh điều hướng'}
              aria-expanded={!sidebarCollapsed}
              aria-controls="main-sidebar"
              onClick={toggleSidebar}
            >
              {sidebarCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
            </button>
            <div className="breadcrumb">
              <span>Không gian làm việc</span>
              <ChevronRight size={14} />
              <strong>{nav.find((n) => n.id === view)?.label}</strong>
            </div>
          </div>
          <div className="topbar-right">
            <span className="local-badge">
              <span />
              Lưu trữ cục bộ
            </span>
            <span className="header-divider" />
            <button
              className="icon-button"
              aria-label="Hướng dẫn"
              onClick={() => setModal('guide')}
            >
              <CircleHelp size={19} />
            </button>
            <span className="tiny-avatar">NC</span>
          </div>
        </header>
        <main>
          {connectionError ? (
            <div className="connection-state">
              <span className="empty-icon">
                <FolderOpen size={32} />
              </span>
              <h1>Kết nối không gian của bạn</h1>
              <p>Giao diện cần backend Python để đọc sách và lưu tiến trình.</p>
              <code>py run.py</code>
              <p className="muted">Chạy lệnh ở thư mục repo, sau đó thử kết nối lại.</p>
              <button className="primary-button" onClick={() => void loadWorkspace()}>
                <RotateCcw size={16} />
                Thử kết nối lại
              </button>
            </div>
          ) : !workspace ? (
            <div className="connection-state">
              <LoaderCircle className="spin" size={30} />
              <p>Đang mở không gian ngữ liệu…</p>
            </div>
          ) : (
            <>
              <div className="page-heading">
                <div>
                  <div className="eyebrow">SỐ HÓA DI SẢN · KẾT NỐI NGÔN NGỮ</div>
                  <h1>
                    {view === 'review'
                      ? 'Đọc lại từng nét chữ.'
                      : view === 'alignment'
                        ? 'Nối những dòng tri thức.'
                        : view === 'library'
                          ? 'Một tủ sách, nhiều di sản.'
                          : view === 'export'
                            ? 'Sẵn sàng cho hành trình tiếp theo.'
                            : 'Tiếp nối những trang sách xưa.'}
                  </h1>
                  <p>
                    {view === 'review'
                      ? 'Đối chiếu bản gốc, hiệu đính văn bản và hoàn thiện từng trang ngữ liệu.'
                      : view === 'alignment'
                        ? 'Đối chiếu Hán Nôm và Quốc ngữ theo từng đơn vị có ý nghĩa.'
                        : view === 'library'
                          ? 'Quản lý tài liệu gốc và tiếp tục từ lần hiệu đính gần nhất.'
                          : view === 'export'
                            ? 'Xuất nhãn và các cặp song ngữ theo đúng định dạng bàn giao.'
                            : 'Theo dõi tiến trình xây dựng kho ngữ liệu song song Hán Nôm – Quốc ngữ.'}
                  </p>
                </div>
                <button className="primary-button" onClick={() => void openImport()}>
                  <Plus size={17} />
                  Nhập tài liệu
                </button>
              </div>
              {!workspace.books.length && (
                <div className="info-banner">
                  <FolderOpen size={22} />
                  <div>
                    <strong>Chưa có sách trong thư mục nguồn</strong>
                    <p>
                      Đặt PDF vào backend/data/raw_data/ rồi quét lại. TXT cùng tên được dùng làm
                      nguồn Quốc ngữ đối chiếu.
                    </p>
                  </div>
                  <button
                    className="secondary-button"
                    disabled={busy}
                    onClick={() => void syncFolder()}
                  >
                    Quét thư mục
                  </button>
                </div>
              )}
              {!!workspace.source_errors.length && (
                <div className="source-errors" role="alert">
                  {workspace.source_errors.map((error) => (
                    <p key={error.filename}>
                      {error.filename}: {error.message}
                    </p>
                  ))}
                </div>
              )}
              {workspace.pair_stats ? (
                <PairProgress stats={workspace.pair_stats} onImport={() => void openImport()} />
              ) : (
                <p className="stats-refresh-notice">
                  Khởi động lại backend để cập nhật bộ đếm cặp câu.
                </p>
              )}
              {(view === 'review' || view === 'alignment' || view === 'export') && (
                <>
                  <div className="book-context">
                    <div className="book-context-icon">
                      <BookOpen size={23} strokeWidth={1.5} />
                    </div>
                    <div className="book-selector">
                      <label htmlFor="book-select">TÀI LIỆU ĐANG LÀM VIỆC</label>
                      <div>
                        <select
                          id="book-select"
                          value={bookId}
                          onChange={(event) => {
                            const next = workspace.books.find((b) => b.id === event.target.value);
                            if (next) selectBook(next, view);
                          }}
                        >
                          {workspace.books.map((book) => (
                            <option key={book.id} value={book.id}>
                              {book.name}
                            </option>
                          ))}
                        </select>
                        <ChevronDown size={15} />
                      </div>
                    </div>
                    <div className="context-stats">
                      <span>
                        <strong>{pages.length}</strong> trang
                      </span>
                      <span>
                        <strong>{doneCount}</strong> đã duyệt
                      </span>
                      <div className="context-progress">
                        <div>
                          <span>Tiến trình duyệt trang</span>
                          <strong>{progress}%</strong>
                        </div>
                        <div className="progress-track">
                          <span style={{ width: `${progress}%` }} />
                        </div>
                      </div>
                    </div>
                  </div>
                  <div className="pipeline">
                    <button onClick={() => setView('library')} className="completed">
                      <span>
                        <Check size={13} />
                      </span>
                      Nhập & phân loại
                    </button>
                    <div className="pipeline-line" />
                    <button
                      className={view === 'review' ? 'current' : ''}
                      onClick={() => setView('review')}
                    >
                      <span>02</span>Hiệu đính OCR
                    </button>
                    <div className="pipeline-line" />
                    <button
                      className={view === 'alignment' ? 'current' : ''}
                      onClick={() => setView('alignment')}
                    >
                      <span>03</span>Căn chỉnh song ngữ
                    </button>
                    <div className="pipeline-line" />
                    <button
                      className={view === 'export' ? 'current' : ''}
                      onClick={() => setView('export')}
                    >
                      <span>04</span>Xuất dữ liệu
                    </button>
                  </div>
                </>
              )}
              {view === 'review' && (
                <>
                  {activeBook && (
                    <BookOCRPanel
                      key={bookId}
                      bookId={bookId}
                      pages={pages}
                      referenceFile={activeBook.reference_file}
                      ready={workspace.ocr_ready}
                      viReady={workspace.vietnamese_ocr?.ready || false}
                      viEngine={workspace.vietnamese_ocr?.engine}
                      disabled={busy || loadingPages}
                      beforeStart={saveBookDrafts}
                      onOpenPage={(id) => {
                        setCategory('all');
                        setStatus('all');
                        setPageSearch('');
                        setPageId(id);
                      }}
                      onJob={setBookJob}
                      onRefresh={() => void refreshBookPages()}
                      onError={fail}
                    />
                  )}
                  {activeBook && (
                    <BookLayoutPanel
                      key={bookId}
                      bookId={bookId}
                      page={page}
                      box={draft?.boxes.find((box) => box.id === selectedBox)}
                      disabled={busy}
                      onSaved={() => void refreshBookPages()}
                      onError={fail}
                    />
                  )}
                  <section className="review-workspace" aria-label="Không gian hiệu đính">
                    <div className="workspace-toolbar">
                      <div className="language-tabs" role="group" aria-label="Nhóm trang">
                        <button
                          className={category === 'ch' ? 'selected' : ''}
                          onClick={() => chooseCategory('ch')}
                        >
                          <span className="han-character">文</span>Hán Nôm
                          <span>{pages.filter((p) => p.category === 'ch').length}</span>
                        </button>
                        <button
                          className={category === 'vi' ? 'selected' : ''}
                          onClick={() => chooseCategory('vi')}
                        >
                          <span className="vi-character">Aa</span>Quốc ngữ
                          <span>{pages.filter((p) => p.category === 'vi').length}</span>
                        </button>
                        <select
                          aria-label="Các nhóm trang khác"
                          value={category !== 'ch' && category !== 'vi' ? category : ''}
                          onChange={(event) => chooseCategory(event.target.value)}
                        >
                          <option value="" disabled>
                            Nhóm khác
                          </option>
                          <option value="all">Tất cả trang</option>
                          {Object.entries(categories)
                            .filter(([key]) => key !== 'ch' && key !== 'vi')
                            .map(([key, label]) => (
                              <option key={key} value={key}>
                                {label}
                              </option>
                            ))}
                        </select>
                      </div>
                      <div className="pending-label">
                        <span />
                        {pendingCount} trang chờ duyệt
                      </div>
                    </div>
                    <div className="review-grid">
                      <aside className="page-navigator">
                        <div className="panel-title">
                          <span>
                            Các trang <small>{filteredPages.length}</small>
                          </span>
                          <PanelLeftClose size={15} />
                        </div>
                        <div className="page-filter">
                          <SlidersHorizontal size={13} />
                          <select
                            value={status}
                            aria-label="Lọc trạng thái"
                            onChange={(event) => setStatus(event.target.value)}
                          >
                            <option value="all">Tất cả trạng thái</option>
                            <option value="pending">Chờ duyệt</option>
                            <option value="done">Đã hoàn thành</option>
                          </select>
                        </div>
                        <label className="page-search">
                          <Search size={13} />
                          <input
                            aria-label="Tìm số trang"
                            placeholder="Tìm số trang…"
                            value={pageSearch}
                            onChange={(event) => setPageSearch(event.target.value)}
                          />
                        </label>
                        <div className="thumbnails">
                          {loadingPages ? (
                            <LoaderCircle className="spin" size={22} />
                          ) : filteredPages.length ? (
                            filteredPages.map((p) => (
                              <button
                                key={p.id}
                                className={`thumbnail-card ${p.id === pageId ? 'selected' : ''}`}
                                onClick={() => setPageId(p.id)}
                                aria-label={`Mở trang ${p.number}, ${categories[p.category]}`}
                              >
                                <div className="thumbnail-image">
                                  <img
                                    loading="lazy"
                                    src={`${p.image_url}?thumbnail=true`}
                                    alt={`Bản quét trang ${p.number}`}
                                  />
                                  {p.status === 'done' && (
                                    <span className="thumb-done">
                                      <Check size={12} />
                                    </span>
                                  )}
                                  {drafts[p.id] && (
                                    <span className="thumb-draft" title="Có bản nháp" />
                                  )}
                                </div>
                                <div>
                                  <span>Trang {String(p.number).padStart(3, '0')}</span>
                                  <small>
                                    {p.ocr_skip || p.category === 'blank'
                                      ? 'Bỏ qua OCR'
                                      : p.source_text && p.target_text
                                        ? 'Có đủ hai nội dung'
                                        : p.source_text || p.target_text
                                          ? 'Có kết quả một phần'
                                          : bookJob?.pages.find((item) => item.page_id === p.id)
                                                ?.status === 'running'
                                            ? 'Đang OCR'
                                            : 'Chờ xử lý'}
                                  </small>
                                  <span className={`status-dot ${p.status}`} />
                                </div>
                              </button>
                            ))
                          ) : (
                            <div className="small-empty">
                              <FileText size={23} />
                              <p>
                                Không có trang
                                <br />
                                trong bộ lọc này.
                              </p>
                            </div>
                          )}
                        </div>
                        <div className="navigator-footer">
                          <ShieldCheck size={12} />
                          Tiến trình lưu trên máy
                        </div>
                      </aside>
                      {page && draft ? (
                        <>
                          <div className="image-panel">
                            <div className="image-toolbar">
                              <span>
                                <FileText size={14} />
                                <strong>{String(page.number).padStart(3, '0')}</strong>
                                <span className="muted">/ {pages.length} trang</span>
                              </span>
                              <div className="image-controls">
                                <button
                                  className={`icon-button ${tool === 'select' ? 'is-active' : ''}`}
                                  aria-label="Chọn và di chuyển vùng"
                                  title="Chọn và di chuyển vùng"
                                  onClick={() => setTool('select')}
                                >
                                  <MousePointer2 size={16} />
                                </button>
                                <button
                                  className={`icon-button ${tool === 'draw' ? 'is-active' : ''}`}
                                  aria-label="Vẽ vùng mới"
                                  title="Vẽ vùng mới"
                                  onClick={() => {
                                    setTool('draw');
                                    setShowBoxes(true);
                                  }}
                                >
                                  <SquareDashedMousePointer size={17} />
                                </button>
                                <span className="toolbar-divider" />
                                <button
                                  className="icon-button"
                                  aria-label={showBoxes ? 'Ẩn vùng chữ' : 'Hiện vùng chữ'}
                                  onClick={() => setShowBoxes(!showBoxes)}
                                >
                                  {showBoxes ? <Eye size={17} /> : <EyeOff size={17} />}
                                </button>
                                <button
                                  className="icon-button"
                                  aria-label="Vừa khung hình"
                                  onClick={() => setZoom(100)}
                                >
                                  <Maximize2 size={16} />
                                </button>
                              </div>
                            </div>
                            <ManuscriptViewer
                              page={page}
                              boxes={draft.boxes}
                              selected={selectedBox}
                              setSelected={setSelectedBox}
                              showBoxes={showBoxes}
                              tool={tool}
                              zoom={zoom}
                              onBoxes={(boxes) => updateDraft({ boxes })}
                              onDrawn={() => setTool('select')}
                            />
                            <div className="image-footer">
                              <span>
                                <MousePointer2 size={13} />
                                {tool === 'draw'
                                  ? 'Kéo trên ảnh để tạo vùng chữ'
                                  : 'Chọn vùng · Kéo để chỉnh vị trí'}
                              </span>
                              <div>
                                <button
                                  className="icon-button"
                                  aria-label="Thu nhỏ"
                                  onClick={() => setZoom(Math.max(50, zoom - 25))}
                                >
                                  <Minus size={14} />
                                </button>
                                <span>{zoom}%</span>
                                <button
                                  className="icon-button"
                                  aria-label="Phóng to"
                                  onClick={() => setZoom(Math.min(200, zoom + 25))}
                                >
                                  <Plus size={14} />
                                </button>
                              </div>
                            </div>
                          </div>
                          <aside className="transcription-panel">
                            <div className="panel-title">
                              <span>
                                Văn bản nhận dạng <small>{draft.boxes.length} vùng</small>
                              </span>
                              <button
                                className="icon-button"
                                aria-label="Thêm vùng văn bản"
                                title="Vẽ thêm vùng trên bản quét"
                                onClick={() => {
                                  setTool('draw');
                                  setShowBoxes(true);
                                }}
                              >
                                <Plus size={17} />
                              </button>
                            </div>
                            <div className="editor-notice">
                              <span />
                              {workspace.ocr_ready
                                ? 'OCR đã cấu hình · đọc lại trước khi hoàn thành'
                                : 'OCR chưa cấu hình · có thể hiệu đính thủ công'}
                            </div>
                            <div className="transcription-list">
                              <div className="page-text-editor">
                                {pageOCR?.warnings.map((warning, index) => (
                                  <p key={index} className="reference-draft-note">
                                    {warning}
                                  </p>
                                ))}
                                <p role="status">
                                  {autosaveState} ·{' '}
                                  {page.ocr_skip || page.category === 'blank'
                                    ? 'Trang đã chọn bỏ qua OCR'
                                    : bookJob?.pages.find((p) => p.page_id === page.id)?.status ===
                                        'running'
                                      ? 'Đang xử lý trang này'
                                      : page.source_text || page.target_text
                                        ? 'Đã có nội dung để hiệu đính'
                                        : 'Đang chờ OCR theo quyển'}
                                </p>
                                <label>
                                  Hán / Nôm · đối chiếu với ảnh bên cạnh
                                  <textarea
                                    className="han-text"
                                    aria-label="Văn bản Nôm toàn trang"
                                    rows={6}
                                    disabled={busy}
                                    value={draft.source_text}
                                    onChange={(event) =>
                                      updateDraft({ source_text: event.target.value })
                                    }
                                    onBlur={() => void saveDraftNow(page.id).catch(fail)}
                                    placeholder="OCR Nôm sẽ điền văn bản ở đây; có thể sửa trực tiếp."
                                  />
                                </label>
                                <button
                                  className="secondary-button"
                                  disabled={busy}
                                  onClick={() =>
                                    void saveDraftNow(page.id)
                                      .then(() => notify('Đã lưu nội dung hiện tại của trang.'))
                                      .catch(fail)
                                  }
                                >
                                  Lưu Hán / Nôm hiện tại
                                </button>
                                <CharacterStrip
                                  text={draft.source_text || ''}
                                  onLookup={(character, index) => {
                                    setDictionarySelection({
                                      pageId: page.id,
                                      boxId: 'page-source',
                                      index,
                                      character,
                                    });
                                    setDictionaryCharacter(character);
                                  }}
                                />
                                <label>
                                  Quốc ngữ · đối chiếu với cùng ảnh
                                  <textarea
                                    aria-label="Văn bản Quốc ngữ toàn trang"
                                    rows={6}
                                    disabled={busy}
                                    value={draft.target_text}
                                    onChange={(event) =>
                                      updateDraft({ target_text: event.target.value })
                                    }
                                    onBlur={() => void saveDraftNow(page.id).catch(fail)}
                                    placeholder="OCR Quốc ngữ lấy trực tiếp từ cùng ảnh, không cần tạo bản sao trang."
                                  />
                                </label>
                                {page.target_origin?.startsWith('txt-draft:') && (
                                  <p className="reference-draft-note">
                                    Bản ghép nháp từ TXT: {page.target_origin.slice(10)}. Duyệt lại
                                    đoạn và tách/gộp khi căn chỉnh.
                                  </p>
                                )}
                                <button
                                  className="secondary-button"
                                  disabled={busy}
                                  onClick={() =>
                                    void saveDraftNow(page.id)
                                      .then(() => notify('Đã lưu nội dung hiện tại của trang.'))
                                      .catch(fail)
                                  }
                                >
                                  Lưu Quốc ngữ hiện tại
                                </button>
                                <p>
                                  Hai văn bản được lưu tự động khi sửa. Duyệt xong trang rồi căn
                                  chỉnh để tạo các cặp ngữ liệu.
                                </p>
                              </div>
                              <details className="optional-box-editor">
                                <summary>
                                  Box tùy chọn · {draft.boxes.length} vùng Nôm /{' '}
                                  {draft.vi_boxes?.length || 0} vùng Quốc ngữ
                                </summary>
                                {!!pageOCR?.boxes.length && (
                                  <button
                                    className="secondary-button"
                                    onClick={() =>
                                      updateDraft({
                                        boxes: pageOCR.boxes,
                                        vi_boxes: pageOCR.vi_boxes || [],
                                      })
                                    }
                                  >
                                    Lấy box đã phát hiện (tùy chọn, không chạy lại OCR)
                                  </button>
                                )}
                                {draft.boxes.length ? (
                                  draft.boxes.map((box, index) => (
                                    <div
                                      key={box.id}
                                      className={`transcription-card ${selectedBox === box.id ? 'selected' : ''}`}
                                      onClick={() => setSelectedBox(box.id)}
                                    >
                                      <div className="transcription-label">
                                        <span>
                                          <GripVertical size={12} />
                                          <b>{String(index + 1).padStart(2, '0')}</b>
                                          <span>
                                            {draft.category === 'ch' &&
                                            (draft.reading_direction ?? page.reading_direction) ===
                                              1
                                              ? 'Cột dọc'
                                              : 'Vùng chữ'}
                                          </span>
                                        </span>
                                        <button
                                          className="icon-button"
                                          aria-label={`Xóa vùng ${index + 1}`}
                                          onClick={(event) => {
                                            event.stopPropagation();
                                            updateDraft({
                                              boxes: draft.boxes.filter((b) => b.id !== box.id),
                                            });
                                            if (selectedBox === box.id) setSelectedBox(null);
                                          }}
                                        >
                                          <Trash2 size={13} />
                                        </button>
                                      </div>
                                      <textarea
                                        className={draft.category === 'ch' ? 'han-text' : ''}
                                        aria-label={`Văn bản vùng ${index + 1}`}
                                        rows={draft.category === 'ch' ? 2 : 3}
                                        value={box.transcription}
                                        placeholder="Nhập văn bản trong vùng…"
                                        onFocus={() => setSelectedBox(box.id)}
                                        onChange={(event) =>
                                          updateDraft({
                                            boxes: draft.boxes.map((b) =>
                                              b.id === box.id
                                                ? { ...b, transcription: event.target.value }
                                                : b,
                                            ),
                                          })
                                        }
                                      />
                                      <CharacterStrip
                                        text={box.transcription}
                                        onLookup={(character, index) => {
                                          setSelectedBox(box.id);
                                          setDictionarySelection({
                                            pageId: page.id,
                                            boxId: box.id,
                                            index,
                                            character,
                                          });
                                          setDictionaryCharacter(character);
                                        }}
                                      />
                                      <div className="transcription-meta">
                                        <span>{box.transcription.length} ký tự</span>
                                        <span>Tra từng chữ để đối chiếu</span>
                                      </div>
                                    </div>
                                  ))
                                ) : (
                                  <div className="editor-empty">
                                    <Boxes size={30} />
                                    <h3>Chưa có box — vẫn sửa và lưu văn bản được</h3>
                                    <p>
                                      Chỉ vẽ khi muốn giới hạn vùng đọc hoặc chỉnh nhãn tọa độ. Có
                                      thể lưu vùng mẫu cho cả quyển.
                                    </p>
                                    <button
                                      className="secondary-button"
                                      onClick={() => {
                                        setTool('draw');
                                        setShowBoxes(true);
                                      }}
                                    >
                                      <Plus size={15} />
                                      Vẽ vùng đầu tiên
                                    </button>
                                  </div>
                                )}
                              </details>
                            </div>
                            <div className="editor-bottom">
                              <label htmlFor="category-select">PHÂN LOẠI TRANG</label>
                              <select
                                id="category-select"
                                value={draft.category}
                                onChange={(event) =>
                                  updateDraft({ category: event.target.value as Category })
                                }
                              >
                                {Object.entries(categories).map(([key, label]) => (
                                  <option key={key} value={key}>
                                    {label}
                                  </option>
                                ))}
                              </select>
                              <label>
                                <input
                                  type="checkbox"
                                  checked={draft.ocr_skip || false}
                                  onChange={(e) => updateDraft({ ocr_skip: e.target.checked })}
                                />
                                Bỏ qua trang khi OCR sách
                              </label>
                              <div className="editor-extra-actions">
                                <button
                                  disabled={!drafts[page.id]}
                                  title="Khôi phục bản đã lưu gần nhất"
                                  onClick={() => {
                                    setDrafts((previous) => {
                                      const next = { ...previous };
                                      delete next[page.id];
                                      try {
                                        localStorage.setItem('nom-drafts-v1', JSON.stringify(next));
                                      } catch {}
                                      return next;
                                    });
                                    setSelectedBox(null);
                                  }}
                                  aria-label="Khôi phục bản đã lưu"
                                >
                                  <RotateCcw size={12} />
                                </button>
                              </div>
                              <div className="dictionary-status">
                                <CircleHelp size={13} />
                                {workspace.dictionary.ready
                                  ? 'Từ điển tại máy · bấm chữ để tra'
                                  : 'Cài từ điển: py backend/setup_dictionary.py'}
                              </div>
                            </div>
                          </aside>
                        </>
                      ) : (
                        <div className="no-page">
                          <BookOpen size={38} />
                          <h3>
                            {loadingPages ? 'Đang tải tài liệu…' : 'Chọn một trang để bắt đầu'}
                          </h3>
                          <p>Chọn nhóm trang và bản quét ở cột bên trái.</p>
                        </div>
                      )}
                    </div>
                    <div className="workspace-actions">
                      <span className="save-state">
                        {page && drafts[page.id] ? (
                          <>
                            <span className="draft-state-dot" />
                            Bản nháp trên trình duyệt
                          </>
                        ) : (
                          <>
                            <CheckCheck size={15} />
                            Đã lưu vào máy
                          </>
                        )}
                        <small>Ctrl + S để lưu</small>
                      </span>
                      <div>
                        <button
                          className="secondary-button"
                          disabled={!page || busy}
                          onClick={() => void savePage(false)}
                        >
                          <Save size={15} />
                          Lưu bản nháp
                        </button>
                        <button
                          className="primary-button"
                          disabled={!page || busy}
                          onClick={() => void savePage(true)}
                        >
                          {busy ? <LoaderCircle size={16} className="spin" /> : <Check size={16} />}
                          Hoàn thành & tiếp theo
                          <ArrowRight size={16} />
                        </button>
                      </div>
                    </div>
                  </section>
                  <div className="workspace-caption">
                    <span>
                      <ShieldCheck size={14} />
                      Tài liệu và bản hiệu đính được lưu cục bộ trên máy của bạn.
                    </span>
                    <button onClick={() => setModal('guide')}>
                      Quy tắc hiệu đính
                      <ArrowRight size={13} />
                    </button>
                  </div>
                </>
              )}
              {view === 'overview' && (
                <>
                  <div className="stats-grid">
                    <Stat
                      icon={<Library size={21} />}
                      value={workspace.books.length}
                      label="Tài liệu đã nhập"
                      detail="PDF trong thư mục nguồn"
                    />
                    <Stat
                      icon={<FileText size={21} />}
                      value={workspace.books.reduce((n, b) => n + b.pages, 0)}
                      label="Trang trong không gian"
                      detail="Các trang PDF đã nhập"
                    />
                    <Stat
                      icon={<FileCheck2 size={21} />}
                      value={workspace.books.reduce((n, b) => n + b.done, 0)}
                      label="Trang đã hoàn thành"
                      detail="Được người hiệu đính xác nhận"
                    />
                    <Stat
                      icon={<Link2 size={21} />}
                      value="—"
                      label="Độ tương đồng"
                      detail="Chưa có phép đánh giá tự động"
                    />
                  </div>
                  <div className="section-heading">
                    <div>
                      <h2>Tiếp tục công việc</h2>
                      <p>Mở một tài liệu để tiếp tục hiệu đính.</p>
                    </div>
                    <button className="text-button" onClick={() => setView('library')}>
                      Xem tủ sách
                      <ArrowRight size={15} />
                    </button>
                  </div>
                  <div className="book-grid">
                    {workspace.books.map((book) => (
                      <BookCard key={book.id} book={book} onOpen={() => selectBook(book)} />
                    ))}
                  </div>
                  <div className="info-banner">
                    <BookOpen size={23} />
                    <div>
                      <strong>Từ bản quét đến ngữ liệu song song</strong>
                      <p>
                        Phân loại đầy đủ trang có bản dịch, hiệu đính theo thứ tự đọc và căn chỉnh
                        trước khi xuất. Mục tiêu chất lượng theo yêu cầu gốc: ≥95% tương đồng.
                      </p>
                    </div>
                    <button className="secondary-button" onClick={() => setModal('guide')}>
                      Xem quy trình
                      <ArrowRight size={15} />
                    </button>
                  </div>
                </>
              )}
              {view === 'library' && (
                <>
                  <div className="section-toolbar">
                    <label className="search-input">
                      <Search size={17} />
                      <input
                        aria-label="Tìm trong tủ sách"
                        placeholder="Tìm tài liệu trong tủ sách…"
                        value={librarySearch}
                        onChange={(event) => setLibrarySearch(event.target.value)}
                      />
                    </label>
                    <span className="muted">
                      {workspace.books.length} tài liệu trong không gian
                    </span>
                    <button
                      className="secondary-button"
                      disabled={busy}
                      onClick={() => void syncFolder()}
                    >
                      <RotateCcw size={15} />
                      Quét lại thư mục
                    </button>
                  </div>
                  <div className="book-grid">
                    {workspace.books
                      .filter((book) =>
                        book.name.toLowerCase().includes(librarySearch.toLowerCase()),
                      )
                      .map((book) => (
                        <BookCard key={book.id} book={book} onOpen={() => selectBook(book)} />
                      ))}
                    <button className="new-book-card" onClick={() => void openImport()}>
                      <Plus size={26} />
                      <strong>Thêm một cuốn sách</strong>
                      <span>PDF từ máy hoặc backend/data/raw_data/</span>
                    </button>
                  </div>
                  <div className="info-banner">
                    <ShieldCheck size={22} />
                    <div>
                      <strong>Nguồn gốc được giữ nguyên</strong>
                      <p>
                        Tên sách theo đúng tên PDF. Trang được đánh số từ 001; các bản Hán Nôm và
                        Quốc ngữ có thể dùng chung ảnh nguồn.
                      </p>
                    </div>
                  </div>
                </>
              )}
              {view === 'alignment' && (
                <section className="alignment-workspace">
                  <div className="alignment-top">
                    <div>
                      <h2>
                        <Link2 size={19} />
                        Cặp ngữ liệu song song <span className="count-badge">{rows.length}</span>
                      </h2>
                      <p>Gộp các hàng liên tiếp, hoặc tách tại một ranh giới ngữ nghĩa.</p>
                    </div>
                    <div className="button-group">
                      <select
                        aria-label="Trang nguồn cho cặp mới"
                        value={alignmentPage}
                        onChange={(event) => setAlignmentPage(event.target.value)}
                      >
                        <option value="">Chọn trang Nôm</option>
                        {pages
                          .filter((p) => p.category === 'ch')
                          .map((p) => (
                            <option key={p.id} value={p.id}>
                              Trang {String(p.number).padStart(3, '0')}
                            </option>
                          ))}
                      </select>
                      <button className="secondary-button" disabled={busy} onClick={() => newRow()}>
                        <Plus size={15} />
                        Thêm cặp
                      </button>
                      <button
                        className="primary-button"
                        disabled={busy || !rowsDirty}
                        onClick={() => void saveRows()}
                      >
                        <Save size={15} />
                        Lưu căn chỉnh
                      </button>
                    </div>
                  </div>
                  {!alignmentLoading && (
                    <AlignmentSources
                      key={`${bookId}-${alignmentPage || pages.find((p) => p.category === 'ch')?.id || ''}`}
                      page={
                        pages.find((p) => p.id === alignmentPage) ||
                        pages.find((p) => p.category === 'ch')
                      }
                      pages={pages}
                      reference={reference}
                      busy={busy}
                      onCreate={newRow}
                    />
                  )}
                  <div className="alignment-notice">
                    <CircleHelp size={16} />
                    <span>
                      Từ điển hỗ trợ tra từng chữ khi hiệu đính. Độ tương đồng của các cặp chưa được
                      đánh giá tự động; đánh dấu đã đọc không xác nhận tương đồng ngữ nghĩa.
                    </span>
                  </div>
                  <div className="alignment-head">
                    <span>ID CÂU</span>
                    <span>
                      <b>文</b> HÁN NÔM
                    </span>
                    <span>
                      <b>Aa</b> QUỐC NGỮ
                    </span>
                    <span>THAO TÁC</span>
                  </div>
                  {alignmentLoading ? (
                    <div className="empty-section">
                      <LoaderCircle className="spin" size={24} />
                    </div>
                  ) : rows.length ? (
                    <div className="alignment-rows">
                      {rows.map((row, index) => (
                        <AlignmentRow
                          key={row.id}
                          row={row}
                          index={index}
                          total={rows.length}
                          onChange={(updated) =>
                            changeRows(rows.map((r) => (r.id === row.id ? updated : r)))
                          }
                          onRemove={() => changeRows(rows.filter((r) => r.id !== row.id))}
                          onMerge={() => {
                            const next = rows[index + 1];
                            if (!next) return;
                            changeRows(
                              rows.flatMap((r, i) =>
                                i === index
                                  ? [
                                      {
                                        ...row,
                                        source: row.source + next.source,
                                        target: row.target + ' ' + next.target,
                                        reviewed: false,
                                      },
                                    ]
                                  : i === index + 1
                                    ? []
                                    : [r],
                              ),
                            );
                          }}
                          onSplit={(source, target) => {
                            const match = row.sentence_id.match(/^(.*\.)(\d+)$/);
                            if (!match) return;
                            const prefix = match[1];
                            const sequence =
                              Math.max(
                                0,
                                ...rows
                                  .filter((r) => r.sentence_id.startsWith(prefix))
                                  .map((r) => Number(r.sentence_id.slice(prefix.length)) || 0),
                              ) + 1;
                            changeRows(
                              rows.flatMap((r) =>
                                r.id === row.id
                                  ? [
                                      {
                                        ...r,
                                        source: source[0],
                                        target: target[0],
                                        reviewed: false,
                                      },
                                      {
                                        ...r,
                                        id: crypto.randomUUID(),
                                        sentence_id: prefix + sequence,
                                        source: source[1],
                                        target: target[1],
                                        reviewed: false,
                                      },
                                    ]
                                  : [r],
                              ),
                            );
                          }}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="empty-section">
                      <Link2 size={34} />
                      <h3>Chưa có cặp căn chỉnh</h3>
                      <p>Chọn một trang Hán Nôm và thêm cặp văn bản tương ứng.</p>
                      <button className="secondary-button" onClick={() => newRow()}>
                        <Plus size={15} />
                        Tạo cặp đầu tiên
                      </button>
                    </div>
                  )}
                  <div className="alignment-footer">
                    <span>
                      <span className="status-dot pending" />
                      {rows.filter((r) => !r.reviewed).length} cặp chưa đọc lại
                    </span>
                    <span>
                      {rowsDirty ? 'Có bản nháp chưa lưu vào máy' : 'Đã lưu vào máy'} · Xuất đúng 4
                      cột theo yêu cầu
                    </span>
                  </div>
                </section>
              )}
              {view === 'export' && (
                <>
                  <div className="export-intro">
                    <span className="empty-icon">
                      <Download size={26} />
                    </span>
                    <div>
                      <h2>Gói dữ liệu của {activeBook?.name}</h2>
                      <p>
                        {pendingCount
                          ? `${pendingCount} trang chưa hoàn thành. Có thể xuất bản làm việc để kiểm tra định dạng.`
                          : 'Các trang đã được duyệt. Kiểm tra căn chỉnh và chất lượng trước khi bàn giao.'}
                      </p>
                    </div>
                  </div>
                  <div className="book-ocr-panel">
                    <h3>Kết quả và nhật ký được cập nhật tự động</h3>
                    <p>
                      Thống kê đếm cặp căn chỉnh đã lưu; OCR xong không tự tạo cặp. Các file dưới
                      đây phục vụ đối chiếu tiến trình và tổng hợp cuối cùng.
                    </p>
                    <div className="button-group">
                      {(
                        [
                          'summary.json',
                          'pages.json',
                          'alignments.json',
                          'pairs.csv',
                          'events.jsonl',
                        ] as const
                      ).map((file) => (
                        <a
                          className="secondary-button"
                          key={file}
                          href={api.resultUrl(bookId, file)}
                          download
                        >
                          {file}
                        </a>
                      ))}
                    </div>
                  </div>
                  <div className="export-grid">
                    {[
                      {
                        format: 'csv',
                        title: 'Ngữ liệu CSV',
                        description:
                          'UTF-8 có BOM, 4 cột đúng định dạng. Mở bằng Excel hoặc dùng cho xử lý dữ liệu.',
                        label: '.CSV',
                        icon: FileText,
                      },
                      {
                        format: 'xlsx',
                        title: 'Bảng tính Excel',
                        description:
                          'Giữ nguyên Unicode. Các cặp chưa được kiểm chứng ngữ nghĩa được tô đỏ để tiếp tục kiểm tra.',
                        label: '.XLSX',
                        icon: FileCheck2,
                      },
                      {
                        format: 'labels',
                        title: 'Nhãn PPOCRLabel',
                        description:
                          'Label.txt và fileState.txt theo từng nhóm. Gói nhãn này không bao gồm ảnh gốc.',
                        label: '.ZIP',
                        icon: Boxes,
                      },
                    ].map((item) => (
                      <div className="export-card" key={item.format}>
                        <div className="export-icon">
                          <item.icon size={27} />
                          <span>{item.label}</span>
                        </div>
                        <h3>{item.title}</h3>
                        <p>{item.description}</p>
                        <button
                          className="secondary-button"
                          disabled={busy}
                          onClick={() => void download(item.format as 'csv' | 'xlsx' | 'labels')}
                        >
                          <Download size={15} />
                          Xuất {item.label}
                          <ArrowRight size={15} />
                        </button>
                      </div>
                    ))}
                  </div>
                  <div className="export-schema">
                    <h3>Cấu trúc ngữ liệu song song</h3>
                    <div>
                      {['img_id', 'sentence_id', 'SinoNom_Char', 'ChuQN_txt'].map((name, i) => (
                        <span key={name}>
                          <code>{name}</code>
                          <small>
                            {
                              [
                                'Tên ảnh, không kèm thư mục',
                                'Tên ảnh bỏ .jpg + thứ tự câu',
                                'Văn bản Hán Nôm',
                                'Văn bản Quốc ngữ',
                              ][i]
                            }
                          </small>
                        </span>
                      ))}
                    </div>
                  </div>
                  <div className="info-banner">
                    <CircleHelp size={22} />
                    <div>
                      <strong>Bản xuất làm việc chưa phải gói nộp đầy đủ</strong>
                      <p>
                        Gói bàn giao cuối cùng còn cần PDF gốc, ảnh JPG, báo cáo và mã nguồn. Độ
                        tương đồng ≥95% cần được đánh giá bằng từ điển và đối chiếu nội dung.
                      </p>
                    </div>
                    <button className="text-button" onClick={() => setView('alignment')}>
                      Kiểm tra căn chỉnh
                      <ArrowRight size={15} />
                    </button>
                  </div>
                </>
              )}
            </>
          )}
        </main>
        <footer className="app-footer">
          <span>
            NÔM WORKSPACE <span>v0.1</span>
          </span>
          <span>Một không gian cho những giá trị còn mãi.</span>
          <span>
            Hán Nôm <Link2 size={11} /> Quốc ngữ
          </span>
        </footer>
      </div>
      {toast && (
        <div
          role={toast.error ? 'alert' : 'status'}
          className={`toast ${toast.error ? 'error' : ''}`}
        >
          {toast.error ? <CircleHelp size={18} /> : <CheckCheck size={18} />}
          <span>{toast.message}</span>
          <button
            className="icon-button"
            aria-label="Đóng thông báo"
            onClick={() => setToast(null)}
          >
            <X size={16} />
          </button>
        </div>
      )}
      {dictionaryCharacter !== null && (
        <DictionaryPanel
          character={dictionaryCharacter}
          canReplace={!busy && !!dictionarySelection && dictionarySelection.pageId === page?.id}
          onReplace={replaceDictionaryCharacter}
          onClose={() => setDictionaryCharacter(null)}
        />
      )}
      <input
        ref={fileInput}
        type="file"
        accept=".pdf,application/pdf"
        hidden
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) void importFile(file);
          event.target.value = '';
        }}
      />
      {modal && (
        <div
          className="modal-backdrop"
          onClick={(event) => {
            if (event.target === event.currentTarget && !busy) setModal(null);
          }}
        >
          <section
            className={`modal ${modal === 'import' ? 'import-modal' : ''}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby="modal-title"
          >
            <div className="modal-header">
              <div>
                <div className="eyebrow">NÔM WORKSPACE</div>
                <h2 id="modal-title">
                  {modal === 'import'
                    ? 'Thêm tài liệu vào tủ sách'
                    : modal === 'guide'
                      ? 'Từng bước, trọn một trang sách.'
                      : 'Không gian trên máy của bạn'}
                </h2>
              </div>
              <button
                className="icon-button"
                aria-label="Đóng cửa sổ"
                disabled={busy}
                onClick={() => setModal(null)}
              >
                <X size={20} />
              </button>
            </div>
            {modal === 'import' ? (
              <>
                <button
                  className="upload-area"
                  disabled={busy}
                  onClick={() => fileInput.current?.click()}
                  onDragOver={(event) => event.preventDefault()}
                  onDrop={(event) => {
                    event.preventDefault();
                    const file = event.dataTransfer.files[0];
                    if (file && !busy) void importFile(file);
                  }}
                >
                  <span>
                    {busy ? <LoaderCircle className="spin" size={29} /> : <Upload size={29} />}
                  </span>
                  <strong>{busy ? 'Đang nhập tài liệu…' : 'Chọn hoặc kéo thả file PDF'}</strong>
                  <small>Tối đa 150 MB · Tệp được xử lý và lưu tại máy</small>
                </button>
                <div className="source-heading">
                  <strong>Thư mục backend/data/raw_data/</strong>
                  <button className="text-button" disabled={busy} onClick={() => void syncFolder()}>
                    Quét lại · {sources.length} PDF
                  </button>
                </div>
                <label className="search-input">
                  <Search size={16} />
                  <input
                    autoFocus
                    aria-label="Tìm PDF nguồn"
                    placeholder="Tìm theo tên file…"
                    value={sourceSearch}
                    onChange={(event) => setSourceSearch(event.target.value)}
                  />
                </label>
                <div className="source-list">
                  {sourceLoading ? (
                    <LoaderCircle className="spin" size={23} />
                  ) : (
                    sources
                      .filter((s) => s.name.toLowerCase().includes(sourceSearch.toLowerCase()))
                      .map((source) => (
                        <button
                          disabled={busy}
                          key={source.name}
                          onClick={() => {
                            const book = workspace?.books.find(
                              (book) => book.id === source.book_id,
                            );
                            if (book) {
                              selectBook(book);
                              setModal(null);
                            } else void importFile(source.name);
                          }}
                        >
                          <span className="source-file-icon">
                            <FileText size={20} />
                          </span>
                          <span>
                            <strong>{source.name}</strong>
                            <small>
                              PDF · {readableSize(source.bytes)}
                              {source.book_id ? ' · Đã có trong tủ sách' : ''}
                              {source.reference_file ? ' · Có TXT Quốc ngữ' : ''}
                            </small>
                          </span>
                          <Plus size={17} />
                        </button>
                      ))
                  )}
                  {!sourceLoading && !sources.length && (
                    <p className="muted">
                      Chưa có PDF trong backend/data/raw_data/. Bạn có thể tải file từ máy ở phía
                      trên.
                    </p>
                  )}
                </div>
                <p className="modal-note">
                  <ShieldCheck size={14} />
                  PDF gốc được lưu tại máy. Khi bấm Chạy OCR, ảnh trang được gửi tới Kim Hán Nôm.
                </p>
              </>
            ) : modal === 'guide' ? (
              <div className="guide-content">
                <p>
                  Luồng làm việc dựa trên tài liệu gốc <code>docs/Quy_định_đồ_án.pdf</code>.
                </p>
                {[
                  [
                    '01',
                    'Nhập và xác nhận phạm vi',
                    'Kiểm tra hai bản cùng nội dung; phân loại ch, vi, intro, ref, toc, blank hoặc misc. Trang có bản dịch vẫn phải được dóng hàng.',
                  ],
                  [
                    '02',
                    'Hiệu đính từng vùng chữ',
                    'Nôm dọc đọc phải → trái, trên → dưới. Quốc ngữ theo dòng. Mỗi box có 4 điểm; loại tiêu đề, số trang và chân trang. Kéo vùng để di chuyển, kéo điểm góc để chỉnh kích thước.',
                  ],
                  [
                    '03',
                    'Căn chỉnh có ý nghĩa',
                    'Ghép câu ngắt qua trang trước khi tách. Có thể gộp các hàng hoặc tách hai vế tại vị trí con trỏ. Không chia cơ học theo dấu câu.',
                  ],
                  [
                    '04',
                    'Lưu và kiểm tra bản xuất',
                    'Chọn sách, gắn nhãn và bỏ qua trang đặc biệt, rồi Lưu nhãn & OCR toàn bộ sách. Kết quả từng phần hiện dần để sửa và tra chữ. Văn bản/căn chỉnh tự lưu; mở lại sẽ khôi phục vị trí và tiếp tục phần OCR chưa xong. File kết quả tự cập nhật số cặp đã căn chỉnh.',
                  ],
                ].map(([number, title, description]) => (
                  <div className="guide-step" key={number}>
                    <span>{number}</span>
                    <div>
                      <h3>{title}</h3>
                      <p>{description}</p>
                    </div>
                  </div>
                ))}
                <div className="guide-callout">Mục tiêu ≥95% độ tương đồng dữ liệu.</div>
              </div>
            ) : (
              <div className="settings-content">
                <div>
                  <span>
                    <FolderOpen size={18} />
                    Kho tiến trình
                  </span>
                  <code>backend/data/.workspace/workspace.sqlite3</code>
                </div>
                <div>
                  <span>
                    <BookOpen size={18} />
                    PDF gốc
                  </span>
                  <code>backend/data/raw_data/</code>
                </div>
                <div>
                  <span>
                    <Boxes size={18} />
                    Ảnh và nhãn theo sách
                  </span>
                  <code>backend/data/.workspace/books/&lt;book_id&gt;/</code>
                </div>
                <div>
                  <span>
                    <Download size={18} />
                    Dữ liệu xuất
                  </span>
                  <code>backend/data/output_alignment/</code>
                </div>
                <div>
                  <span>
                    <ScanLine size={18} />
                    Nhận dạng OCR
                  </span>
                  <span className="pending-pill">
                    {workspace?.ocr_ready ? 'Đã cấu hình Kim Hán Nôm' : 'Thiếu KHN_token'}
                  </span>
                </div>
                <div>
                  <span>
                    <BookOpen size={18} />
                    Từ điển Hán Nôm
                  </span>
                  <span className="pending-pill">
                    {workspace?.dictionary.ready
                      ? 'Unihan tại máy đã sẵn sàng'
                      : 'Chưa cài dữ liệu'}
                  </span>
                </div>
                <div>
                  <span>
                    <FileText size={18} />
                    Font Hán Nôm
                  </span>
                  <span className="pending-pill">{nomFontStatus}</span>
                </div>
                <p className="muted">
                  Dữ liệu làm việc được bỏ qua trong Git. Mỗi máy đọc toàn bộ PDF trong thư mục
                  nguồn; TXT đối chiếu không được tính thành sách riêng.
                </p>
                <button
                  className="secondary-button"
                  onClick={() => {
                    setModal(null);
                    void loadWorkspace();
                  }}
                >
                  <RotateCcw size={15} />
                  Làm mới thông tin
                </button>
              </div>
            )}
          </section>
        </div>
      )}
    </div>
  );
}
