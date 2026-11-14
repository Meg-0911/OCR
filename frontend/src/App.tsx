import { useEffect, useMemo, useRef, useState } from 'react';
import {
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Boxes,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  CircleHelp,
  Download,
  FileCheck2,
  FileText,
  FolderOpen,
  LayoutDashboard,
  Library,
  Link2,
  LoaderCircle,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  RotateCcw,
  Save,
  ScanLine,
  Search,
  Settings2,
  SplitSquareVertical,
  Upload,
  X,
} from 'lucide-react';
import { api } from './api';
import AlignmentRow from './components/AlignmentRow';
import BookCard, { formatBookTitle } from './components/BookCard';
import Stat from './components/Stat';
import PairProgress from './components/PairProgress';
import AlignmentSources from './components/AlignmentSources';
import LinkedAlignmentWorkspace from './components/LinkedAlignmentWorkspace';
import BookWorkbench from './components/BookWorkbench';
import LibraryBookReader from './components/LibraryBookReader';
import DictionaryPanel from './components/DictionaryPanel';
import { draftPatch, patchDraft, afterAutomaticSave, type Draft } from './drafts';
import { replaceBoxText } from './components/boxText';
import { boxReviewKindAt, reviewColorsForAlignmentRows, reviewColorsForText } from './reviewColors';
import type {
  Alignment,
  Book,
  Box,
  Category,
  Page,
  ReviewKind,
  SourceFile,
  TextReference,
  Workspace,
  OCRJob,
  BookSession,
  OCRSettings,
} from './types';

type View = 'overview' | 'library' | 'review' | 'alignment' | 'export';
const nav = [
  { id: 'overview', label: 'Tổng quan', icon: LayoutDashboard },
  { id: 'library', label: 'Tủ sách', icon: Library },
  { id: 'review', label: 'Gán nhãn OCR', icon: ScanLine },
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

function reviewSummary(pages: Page[]) {
  let total = 0;
  let red = 0;
  for (const page of pages) {
    for (const box of page.boxes) {
      let characterIndex = 0;
      for (const char of box.transcription) {
        if (/\p{Script=Han}|\p{Co}|□/u.test(char)) {
          total++;
          const reviewKind = boxReviewKindAt(box, characterIndex);
          red += Number(reviewKind === 'mismatch' || reviewKind === 'unknown');
        }
        characterIndex++;
      }
    }
  }
  return { total, red, percent: total ? 100 * (1 - red / total) : null };
}

function validOCRRegionBox(box: Box, page: Page) {
  const points = box.points;
  if (!box.id || box.id.length > 100 || box.transcription.length > 30000 ||
      !Array.isArray(points) || points.length !== 4 || points.some((point) =>
        !Array.isArray(point) || point.length !== 2 ||
        !Number.isFinite(point[0]) || !Number.isFinite(point[1]) ||
        point[0] < 0 || point[1] < 0 || point[0] > page.width || point[1] > page.height,
      )) return false;
  const turns = points.map((point, index) => {
    const next = points[(index + 1) % 4];
    const after = points[(index + 2) % 4];
    return (next[0] - point[0]) * (after[1] - next[1]) -
      (next[1] - point[1]) * (after[0] - next[0]);
  });
  return turns.every((turn) => turn > 0) || turns.every((turn) => turn < 0);
}

function alignmentReviewColors(rows: Alignment[], pages: Page[]) {
  const result = new Map<string, { source: ReviewKind[]; target: ReviewKind[] }>();
  const rowsByPage = new Map<number, Alignment[]>();
  for (const row of rows) {
    const pageNumber = Number(row.sentence_id.match(/\.(\d{3,})\.\d+$/)?.[1]);
    if (!pageNumber) continue;
    const pageRows = rowsByPage.get(pageNumber);
    if (pageRows) pageRows.push(row);
    else rowsByPage.set(pageNumber, [row]);
  }
  for (const page of pages) {
    const pageRows = rowsByPage.get(page.number);
    if (!pageRows?.length || !page.boxes.length) continue;
    const sourceColors = reviewColorsForAlignmentRows(pageRows, page.boxes, 'source');
    const targetColors = reviewColorsForAlignmentRows(pageRows, page.boxes, 'target');
    for (const row of pageRows) {
      result.set(row.id, {
        source: sourceColors.get(row.id) || [],
        target: targetColors.get(row.id) || [],
      });
    }
  }
  return result;
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
  const [view, setView] = useState<View>('overview');
  const [sidebarCollapsed, setSidebarCollapsed] = useState(readSidebarCollapsed);
  const [workspace, setWorkspace] = useState<Workspace | null>(null);
  const [bookId, setBookId] = useState('');
  const [pages, setPages] = useState<Page[]>([]);
  const [pageId, setPageId] = useState('');
  const [drafts, setDrafts] = useState<Record<string, Draft>>(readDrafts);
  const [busy, setBusy] = useState(false);
  const [loadingPages, setLoadingPages] = useState(false);
  const [connectionError, setConnectionError] = useState('');
  const [toast, setToast] = useState<{ message: string; error?: boolean } | null>(null);
  const [modal, setModal] = useState<'import' | 'guide' | 'settings' | null>(null);
  const [sources, setSources] = useState<SourceFile[]>([]);
  const [sourceSearch, setSourceSearch] = useState('');
  const [sourceLoading, setSourceLoading] = useState(false);
  const [rows, setRows] = useState<Alignment[]>([]);
  const [alignmentPage, setAlignmentPage] = useState('');
  const [alignmentBoxTarget, setAlignmentBoxTarget] = useState<{
    rowId: string;
    axis: 'vertical' | 'horizontal';
    requestId: string;
  } | null>(null);
  const similarity = useMemo(
    () => reviewSummary(pages.map((item) => ({
      ...item,
      ...(drafts[item.id] ? draftPatch(drafts[item.id]) : {}),
    }))),
    [pages, drafts],
  );
  const alignmentColors = useMemo(
    () => alignmentReviewColors(rows, pages.map((item) => ({
      ...item,
      ...(drafts[item.id] ? draftPatch(drafts[item.id]) : {}),
    }))),
    [rows, pages, drafts],
  );
  const alignmentContentPages = useMemo(() => pages.map((item) => {
    const merged = { ...item, ...(drafts[item.id] ? draftPatch(drafts[item.id]) : {}) };
    return merged.vi_boxes.length
      ? { ...merged, target_text: merged.vi_boxes.map((box) => box.transcription).join('\n') }
      : merged;
  }), [pages, drafts]);
  const alignmentPages = useMemo(() => alignmentContentPages.filter((item) =>
    !item.ocr_skip && item.category !== 'blank' && item.category !== 'misc' && item.ocr_languages.includes('han')
  ).sort((a, b) => a.number - b.number), [alignmentContentPages]);
  const activeBook = workspace?.books.find((b) => b.id === bookId);
  const alignmentSourcePage =
    alignmentPages.find((item) => item.id === alignmentPage) ||
    (activeBook && alignmentPages.find((item) => rows.some((row) =>
      row.sentence_id.startsWith(`${activeBook.name}.${String(item.number).padStart(3, '0')}.`)))) ||
    alignmentPages[0];
  const alignmentSourceDraft = alignmentSourcePage
    ? drafts[alignmentSourcePage.id]
    : undefined;
  const alignmentSource = alignmentSourcePage
    ? {
        ...alignmentSourcePage,
        ...(alignmentSourceDraft ? draftPatch(alignmentSourceDraft) : {}),
      }
    : undefined;
  const alignmentPageRows = alignmentSourcePage && activeBook
    ? rows.filter((row) =>
        row.sentence_id.startsWith(
          `${activeBook.name}.${String(alignmentSourcePage.number).padStart(3, '0')}.`,
        ),
      )
    : [];
  const alignmentPageGroups = useMemo(() => {
    if (!activeBook) return [];
    const rowsByPage = new Map<number, { row: Alignment; globalIndex: number }[]>();
    const prefix = `${activeBook.name}.`;
    rows.forEach((row, globalIndex) => {
      if (!row.sentence_id.startsWith(prefix)) return;
      const pageNumber = row.sentence_id.slice(prefix.length).split('.', 1)[0];
      if (!/^\d{3,}$/u.test(pageNumber)) return;
      const number = Number(pageNumber);
      const pageRows = rowsByPage.get(number);
      if (pageRows) pageRows.push({ row, globalIndex });
      else rowsByPage.set(number, [{ row, globalIndex }]);
    });
    return alignmentPages
      .map((page) => ({ page, rows: rowsByPage.get(page.number) || [] }));
  }, [activeBook, alignmentPages, rows]);
  const [rowsDirty, setRowsDirty] = useState(false);
  const rowsRef = useRef(rows);
  rowsRef.current = rows;
  const alignmentTimers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  const alignmentSaves = useRef(new Map<string, Promise<Alignment[]>>());
  const [alignmentLoading, setAlignmentLoading] = useState(false);
  const [reference, setReference] = useState<TextReference | null>(null);
  const [librarySearch, setLibrarySearch] = useState('');
  const [libraryBookId, setLibraryBookId] = useState('');
  const [dictionaryCharacter, setDictionaryCharacter] = useState<string | null>(null);
  const [dictionaryMode, setDictionaryMode] = useState<'character' | 'reading'>('character');
  const [dictionaryRequest, setDictionaryRequest] = useState(0);
  const [bookJob, setBookJob] = useState<OCRJob | null>(null);
  const [workflowStep, setWorkflowStep] = useState<1 | 2 | 3 | 4>(1);
  const [boxOCRPages, setBoxOCRPages] = useState<string[]>([]);
  const boxOCRRequests = useRef(new Set<string>());
  const [pageOCRPages, setPageOCRPages] = useState<string[]>([]);
  const pageOCRRequests = useRef(new Set<string>());
  const pagesRef = useRef(pages);
  pagesRef.current = pages;
  const [autosaveState, setAutosaveState] = useState('Mọi chỉnh sửa được lưu tự động.');
  const draftsRef = useRef(drafts);
  draftsRef.current = drafts;
  const savingDrafts = useRef(new Map<string, Promise<Page>>());
  const sessionRestored = useRef(false);
  const sessionSaves = useRef<Promise<unknown>>(Promise.resolve());
  const currentBookRef = useRef(bookId);
  currentBookRef.current = bookId;
  const pagesBookId = useRef('');
  const refreshingBookPages = useRef(false);
  const [dictionarySelection, setDictionarySelection] = useState<{
    pageId: string;
    boxId: string;
    index: number;
    character: string;
  } | null>(null);
  const fileInput = useRef<HTMLInputElement>(null);
  const toastTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const libraryBook = workspace?.books.find((b) => b.id === libraryBookId);
  const page = pages.find((p) => p.id === pageId);
  const draft = page
    ? {
        ...page,
        ...(drafts[page.id] ? draftPatch(drafts[page.id]) : {}),
      }
    : null;
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
    else {
      const nextValue = text.slice(0, selected.index) + character +
        text.slice(selected.index + selected.character.length);
      const next = replaceBoxText(draft.boxes, draft.source_text || '', selected.boxId,
        nextValue, draft.reading_direction, true);
      updateDraft({ boxes: next.boxes, source_text: next.text });
    }
    setDictionarySelection({ ...selected, character });
    setDictionaryCharacter(
      selected.character === '□' || !selected.character ? null : character,
    );
    notify('Đã thay chữ. Chỉnh sửa sẽ tự lưu; Ctrl + S để lưu ngay.');
  }

  async function refreshBookPages() {
    if (refreshingBookPages.current) return;
    refreshingBookPages.current = true;
    try {
      const id = bookId;
      const next = await api.pages(id);
      if (currentBookRef.current !== id) return;
      const current = pagesRef.current;
      const changed =
        next.length !== current.length ||
        next.some((page) => {
          const previous = current.find((item) => item.id === page.id);
          return !previous || page.version > previous.version;
        });
      setPages((previous) =>
        next.map((p) => {
          const old = previous.find((q) => q.id === p.id);
          return old && old.version >= p.version ? old : p;
        }),
      );
      if (changed) void loadWorkspace();
    } catch (error) {
      fail(error);
    } finally {
      refreshingBookPages.current = false;
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
  function updatePageDraft(base: Page, patch: Partial<Draft>, manual: boolean) {
    setDrafts((previous) => {
      const updated = {
        ...previous,
        [base.id]: patchDraft(previous[base.id], base, patch, manual),
      };
      try {
        localStorage.setItem('nom-drafts-v1', JSON.stringify(updated));
      } catch {
        notify(
          'Không giữ được bản nháp trên trình duyệt. Hãy bấm Lưu & hoàn thành trước khi đóng trang.',
          true,
        );
      }
      draftsRef.current = updated;
      return updated;
    });
  }
  function updateDraft(patch: Partial<Draft>) {
    if (page) {
      const ocrChange = ['boxes', 'vi_boxes', 'source_text', 'target_text'].some((key) => key in patch);
      updatePageDraft(page, patch, view === 'review' && workflowStep === 4 && !ocrChange);
    }
  }
  async function recognizeBoxes(boxes: Box[], language: 'han' | 'vi') {
    if (!draft || !boxes.length || boxOCRRequests.current.has(draft.id)) return;
    const snapshot = draft;
    if (snapshot.ocr_skip || snapshot.category === 'blank') {
      notify('Trang này đang bỏ qua OCR.', true);
      return;
    }
    boxOCRRequests.current.add(snapshot.id);
    setBoxOCRPages((previous) => [...previous, snapshot.id]);
    let completed = 0;
    let stale = 0;
    const errors: string[] = [];
    const validBoxes = boxes.filter((box) => validOCRRegionBox(box, snapshot));
    if (validBoxes.length !== boxes.length) {
      errors.push(`${boxes.length - validBoxes.length} box có khung không hợp lệ đã được bỏ qua.`);
    }
    let failed = boxes.length - validBoxes.length;
    try {
      for (const box of validBoxes) {
        try {
          const result = await api.recognizeBox(snapshot.id, box, language, language === 'vi' ? 2 : snapshot.reading_direction);
          if (!result.text.trim()) {
            errors.push('OCR không nhận ra chữ trong box; nội dung hiện tại được giữ nguyên.');
            failed++;
            continue;
          }
          const saved = pagesRef.current.find((item) => item.id === snapshot.id) || snapshot;
          const pending = draftsRef.current[snapshot.id];
          const current = { ...saved, ...(pending ? draftPatch(pending) : {}) };
          const boxesKey = language === 'han' ? 'boxes' : 'vi_boxes';
          const textKey = language === 'han' ? 'source_text' : 'target_text';
          const latestBox = current[boxesKey].find((item) => item.id === box.id);
          if (!latestBox || latestBox.transcription !== box.transcription ||
              JSON.stringify(latestBox.points) !== JSON.stringify(box.points) ||
              (saved.status === 'done' && saved.version !== snapshot.version)) {
            stale++;
            continue;
          }
          const next = replaceBoxText(current[boxesKey], current[textKey], box.id, result.text,
            language === 'vi' ? 2 : current.reading_direction, language === 'han');
          updatePageDraft(saved, { [boxesKey]: next.boxes, [textKey]: next.text }, true);
          completed++;
        } catch (error) {
          errors.push(error instanceof Error ? error.message : 'Lỗi OCR không xác định');
          failed++;
        }
      }
      if (boxes.length === 1 && completed === 1 && !errors.length) {
        notify('Đã OCR lại box. Kiểm tra chữ rồi bấm Lưu & hoàn thành.');
      } else {
        const details = [stale ? `${stale} box đã thay đổi nên bỏ qua.` : '',
          failed ? `${failed} box lỗi: ${errors[0]}` : '']
          .filter(Boolean).join(' ');
        notify(`Đã OCR ${completed}/${boxes.length} box. ${details || 'Kiểm tra chữ rồi bấm Lưu & hoàn thành.'}`,
          stale > 0 || errors.length > 0);
      }
    } finally {
      boxOCRRequests.current.delete(snapshot.id);
      setBoxOCRPages((previous) => previous.filter((id) => id !== snapshot.id));
    }
  }
  async function rerunPageOCR(target: Page, settings: OCRSettings) {
    if (pageOCRRequests.current.has(target.id)) return;
    const id = bookId;
    let startedVersion: number | null = null;
    let previousResultId: string | null = null;
    let startedDraft: Draft | undefined;
    pageOCRRequests.current.add(target.id);
    setPageOCRPages((previous) => [...previous, target.id]);
    try {
      await saveBookDrafts();
      const currentPages = await api.pages(id);
      if (currentBookRef.current !== id) return;
      const currentPage = currentPages.find((item) => item.id === target.id);
      if (!currentPage) throw new Error('Không tìm thấy trang cần OCR lại.');
      const draftSnapshot = draftsRef.current[target.id];
      const previousOCR = await api.latestOCR(target.id);
      startedVersion = currentPage.version;
      previousResultId = previousOCR?.result_id || null;
      startedDraft = draftSnapshot;
      const result = await api.recognizePage(target.id, {
        ...settings,
        ...(previousOCR?.settings || {}),
        mode: settings.mode,
        version: currentPage.version,
        force: true,
        reuse_saved_settings: true,
      });
      if (currentBookRef.current !== id) return;
      if (draftsRef.current[target.id] !== draftSnapshot) {
        notify('Trang đã được chỉnh sửa trong lúc OCR. Kết quả mới không được áp dụng.', true);
        return;
      }
      const requested = result.requested_languages || result.completed_languages || [];
      const completed = (result.completed_languages || []).filter((language) =>
        requested.includes(language),
      );
      const patch: Partial<Draft> = {};
      if (completed.includes('han')) {
        patch.boxes = result.boxes;
        patch.source_text = result.text_lines.join('\n');
      }
      if (completed.includes('vi')) {
        patch.vi_boxes = result.vi_boxes || [];
        patch.target_text = (result.vi_text_lines || []).join('\n');
      }
      if (!Object.keys(patch).length)
        throw new Error('OCR không trả về kết quả cho ngôn ngữ của trang này.');
      setPages((previous) =>
        previous.map((item) =>
          item.id === currentPage.id && item.version <= currentPage.version ? currentPage : item,
        ),
      );
      updatePageDraft(currentPage, patch, true);
      notify(`Đã OCR lại trang ${currentPage.number}. Kiểm tra kết quả rồi lưu trang.`);
    } catch (error) {
      // A later Quốc ngữ failure still leaves the Nôm checkpoint on the server.
      // Bring that completed half into the editable draft immediately.
      try {
        const [currentPages, checkpoint] = await Promise.all([api.pages(id), api.latestOCR(target.id)]);
        const saved = currentPages.find((item) => item.id === target.id);
        if (currentBookRef.current === id && saved && startedVersion !== null &&
            saved.version === startedVersion && draftsRef.current[target.id] === startedDraft &&
            checkpoint && checkpoint.result_id !== previousResultId &&
            checkpoint.version === startedVersion && checkpoint.completed_languages?.includes('han') &&
            checkpoint.boxes?.length) {
          setPages((previous) => previous.map((item) =>
            item.id === saved.id && item.version <= saved.version ? saved : item));
          updatePageDraft(saved, {
            boxes: checkpoint.boxes,
            source_text: checkpoint.text_lines.join('\n'),
          }, true);
        }
      } catch { /* Preserve the original OCR error. */ }
      fail(error);
    } finally {
      pageOCRRequests.current.delete(target.id);
      setPageOCRPages((previous) => previous.filter((id) => id !== target.id));
    }
  }
  async function bulkTagPages(pageIds: string[], category: Category) {
    if (!pageIds.length) return;
    setBusy(true);
    try {
      const plan: { page_id: string; category: Category; ocr_skip: boolean }[] = [];
      for (const id of pageIds) {
        const saved = await saveDraftNow(id, 'all');
        const current = saved || pagesRef.current.find((item) => item.id === id);
        if (current) plan.push({ page_id: id, category, ocr_skip: current.ocr_skip });
      }
      if (!plan.length) return;
      setPages(await api.savePlan(bookId, plan));
      notify(`Đã đổi nhãn ${plan.length} trang.`);
    } finally {
      setBusy(false);
    }
  }
  async function savePageLinks(id: string, linkedIds: string[]) {
    setBusy(true);
    try {
      const updated = await api.savePageLinks(id, linkedIds);
      setPages(updated);
      notify('Đã lưu liên kết trang. Kết quả OCR hiện tại được giữ nguyên.');
    } finally {
      setBusy(false);
    }
  }
  async function saveDraftNow(
    id: string,
    mode: 'all' | 'automatic' = 'automatic',
    refreshWorkspace = true,
  ): Promise<Page | undefined> {
    const inflight = savingDrafts.current.get(id);
    if (inflight) {
      await inflight;
      return saveDraftNow(id, mode, refreshWorkspace);
    }
    const snapshot = draftsRef.current[id];
    if (!snapshot) return;
    const patch = draftPatch(snapshot, mode);
    if (!Object.keys(patch).length) return;
    setAutosaveState('Đang lưu chỉnh sửa…');
    const task = api.patchPage(id, patch);
    savingDrafts.current.set(id, task);
    try {
      const updated = await task;
      if (draftsRef.current[id] === snapshot) {
        const next = { ...draftsRef.current };
        const remaining = afterAutomaticSave(snapshot, Object.keys(patch));
        if (remaining) next[id] = remaining;
        else delete next[id];
        draftsRef.current = next;
      }
      setPages((previous) =>
        previous.map((p) => (p.id === id && p.version <= updated.version ? updated : p)),
      );
      setDrafts((previous) => {
        if (previous[id] !== snapshot) return previous;
        const next = { ...previous };
        const remaining = afterAutomaticSave(snapshot, Object.keys(patch));
        if (remaining) next[id] = remaining;
        else delete next[id];
        draftsRef.current = next;
        try {
          localStorage.setItem('nom-drafts-v1', JSON.stringify(next));
        } catch {
          /* server copy saved */
        }
        return next;
      });
      setAutosaveState('Đã lưu chỉnh sửa vào máy.');
      if (refreshWorkspace) void loadWorkspace();
      return updated;
    } catch (error) {
      setAutosaveState('Chưa lưu được vào máy; bản nháp còn trên trình duyệt.');
      throw error;
    } finally {
      savingDrafts.current.delete(id);
    }
  }
  async function saveBookDrafts(mode: 'all' | 'automatic' = 'automatic') {
    for (const p of pages) await saveDraftNow(p.id, mode);
  }
  useEffect(() => {
    if (busy || !pages.length) return;
    const ids = pages.filter((p) => drafts[p.id] && Object.keys(draftPatch(drafts[p.id], 'automatic')).length).map((p) => p.id);
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
        setView('overview');
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
        pagesBookId.current = bookId;
        const localSession = readSession(bookId);
        const session = result.some((p) => p.id === localSession.page_id)
          ? localSession
          : savedSession;
        setPages(result);
        setWorkflowStep(session.workflow_step || 1);
        const unfinished = result.filter(
          (p) => p.status !== 'done' && !p.ocr_skip && p.category !== 'blank',
        );
        const first =
          result.find((p) => p.id === session.page_id) || unfinished[0] || result[0];
        setPageId(first?.id || '');
        if (session.alignment_page) setAlignmentPage(session.alignment_page);
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
    const state = {
      book_id: bookId,
      page_id: pageId,
      view,
      alignment_page: alignmentPage || null,
      workflow_step: workflowStep,
    };
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
  }, [bookId, pageId, view, alignmentPage, loadingPages, workflowStep]);
  useEffect(() => {
    if (!bookId || (view !== 'alignment' && view !== 'review')) return;
    let cancelled = false;
    setAlignmentLoading(true);
    setRows([]);
    setReference(null);
    if (loadingPages || pagesBookId.current !== bookId) {
      if (!loadingPages) setAlignmentLoading(false);
      return () => { cancelled = true; };
    }
    (async () => {
      let cached: Alignment[] | null = null;
      try { cached = JSON.parse(localStorage.getItem(`nom-alignment-${bookId}`) || 'null'); } catch { /* server copy */ }
      if (view === 'alignment') {
        const dirtyPageIds = pagesRef.current
          .filter((bookPage) => bookPage.book_id === bookId && draftsRef.current[bookPage.id] &&
            Object.keys(draftPatch(draftsRef.current[bookPage.id], 'all')).length)
          .map((bookPage) => bookPage.id);
        const savedDrafts = await Promise.all(
          dirtyPageIds.map((id) => saveDraftNow(id, 'all', false)),
        );
        if (savedDrafts.some(Boolean)) void loadWorkspace();
        if (cached) {
          await api.saveAlignments(bookId, cached);
          try { localStorage.removeItem(`nom-alignment-${bookId}`); } catch { /* server copy */ }
        }
        const [prepared, referenceText] = await Promise.all([
          api.prepareAlignments(bookId),
          api.reference(bookId),
        ]);
        const freshPages = await api.pages(bookId);
        return { result: prepared.rows, referenceText, freshPages, cached: null };
      }
      return { result: cached || await api.alignments(bookId), referenceText: null, freshPages: null, cached };
    })()
      .then(({ result, referenceText, freshPages, cached }) => {
        if (cancelled) return;
        setReference(referenceText);
        if (freshPages) setPages(freshPages);
        setRows(result);
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
  }, [bookId, view, loadingPages]);
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

  async function savePage(done: boolean) {
    if (!page || !draft) return false;
    if (done && boxOCRRequests.current.has(page.id)) {
      notify('Chờ OCR box này xong trước khi lưu trang.', true);
      return false;
    }
    setBusy(true);
    try {
      await saveDraftNow(page.id, 'all');
      const fresh = await api.pages(bookId);
      const saved = fresh.find((p) => p.id === page.id)!;
      const snapshot = draftsRef.current[page.id];
      const current = done && snapshot ? { ...saved, ...draftPatch(snapshot) } : saved;
      const updated = done
        ? await api.savePage(
            current,
            current.boxes,
            true,
            current.category,
            current.reading_direction,
            { source_text: current.source_text, target_text: current.target_text, vi_boxes: current.vi_boxes,
              ocr_granularity: current.ocr_granularity ??
                (current.category === 'ch' || current.category === 'vi' ? 'phrase' : 'character') },
          )
        : current;
      setPages((previous) => previous.map((p) => (p.id === updated.id ? updated : p)));
      if (done) {
        if (snapshot && draftsRef.current[page.id] === snapshot) {
          const next = { ...draftsRef.current };
          delete next[page.id];
          draftsRef.current = next;
          setDrafts(next);
          try { localStorage.setItem('nom-drafts-v1', JSON.stringify(next)); } catch { /* server copy saved */ }
        }
        notify(`Đã lưu và hoàn thành trang ${page.number}.`);
      } else notify('Đã lưu bản nháp vào máy.');
      void loadWorkspace();
      return true;
    } catch (error) {
      fail(error);
      return false;
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
        if (!busy) void savePage(workflowStep === 4);
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
      notify(`Đã nhập ${book.pages} trang. Phân loại trang để bắt đầu Gán nhãn.`);
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
  function navigateToView(nextView: View) {
    if (nextView === 'alignment' && pageId) {
      const currentPage = pages.find((item) => item.id === pageId);
      const sourcePage = alignmentPages.find((item) => item.id === pageId) ||
        alignmentPages.find((item) => item.linked_page_ids.includes(pageId)) ||
        (currentPage && alignmentPages.find((item) => item.number === currentPage.number));
      if (sourcePage) setAlignmentPage(sourcePage.id);
    }
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
  async function setAlignmentPageReviewed(
    groupPage: Page,
    pageRows: { row: Alignment; globalIndex: number }[],
    reviewed: boolean,
  ) {
    if (busy || !pageRows.length) return;
    if (reviewed) {
      const pageBoxes = draftsRef.current[groupPage.id]
        ? draftPatch(draftsRef.current[groupPage.id]).export_boxes || groupPage.export_boxes
        : groupPage.export_boxes;
      const missingBoxes = pageRows.filter(({ row }) =>
        !pageBoxes.some((box) => box.alignment_id === row.id)).length;
      if (missingBoxes) {
        notify(`Trang ${groupPage.number} còn ${missingBoxes} cặp chưa có box. Tạo box trước khi xác nhận.`, true);
        return;
      }
      const incomplete = pageRows.filter(({ row }) => !row.source.trim() || !row.target.trim()).length;
      if (incomplete) {
        notify(`Trang ${groupPage.number} còn ${incomplete} cặp thiếu nội dung đối chiếu.`, true);
        return;
      }
    }
    setBusy(true);
    try {
      await saveDraftNow(groupPage.id);
      const ids = new Set(pageRows.map(({ row }) => row.id));
      const next = rows.map((row) => ids.has(row.id) ? { ...row, reviewed } : row);
      changeRows(next);
      clearTimeout(alignmentTimers.current.get(bookId));
      await persistRows(bookId, next);
      notify(reviewed
        ? `Đã xác nhận hoàn tất ${pageRows.length} cặp của trang ${groupPage.number}.`
        : `Đã mở lại trang ${groupPage.number} để đọc lại.`);
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }
  function newRow(source = '', target = '', sourcePageId = alignmentSourcePage?.id || alignmentPage, pageLinked = false) {
    const sourcePage =
      pages.find((p) => p.id === sourcePageId) ||
      alignmentPages[0];
    if (!sourcePage || !activeBook) {
      notify('Cần chọn ít nhất một trang nội dung trước khi tạo cặp.', true);
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
        page_linked: pageLinked || !!sourcePage.linked_page_ids.length,
      },
    ]);
  }
  async function downloadAllResults() {
    setBusy(true);
    try {
      await saveBookDrafts('all');
      if (rowsDirty && bookId) {
        clearTimeout(alignmentTimers.current.get(bookId));
        await persistRows(bookId, rowsRef.current);
      }
      const response = await fetch(api.allResultsUrl);
      if (!response.ok) {
        const error = await response.json().catch(() => ({}));
        throw new Error(error.detail || 'Không thể tạo gói kết quả.');
      }
      const url = URL.createObjectURL(await response.blob());
      const link = document.createElement('a');
      link.href = url;
      link.download = 'tat-ca-ket-qua.zip';
      document.body.appendChild(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 10000);
      notify('Đã tải kết quả của tất cả sách. Bản sao được lưu trong backend/data/output_alignment/.');
    } catch (error) {
      fail(error);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className={`app-shell ${view === 'review' ? 'review-mode' : ''} ${sidebarCollapsed ? 'sidebar-collapsed' : ''}`}
    >
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
              onClick={() => navigateToView(item.id)}
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
              setDictionaryMode('reading');
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
                      ? 'Đối chiếu bản gốc, Gán nhãn văn bản và hoàn thiện từng trang ngữ liệu.'
                      : view === 'alignment'
                        ? 'Đối chiếu Hán Nôm và Quốc ngữ theo từng đơn vị có ý nghĩa.'
                        : view === 'library'
                          ? 'Xem các trang sách và kết quả Hán Nôm, Quốc ngữ đã lưu.'
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
                    <p>Đặt PDF vào backend/data/raw_data/ rồi quét lại.</p>
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
              {view !== 'review' &&
                (workspace.pair_stats ? (
                  <PairProgress stats={workspace.pair_stats} onImport={() => void openImport()} />
                ) : (
                  <p className="stats-refresh-notice">
                    Khởi động lại backend để cập nhật bộ đếm cặp câu.
                  </p>
                ))}
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
                              {formatBookTitle(book.name)}
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
                </>
              )}
              {view === 'review' && activeBook && !loadingPages && pages.length > 0 && (
                <BookWorkbench
                  key={bookId}
                  bookId={bookId}
                  initialStep={workflowStep}
                  onStepChange={setWorkflowStep}
                  pages={pages}
                  page={draft || undefined}
                  dirty={!!drafts[pageId]}
                  busy={busy || loadingPages}
                  recognizingBox={boxOCRPages.includes(pageId)}
                  onRecognizeBoxes={recognizeBoxes}
                  onRerunPage={rerunPageOCR}
                  rerunningPage={pageOCRPages.includes(pageId)}
                  onBulkTag={bulkTagPages}
                  onSaveLinks={savePageLinks}
                  job={bookJob}
                  onJob={setBookJob}
                  onPatch={updateDraft}
                  onNavigate={setPageId}
                  onConfirm={() => savePage(true)}
                  beforeStart={saveBookDrafts}
                  saveState={autosaveState}
                  onRefresh={() => void refreshBookPages()}
                  onError={fail}
                  onLookup={(box, character, index) => {
                    setDictionarySelection({ pageId: pageId, boxId: box.id, index, character });
                    setDictionaryMode(!character || character === '□' ? 'reading' : 'character');
                    setDictionaryCharacter(character);
                    setDictionaryRequest((current) => current + 1);
                  }}
                />
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
                      detail="Được người Gán nhãn xác nhận"
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
                      <p>Mở một tài liệu để tiếp tục Gán nhãn.</p>
                    </div>
                    <button className="text-button" onClick={() => setView('library')}>
                      Xem tủ sách
                      <ArrowRight size={15} />
                    </button>
                  </div>
                  <div className="book-grid">
                    {workspace.books.map((book) => (
                      <BookCard
                        key={book.id}
                        book={book}
                        onOpen={() => selectBook(book, 'review')}
                      />
                    ))}
                  </div>
                </>
              )}
              {view === 'library' &&
                (libraryBook ? (
                  <LibraryBookReader
                    key={libraryBook.id}
                    book={libraryBook}
                    onClose={() => setLibraryBookId('')}
                    onError={fail}
                  />
                ) : (
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
                        type="button"
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
                          <BookCard
                            key={book.id}
                            book={book}
                            onOpen={() => setLibraryBookId(book.id)}
                            actionLabel="Xem trang & kết quả"
                          />
                        ))}
                      <button
                        type="button"
                        className="new-book-card"
                        onClick={() => void openImport()}
                      >
                        <Plus size={26} />
                        <strong>Thêm một cuốn sách</strong>
                        <span>PDF từ máy hoặc backend/data/raw_data/</span>
                      </button>
                    </div>
                  </>
                ))}
              {view === 'alignment' && (
                <section className="alignment-workspace">
                  <div className="alignment-top">
                    <div>
                      <h2>
                        <Link2 size={19} />
                        Cặp đã xác nhận <span className="count-badge">{rows.filter((row) => row.reviewed).length}</span>
                      </h2>
                      <p>Cặp và box từ OCR đã được tự tạo, lưu sẵn. Kiểm tra rồi xác nhận từng trang.</p>
                    </div>
                    <div className="button-group">
                      <select
                        aria-label="Trang nguồn cho cặp mới"
                        value={alignmentSourcePage?.id || ''}
                        onChange={(event) => setAlignmentPage(event.target.value)}
                      >
                        <option value="">Chọn trang Nôm</option>
                        {alignmentPages.map((p) => (
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
                  <div key={`${bookId}:${alignmentSourcePage?.id || 'none'}`} className="alignment-active-page">
                  {!alignmentLoading && alignmentSourcePage?.linked_page_ids.length && activeBook && (
                    <LinkedAlignmentWorkspace
                      key={`${bookId}-${alignmentSourcePage.id}`}
                      page={alignmentSourcePage}
                      pages={alignmentContentPages}
                      bookName={activeBook.name}
                      rows={rows}
                      busy={busy}
                      onReviewPage={(reviewed) => {
                        const group = alignmentPageGroups.find(({ page }) => page.id === alignmentSourcePage.id);
                        if (group) void setAlignmentPageReviewed(group.page, group.rows, reviewed);
                      }}
                      onRows={(next, immediate) => {
                        changeRows(next);
                        if (immediate) {
                          clearTimeout(alignmentTimers.current.get(bookId));
                          void persistRows(bookId, next).catch(fail);
                        }
                      }}
                    />
                  )}
                  {!alignmentLoading && (
                    <AlignmentSources
                      key={`${bookId}-${alignmentSourcePage?.id || ''}`}
                      page={alignmentSource}
                      pages={alignmentContentPages}
                      reference={reference}
                      busy={busy}
                      onCreate={newRow}
                      onBoxes={(page, boxes) => updatePageDraft(page, { export_boxes: boxes }, false)}
                      alignments={alignmentPageRows}
                      targetRow={alignmentPageRows.find((row) => row.id === alignmentBoxTarget?.rowId)}
                      targetAxis={alignmentBoxTarget?.axis}
                      targetRequestId={alignmentBoxTarget?.requestId}
                      onTargetHandled={() => setAlignmentBoxTarget(null)}
                    />
                  )}
                  {!alignmentSourcePage?.linked_page_ids.length && <div className="alignment-notice">
                    <CircleHelp size={16} />
                    <span>
                      Dùng ảnh và box nhãn xuất phía trên để chỉnh dữ liệu tải về; chúng được lưu
                      riêng với box chữ OCR. Tô màu khi dò chữ trong bước{' '}
                      <strong>Gán nhãn OCR</strong>; bảng dưới dùng để tách, gộp và sửa cặp.
                    </span>
                  </div>}
                  {alignmentLoading ? (
                    <div className="empty-section">
                      <LoaderCircle className="spin" size={24} />
                    </div>
                  ) : alignmentPageGroups.length ? (
                    <div className="alignment-page-groups">
                      {alignmentPageGroups.map(({ page: groupPage, rows: pageRows }) => {
                        const isSelectedPage = groupPage.id === alignmentSourcePage?.id;
                        return (
                          <details
                            className="alignment-page-group"
                            key={groupPage.id}
                            open={isSelectedPage}
                          >
                          <summary onClick={() => setAlignmentPage(groupPage.id)}>
                            <strong>Trang {String(groupPage.number).padStart(3, '0')}</strong>
                            <span className={`alignment-page-status ${pageRows.length ? 'has-pairs' : ''}`}>
                              {pageRows.length
                                ? pageRows.every(({ row }) => row.reviewed)
                                  ? 'Đã xác nhận xong'
                                  : `Đã có ${pageRows.length} cặp`
                                : 'Chưa căn'}
                            </span>
                            {pageRows.length > 0 && (
                              <small>
                                {pageRows.every(({ row }) => row.reviewed)
                                  ? `${pageRows.length} cặp đã hoàn tất`
                                  : `${pageRows.filter(({ row }) => !row.reviewed).length} cặp chờ đọc lại`}
                              </small>
                            )}
                          </summary>
                          {isSelectedPage ? (
                            groupPage.linked_page_ids.length && pageRows.length ? (
                              <div className="alignment-page-empty">
                                <span>Các cặp của trang liên kết được chỉnh ở khối ghép phía trên.</span>
                              </div>
                            ) : pageRows.length ? (
                              <>
                              <div className="alignment-page-actions">
                                <span>
                                  {pageRows.filter(({ row }) => row.reviewed).length}/{pageRows.length} cặp đã xác nhận
                                </span>
                                <button
                                  type="button"
                                  className={pageRows.every(({ row }) => row.reviewed) ? 'secondary-button' : 'primary-button'}
                                  disabled={busy}
                                  onClick={() => void setAlignmentPageReviewed(
                                    groupPage,
                                    pageRows,
                                    !pageRows.every(({ row }) => row.reviewed),
                                  )}
                                >
                                  <CheckCheck size={15} />
                                  {pageRows.every(({ row }) => row.reviewed)
                                    ? 'Mở lại trang để đọc lại'
                                    : 'Xác nhận xong trang'}
                                </button>
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
                              <div className="alignment-rows">
                                {pageRows.map(({ row, globalIndex }, index) => {
                                  const nextEntry = pageRows[index + 1];
                                  return (
                                    <AlignmentRow
                                      key={row.id}
                                      row={row}
                                      index={index}
                                      total={pageRows.length}
                                      sourceColors={alignmentColors.get(row.id)?.source}
                                      targetColors={alignmentColors.get(row.id)?.target}
                                      onChange={(updated) =>
                                        changeRows(rows.map((item) => (item.id === row.id ? updated : item)))
                                      }
                                      hasBox={(drafts[groupPage.id]
                                        ? draftPatch(drafts[groupPage.id]).export_boxes || groupPage.export_boxes
                                        : groupPage.export_boxes)
                                        .some((box) => box.alignment_id === row.id)}
                                      onDrawBox={(axis) => {
                                        setAlignmentPage(groupPage.id);
                                        setAlignmentBoxTarget({ rowId: row.id, axis, requestId: crypto.randomUUID() });
                                        requestAnimationFrame(() => {
                                          const details = document.querySelector<HTMLDetailsElement>('.alignment-sources');
                                          if (details) details.open = true;
                                          document.querySelector<HTMLElement>('.alignment-source-image-panel')
                                            ?.scrollIntoView({ block: 'center', behavior: 'smooth' });
                                        });
                                      }}
                                      onRemove={() => changeRows(rows.filter((item) => item.id !== row.id))}
                                      onMerge={() => {
                                        if (!nextEntry) return;
                                        changeRows(
                                          rows.flatMap((item, itemIndex) =>
                                            itemIndex === globalIndex
                                              ? [
                                                  {
                                                    ...row,
                                                    source: row.source + nextEntry.row.source,
                                                    target: row.target + ' ' + nextEntry.row.target,
                                                    reviewed: false,
                                                    page_linked: !!row.page_linked || !!nextEntry.row.page_linked,
                                                    source_line_index: null,
                                                    target_page_id: null,
                                                    target_line_index: null,
                                                    marks: [],
                                                  },
                                                ]
                                              : itemIndex === nextEntry.globalIndex
                                                ? []
                                                : [item],
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
                                              .filter((item) => item.sentence_id.startsWith(prefix))
                                              .map((item) => Number(item.sentence_id.slice(prefix.length)) || 0),
                                          ) + 1;
                                        changeRows(
                                          rows.flatMap((item) =>
                                            item.id === row.id
                                              ? [
                                                  {
                                                    ...item,
                                                    source: source[0],
                                                    target: target[0],
                                                    reviewed: false,
                                                    page_linked: !!item.page_linked,
                                                    marks: [],
                                                  },
                                                  {
                                                    ...item,
                                                    id: crypto.randomUUID(),
                                                    sentence_id: prefix + sequence,
                                                    source: source[1],
                                                    target: target[1],
                                                    reviewed: false,
                                                    page_linked: !!item.page_linked,
                                                    marks: [],
                                                  },
                                                ]
                                              : [item],
                                          ),
                                        );
                                      }}
                                    />
                                  );
                                })}
                              </div>
                              </>
                            ) : (
                              <div className="alignment-page-empty">
                                <span>Trang này chưa có cặp căn chỉnh.</span>
                                <button
                                  className="secondary-button"
                                  disabled={busy}
                                  onClick={() => newRow('', '', groupPage.id)}
                                >
                                  <Plus size={14} />
                                  Tạo cặp cho trang này
                                </button>
                              </div>
                            )
                          ) : null}
                          </details>
                        );
                      })}
                    </div>
                  ) : alignmentSourcePage?.linked_page_ids.length ? null : (
                    <div className="empty-section">
                      <Link2 size={34} />
                      <h3>Chưa có cặp căn chỉnh</h3>
                      <p>Chưa có trang nào đủ văn bản Hán Nôm và Quốc ngữ để tự tạo cặp. Kiểm tra OCR hoặc tạo cặp thủ công.</p>
                      <button className="secondary-button" onClick={() => newRow()}>
                        <Plus size={15} />
                        Tạo cặp thủ công
                      </button>
                    </div>
                  )}
                  </div>
                  <div className="alignment-footer">
                    <span>
                      <span className="status-dot pending" />
                      {rows.filter((r) => !r.reviewed).length} cặp chưa đọc lại
                    </span>
                    <span>
                      {rowsDirty ? 'Có bản nháp chưa lưu vào máy' : 'Đã lưu vào máy'} · Xuất đúng 4
                      cột theo yêu cầu
                    </span>
                    <span>
                      {similarity.percent === null
                        ? 'Chưa có chữ Nôm để tính độ tương đồng'
                        : `Độ tương đồng ${similarity.percent.toFixed(2)}% (${similarity.red}/${similarity.total} chữ đỏ) · yêu cầu ≥95%`}
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
                      <h2>{'G\u00f3i demo c\u00e1c k\u1ebft qu\u1ea3 \u0111\u00e3 c\u0103n ch\u1ec9nh th\u00e0nh c\u00f4ng'}</h2>
                      <p>
                        {'ZIP ch\u1ec9 g\u1ed3m c\u00e1c cu\u1ed1n xu\u1ea5t \u0111\u01b0\u1ee3c c\u1ea3 CSV v\u00e0 XLSX. Nh\u00e3n OCR \u0111\u01b0\u1ee3c x\u1ebfp v\u00e0o th\u01b0 m\u1ee5c t\u1eebng cu\u1ed1n; cu\u1ed1n ch\u01b0a c\u00f3 c\u1eb7p ho\u1eb7c c\u00f2n c\u1eb7p thi\u1ebfu v\u1ebf s\u1ebd kh\u00f4ng \u0111\u01b0\u1ee3c th\u00eam v\u00e0o ZIP.'}
                      </p>
                      <button className="primary-button" disabled={busy || !workspace?.books.length}
                        onClick={() => void downloadAllResults()}>
                        <Download size={16} /> {'T\u1ea3i k\u1ebft qu\u1ea3 demo (.ZIP)'}
                      </button>
                    </div>
                  </div>
                  <div className="book-ocr-panel">
                    <h3>Kết quả và nhật ký được cập nhật tự động</h3>
                    <p>
                      {'M\u1ed7i cu\u1ed1n trong ZIP g\u1ed3m nh\u00e3n OCR, CSV v\u00e0 XLSX.'}
                    </p>
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
                </>
              )}
            </>
          )}
        </main>
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
          key={dictionaryRequest}
          character={dictionaryCharacter}
          initialMode={dictionaryMode}
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
                    'Gán nhãn từng vùng chữ',
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
                    {workspace?.han_ocr?.primary_ready
                      ? workspace.han_ocr.fallback.ready ? 'Kim Hán Nôm + PP-OCRv5 CPU' : 'Đã cấu hình Kim Hán Nôm'
                      : workspace?.han_ocr?.fallback.ready ? 'PP-OCRv5 CPU dự phòng' : 'Chưa cấu hình OCR Hán Nôm'}
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
                  Dữ liệu chỉ tính file PDF (txt dùng để đối chiếu chữ nếu có).
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
