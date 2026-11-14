import { useEffect, useLayoutEffect, useRef, useState } from 'react';
import {
  Check,
  ArrowLeft,
  ArrowRight,
  ChevronLeft,
  ChevronRight,
  Eye,
  EyeOff,
  Maximize2,
  Minimize2,
  Minus,
  MousePointer2,
  Plus,
  Search,
  SquareDashedMousePointer,
  Trash2,
  ScanLine,
  LoaderCircle,
  Save,
} from 'lucide-react';
import { api } from '../api';
import { boxReviewKindAt } from '../reviewColors';
import type {
  BookLayout,
  Box,
  Category,
  OCRJob,
  OCRSettings,
  Page,
  Region,
  ReviewKind,
  TextSources,
} from '../types';
import ManuscriptViewer from './ManuscriptViewer';
import BookOCRPanel, { useBookOCR } from './BookOCRPanel';
import CharacterBoxEditor, { groupCharacterBoxes } from './CharacterBoxEditor';
import { removeBoxAndText, replaceBoxText, syncTextLinesToBoxes } from './boxText';
import { boxesInReviewOrder } from '../reviewColors';

type Editable = Pick<
  Page,
  | 'boxes'
  | 'vi_boxes'
  | 'source_text'
  | 'target_text'
  | 'category'
  | 'ocr_skip'
  | 'source_regions'
  | 'target_regions'
  | 'ocr_languages'
  | 'ocr_granularity'
  | 'reading_direction_override'
>;
type Props = {
  bookId: string;
  initialStep: 1 | 2 | 3 | 4;
  onStepChange: (step: 1 | 2 | 3 | 4) => void;
  pages: Page[];
  page?: Page;
  dirty: boolean;
  busy: boolean;
  job: OCRJob | null;
  onJob: (job: OCRJob | null) => void;
  onPatch: (patch: Partial<Editable>) => void;
  onNavigate: (id: string) => void;
  recognizingBox: boolean;
  onRecognizeBoxes: (boxes: Box[], language: 'han' | 'vi') => Promise<void>;
  onRerunPage: (page: Page, settings: OCRSettings) => Promise<void>;
  rerunningPage: boolean;
  onBulkTag: (pageIds: string[], category: Category) => Promise<void>;
  onSaveLinks: (pageId: string, linkedIds: string[]) => Promise<void>;
  onConfirm: () => Promise<boolean>;
  beforeStart: () => Promise<void>;
  saveState: string;
  onRefresh: () => void;
  onError: (error: unknown) => void;
  onLookup: (box: Box, character: string, index: number) => void;
};

// Only explicit page markers divide a TXT. Unmarked text stays available as a reference.
export function referenceForPage(text: string, number: number) {
  const markers = [...text.matchAll(/^\s*\*+\s*Page\s+(\d+)\s*\*+\s*$/gim)];
  if (markers.length) {
    const index = markers.findIndex((marker) => Number(marker[1]) === number);
    if (index < 0) return '';
    const marker = markers[index];
    return text
      .slice(marker.index! + marker[0].length, markers[index + 1]?.index ?? text.length)
      .trim();
  }
  if (text.includes('\f')) return text.split('\f')[number - 1]?.trim() || '';
  return text;
}
function sharedRegions(...groups: Region[][]): Region[] {
  return Array.from(new Map(groups.flat().map((region) => [region.join(','), region])).values());
}
function hasContent(page?: Page) {
  return (
    !!page &&
    !!(
      page.source_text.trim() ||
      page.target_text.trim() ||
      page.boxes.length ||
      page.vi_boxes.length
    )
  );
}

function targetWordsIn(text: string) {
  return text.match(/\S+/gu)?.filter((word) => /[\p{L}\p{N}]/u.test(word)) || [];
}

function targetWordIndexAt(text: string, position: number): number | null {
  let wordIndex = 0;
  for (const match of text.matchAll(/\S+/gu)) {
    if (!/[\p{L}\p{N}]/u.test(match[0])) continue;
    const start = match.index ?? 0;
    if (position >= start && position <= start + match[0].length) return wordIndex;
    wordIndex++;
  }
  return null;
}

function VietnameseBoxEditor({
  box,
  index,
  rowWordStart,
  reviewKinds,
  disabled,
  onChange,
  onFocus,
  onSelectWord,
}: {
  box: Box;
  index: number;
  rowWordStart: number;
  reviewKinds: (ReviewKind | undefined)[];
  disabled: boolean;
  onChange: (box: Box, text: string) => void;
  onFocus: () => void;
  onSelectWord: (wordIndex: number, boxId: string) => void;
}) {
  const [editing, setEditing] = useState(false);
  const composing = useRef(false);
  const editorRef = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const element = editorRef.current;
    if (!element || editing) return;
    let wordIndex = rowWordStart;
    const nodes: Node[] = [];
    for (const part of box.transcription.split(/(\s+)/u)) {
      if (!part) continue;
      if (/^\s+$/u.test(part) || !/[\p{L}\p{N}]/u.test(part)) {
        nodes.push(document.createTextNode(part));
        continue;
      }
      const currentWord = wordIndex++;
      const span = document.createElement('span');
      span.className = `review-${reviewKinds[currentWord] || 'match'}`;
      span.dataset.wordIndex = String(currentWord);
      span.textContent = part;
      nodes.push(span);
    }
    element.replaceChildren(...nodes);
  }, [box.transcription, editing, onSelectWord, reviewKinds, rowWordStart]);

  function updateFromEditor(element: HTMLElement) {
    const value = element.innerText.replace(/\r\n/g, '\n').replace(/\n$/, '');
    if (value !== box.transcription) onChange(box, value);
  }

  return (
    <div
      ref={editorRef}
      className="workbench-vietnamese-editor"
      role="textbox"
      aria-label={`Vùng chữ Quốc ngữ ${index + 1}`}
      aria-multiline="true"
      contentEditable={!disabled}
      suppressContentEditableWarning
      onFocus={() => {
        setEditing(true);
        onFocus();
      }}
      onBlur={(event) => {
        composing.current = false;
        updateFromEditor(event.currentTarget);
        setEditing(false);
      }}
      onCompositionStart={() => {
        composing.current = true;
      }}
      onCompositionEnd={(event) => {
        composing.current = false;
        updateFromEditor(event.currentTarget);
      }}
      onInput={(event) => {
        if (!composing.current && !(event.nativeEvent as InputEvent).isComposing)
          updateFromEditor(event.currentTarget);
      }}
      onKeyDown={(event) => {
        if (event.key === 'Enter' && !event.shiftKey) {
          event.preventDefault();
          document.execCommand('insertText', false, '\n');
        }
      }}
      onClick={(event) => {
        if (!(event.target instanceof HTMLElement)) return;
        const word = event.target.closest<HTMLElement>('[data-word-index]');
        const wordIndex = Number(word?.dataset.wordIndex);
        if (word && Number.isInteger(wordIndex)) onSelectWord(wordIndex, box.id);
      }}
    />
  );
}

export default function BookWorkbench(props: Props) {
  const { pages } = props;
  const [step, setStep] = useState<1 | 2 | 3 | 4>(props.initialStep);
  const [pageFilter, setPageFilter] = useState<'pending' | 'done' | 'all'>('all');
  const [selectedPageIds, setSelectedPageIds] = useState<string[]>([]);
  const [bulkCategory, setBulkCategory] = useState<Category>('intro');
  async function tagSelectedPages(category: Category) {
    if (!selectedPageIds.length || props.busy || acting) return;
    try {
      await props.onBulkTag([...selectedPageIds], category);
      setSelectedPageIds([]);
    } catch (error) {
      props.onError(error);
    }
  }
  const eligiblePages = pages.filter((p) => !p.ocr_skip && p.category !== 'blank');
  const ocrFinished = (p: Page) =>
    p.status === 'done' ||
    p.ocr_languages.every((language) =>
      language === 'han' ? p.boxes.length > 0 : p.vi_boxes.length > 0,
    );
  const unfinishedPages = eligiblePages.filter((p) => !ocrFinished(p));
  const stagePages =
    step === 3
      ? eligiblePages.filter((p) => pageFilter === 'all' ||
          (pageFilter === 'done' ? ocrFinished(p) : !ocrFinished(p)))
      : pages;
  const page =
    step === 3 && !stagePages.some((p) => p.id === props.page?.id) ? stagePages[0] : props.page;
  useEffect(() => {
    if (step === 3 && stagePages.length && !stagePages.some((item) => item.id === props.page?.id))
      props.onNavigate(stagePages[0].id);
  }, [step, pageFilter, stagePages[0]?.id, props.page?.id]);
  const [language, setLanguage] = useState<'han' | 'vi'>('han');
  const [source, setSource] = useState<'ocr' | 'txt'>('ocr');
  const [sources, setSources] = useState<TextSources>({});
  const [sourcesReady, setSourcesReady] = useState(false);
  const [sourcesError, setSourcesError] = useState('');
  const [sourcesReload, setSourcesReload] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [layout, setLayout] = useState<BookLayout>({ source_regions: [], target_regions: [] });
  const [layoutReady, setLayoutReady] = useState(false);
  const [layoutSaving, setLayoutSaving] = useState(false);
  const [layoutError, setLayoutError] = useState(false);
  const [regionDirty, setRegionDirty] = useState(false);
  const layoutSaves = useRef<Promise<unknown>>(Promise.resolve());
  const [editingPageCrop, setEditingPageCrop] = useState(false);
  const [editingRegions, setEditingRegions] = useState(props.initialStep === 2);
  const [tool, setTool] = useState<'select' | 'draw'>('select');
  const [selected, setSelected] = useState<string | null>(null);
  const [selectedBoxIds, setSelectedBoxIds] = useState<string[]>([]);
  const [selectedTargetWord, setSelectedTargetWord] = useState<number | null>(null);
  const [showBoxes, setShowBoxes] = useState(true);
  const [zoom, setZoom] = useState(100);
  const [search, setSearch] = useState('');
  const [linkSearch, setLinkSearch] = useState('');
  const filteredPages = stagePages.filter((p) => !search || String(p.number).includes(search));
  const [full, setFull] = useState(false);
  const imagePane = useRef<HTMLDivElement>(null);
  const editor = useRef<HTMLDivElement>(null);
  const phraseInputs = useRef(new Map<string, HTMLTextAreaElement>());
  const phraseSelections = useRef(new Map<string, { start: number; end: number }>());
  const boxesKey = language === 'han' ? 'boxes' : 'vi_boxes';
  const textKey = language === 'han' ? 'source_text' : 'target_text';
  const boxes = page?.[boxesKey] || [];
  const ocrGranularity = page?.ocr_granularity ??
    (page?.category === 'ch' || page?.category === 'vi' ? 'phrase' : 'character');
  const readingDirection = page && language === 'han' && page.ocr_languages.includes('han')
    ? page.reading_direction_override ?? layout.reading_direction ?? page.reading_direction
    : 2;
  const selectedOCRBoxes = boxes.filter((box) => selectedBoxIds.includes(box.id));
  const ocrBoxes = selectedOCRBoxes.length
    ? selectedOCRBoxes
    : boxes.filter((box) => box.id === selected);
  const text = language === 'vi' && boxes.length
    ? boxes.map((box) => box.transcription).join('\n')
    : language === 'han' && ocrGranularity === 'phrase' && boxes.length
      ? boxes.map((box) => box.transcription).join('\n')
    : page?.[textKey] || '';
  const targetWords = targetWordsIn(language === 'vi' ? text : page?.target_text || '');
  const orderedSourceBoxes = boxesInReviewOrder(page?.boxes || []);
  const characterEditing =
    language === 'han' &&
    ocrGranularity === 'character' &&
    boxes.length > 0;
  const effectiveSource = source === 'txt' && sources[language] ? 'txt' : 'ocr';
  const settings: OCRSettings = {
    ocr_id: 1,
    reading_direction: layout.reading_direction || 2,
    lang_type: 2,
    epitaph: 0,
    tag: null,
    mode: 'bilingual',
    shared_reading_area: true,
    source_regions: sharedRegions(layout.source_regions, layout.target_regions),
    target_regions: sharedRegions(layout.source_regions, layout.target_regions),
  };
  const { acting, act } = useBookOCR({
    bookId: props.bookId,
    job: props.job,
    onJob: props.onJob,
    onRefresh: props.onRefresh,
    onError: props.onError,
    settings,
    beforeStart: async () => {
      await layoutSaves.current;
      await props.beforeStart();
    },
  });
  const navigationPages = step === 3 ? stagePages : pages;
  const pageIndex = navigationPages.findIndex((p) => p.id === page?.id);
  const skipped = page?.ocr_skip || page?.category === 'blank';

  useEffect(() => {
    let cancelled = false;
    setSourcesError('');
    Promise.allSettled([api.bookLayout(props.bookId), api.textSources(props.bookId)])
      .then(([nextLayout, nextSources]) => {
        if (cancelled) return;
        if (nextLayout.status === 'fulfilled') {
          setLayout(nextLayout.value);
          setLayoutReady(true);
        } else props.onError(nextLayout.reason);
        if (nextSources.status === 'fulfilled') {
          setSources(nextSources.value);
          setSourcesReady(true);
        } else {
          setSourcesError('Chưa tải được nguồn TXT đã lưu.');
          props.onError(nextSources.reason);
        }
      })
      .catch(props.onError);
    return () => {
      cancelled = true;
    };
  }, [props.bookId, sourcesReload]);
  useEffect(() => {
    setSelected(null);
    setSelectedBoxIds([]);
    setTool('select');
    setZoom(100);
    setRegionDirty(false);
    setEditingPageCrop(!!page && (page.source_regions != null || page.target_regions != null));
  }, [page?.id]);
  useEffect(() => {
    if (!page) return;
    const languages = page.category === 'ch' ? ['han'] : page.category === 'vi' ? ['vi']
      : page.category === 'blank' || page.category === 'misc' ? [] : page.ocr_languages;
    if (!languages.includes(language) && languages.length) setLanguage(languages[0] as 'han' | 'vi');
  }, [page?.id, page?.category, page?.ocr_languages.join(','), language]);
  useEffect(() => {
    setSelected(null);
    setSelectedBoxIds([]);
    setSelectedTargetWord(null);
  }, [language, page?.id]);
  useEffect(() => {
    if (step !== 4 || !selected) return;
    const row = Array.from(editor.current?.querySelectorAll<HTMLElement>('[data-row]') || []).find(
      (element) => element.dataset.row === selected,
    );
    row?.scrollIntoView({ block: 'nearest', behavior: 'smooth' });
  }, [step, selected, page?.id, boxes.length]);
  useEffect(() => {
    if (!page) return;
    const thumbnail = Array.from(document.querySelectorAll<HTMLElement>('.workbench-thumbnail'))
      .find((element) => element.dataset.pageId === page.id);
    thumbnail?.scrollIntoView({ block: 'nearest', inline: 'nearest' });
  }, [page?.id, step, pageFilter, search]);
  useEffect(() => {
    const sync = () => setFull(document.fullscreenElement === imagePane.current);
    document.addEventListener('fullscreenchange', sync);
    return () => document.removeEventListener('fullscreenchange', sync);
  }, []);

  const commonRegions = sharedRegions(layout.source_regions, layout.target_regions);
  const ownRegions = page
    ? [page.source_regions, page.target_regions].filter(
        (value): value is Region[] => value !== null,
      )
    : [];
  const regions = editingPageCrop
    ? ownRegions.length
      ? ownRegions.some((value) => !value.length)
        ? []
        : sharedRegions(...ownRegions)
      : []
    : commonRegions;
  const regionBoxes: Box[] = page
    ? regions.map(([left, top, right, bottom], index) => ({
        id: `region-${index}`,
        transcription: '',
        points: [
          [left * page.width, top * page.height],
          [right * page.width, top * page.height],
          [right * page.width, bottom * page.height],
          [left * page.width, bottom * page.height],
        ],
      }))
    : [];
  const canDeleteSelection =
    !props.busy &&
    !acting &&
    !skipped &&
    ((step === 2 && layoutReady) || step === 4) &&
    (step === 2 ? regionBoxes : boxes).some((box) => box.id === selected);

  function deleteSelection() {
    if (!canDeleteSelection || !selected) return;
    if (step === 2) saveRegions(regionBoxes.filter((box) => box.id !== selected));
    else if (selectedBoxIds.length > 1) {
      const remaining = boxes.filter((box) => !selectedBoxIds.includes(box.id));
      if (language === 'han') changeTextBoxes(remaining);
      else props.onPatch({
        [boxesKey]: remaining,
        [textKey]: remaining.map((box) => box.transcription).join('\n'),
      });
    }
    else if (characterEditing) changeTextBoxes(boxes.filter((box) => box.id !== selected));
    else {
      const next = removeBoxAndText(boxes, text, selected);
      const boxIndex = boxes.findIndex((box) => box.id === selected);
      props.onPatch({
        [boxesKey]: next.boxes,
        [textKey]: next.text,
        ...(language === 'vi' && page
          ? {
              boxes: page.boxes.map((box, index) =>
                index >= targetWordStart(boxIndex) ? { ...box, review_kind: undefined, review_marks: undefined } : box,
              ),
            }
          : {}),
      });
    }
    setSelected(null);
    setSelectedBoxIds([]);
    setTool('select');
  }

  function saveRegions(nextBoxes: Box[]) {
    if (!page || acting) return;
    const next: Region[] = nextBoxes.map((box) => {
      const xs = box.points.map(([x]) => x / page.width),
        ys = box.points.map(([, y]) => y / page.height);
      return [Math.min(...xs), Math.min(...ys), Math.max(...xs), Math.max(...ys)];
    });
    if (editingPageCrop) props.onPatch({ source_regions: next, target_regions: next });
    else persistLayout({ ...layout, source_regions: next, target_regions: next });
  }
  function persistLayout(profile: BookLayout) {
    const unified = sharedRegions(profile.source_regions, profile.target_regions);
    const nextLayout = { ...profile, source_regions: unified, target_regions: unified };
    setLayout(nextLayout);
    setLayoutSaving(true);
    setLayoutError(false);
    setRegionDirty(true);
    const task = layoutSaves.current
      .catch(() => {})
      .then(() => api.saveBookLayout(props.bookId, nextLayout));
    layoutSaves.current = task;
    void task
      .then(() => {
        if (layoutSaves.current === task) {
          setLayoutSaving(false);
          props.onRefresh();
        }
      })
      .catch((error) => {
        setLayoutSaving(false);
        setLayoutError(true);
        props.onError(error);
      });
  }
  function selectLanguage(next: 'han' | 'vi') {
    setLanguage(next);
    setSelected(null);
  }
  function goToStep(next: 1 | 2 | 3 | 4) {
    setStep(next);
    props.onStepChange(next);
    setTool('select');
    setEditingRegions(next === 2);
    if (next === 2)
      setEditingPageCrop(!!page && (page.source_regions != null || page.target_regions != null));
    setSelected(null);
    setSelectedBoxIds([]);
  }
  function continueToOCR() {
    goToStep(3);
    void act(props.job && ['paused', 'failed'].includes(props.job.status) ? 'resume' : 'start');
  }
  function openReview(id: string) {
    props.onNavigate(id);
    goToStep(4);
  }
  async function completePage() {
    if (!(await props.onConfirm())) return;
    setRegionDirty(false);
    setSelected(null);
    setEditingRegions(false);
  }
  async function upload(file: File, uploadLanguage: 'han' | 'vi' = language) {
    setUploading(true);
    try {
      if (!file.name.toLowerCase().endsWith('.txt') || file.size > 2000000)
        throw new Error('Chọn tệp TXT UTF-8 tối đa 2 MB.');
      const contents = new TextDecoder('utf-8', { fatal: true }).decode(await file.arrayBuffer());
      setSources(
        await api.saveTextSource(props.bookId, uploadLanguage, {
          filename: file.name,
          text: contents,
        }),
      );
      setSource('txt');
    } catch (error) {
      props.onError(error);
    } finally {
      setUploading(false);
    }
  }
  function selectFromImage(id: string | null) {
    setSelected(id);
    setSelectedBoxIds(id ? [id] : []);
  }
  function changeTextBoxes(next: Box[]) {
    if (step !== 4 || props.busy || acting || skipped) return;
    const hadOrders = boxes.some((box) => box.review_order !== undefined);
    const previousOrdersValid = hadOrders && boxes.every((box) => box.review_order != null) &&
      new Set(boxes.map((box) => box.review_order)).size === boxes.length;
    let nextOrder = Math.max(0, ...boxes.map((box) => box.review_order || 0));
    const ordered = hadOrders
      ? next.map((box) => ({
          ...box,
          review_order: box.review_order === undefined ? ++nextOrder : box.review_order,
        }))
      : next;
    if (previousOrdersValid && next.length < boxes.length)
      [...ordered].sort((a, b) => (a.review_order || 0) - (b.review_order || 0))
        .forEach((box, index) => { box.review_order = index + 1; });
    const synchronizedText = characterEditing
      ? groupCharacterBoxes(ordered, readingDirection)
          .map((row) => row.map((item) => item.transcription).join('')).join('\n')
      : language === 'vi'
        ? ordered.map((box) => box.transcription).join('\n')
        : undefined;
    props.onPatch({
      [boxesKey]: ordered,
      ...(synchronizedText !== undefined ? { [textKey]: synchronizedText } : {}),
    });
  }
  function markBox(boxId: string, review_kind: ReviewKind, selectedRange?: { start: number; end: number }) {
    if (!page) return;
    const index = page.boxes.findIndex((box) => box.id === boxId);
    if (index < 0) return;
    const current = page.boxes[index];
    if (selectedRange && ocrGranularity === 'phrase' && language === 'han') {
      const characters = Array.from(current.transcription);
      const kinds = characters.map((_, characterIndex) => boxReviewKindAt(current, characterIndex));
      for (let characterIndex = selectedRange.start; characterIndex < Math.min(selectedRange.end, kinds.length); characterIndex++)
        kinds[characterIndex] = review_kind;
      const review_marks: NonNullable<Box['review_marks']> = [];
      for (let characterIndex = 0; characterIndex < kinds.length;) {
        const kind = kinds[characterIndex];
        let end = characterIndex + 1;
        while (end < kinds.length && kinds[end] === kind) end++;
        if (kind !== 'match') review_marks.push({ start: characterIndex, end, kind });
        characterIndex = end;
      }
      const uniform = kinds.every((kind) => kind === kinds[0]);
      props.onPatch({
        boxes: page.boxes.map((box, boxIndex) => boxIndex === index
          ? { ...box, review_kind: uniform ? kinds[0] : undefined, review_marks: uniform ? undefined : review_marks }
          : box),
      });
      return;
    }
    props.onPatch({
      boxes: page.boxes.map((box, boxIndex) =>
        boxIndex === index || selectedBoxIds.includes(box.id)
          ? { ...box, review_kind, review_marks: undefined }
          : box,
      ),
    });
  }
  function markAllBoxes(review_kind: ReviewKind) {
    if (!page) return;
    props.onPatch({
      boxes: page.boxes.map((box, index) =>
        index < page.boxes.length ? { ...box, review_kind, review_marks: undefined } : box,
      ),
    });
  }
  function updateBox(box: Box, value: string) {
    if (!page) return;
    const next = replaceBoxText(boxes, text, box.id, value, readingDirection, language === 'han');
    const synchronizedText = next.boxes.length
      ? language === 'han'
        ? ocrGranularity === 'phrase'
          ? next.boxes.map((item) => item.transcription).join('\n')
          : groupCharacterBoxes(next.boxes, readingDirection).map((row) =>
            row.map((item) => item.transcription).join(''),
          ).join('\n')
        : next.boxes.map((item) => item.transcription).join('\n')
      : next.text;
    const boxIndex = boxes.findIndex((current) => current.id === box.id);
    const targetWordCountChanged =
      language === 'vi' && targetWordCount(box.transcription) !== targetWordCount(value);
    props.onPatch({
      [boxesKey]: next.boxes.map((item) =>
        item.id === box.id && item.transcription !== value
          ? { ...item, review_kind: undefined, review_marks: undefined }
          : item,
      ),
      ...(language === 'vi' && box.transcription !== value
        && targetWordCountChanged
        ? {
            boxes: page.boxes.map((item, index) =>
              index >= targetWordStart(boxIndex)
                ? { ...item, review_kind: undefined, review_marks: undefined }
              : item,
            ),
          }
        : {}),
      [textKey]: synchronizedText,
    });
  }
  function targetWordCount(value: string) {
    return targetWordsIn(value).length;
  }
  function targetWordStart(boxIndex: number) {
    return boxes.slice(0, boxIndex).reduce((count, box) => count + targetWordCount(box.transcription), 0);
  }
  function selectTargetWord(wordIndex: number, boxId: string) {
    setSelected(boxId);
    setSelectedTargetWord(wordIndex);
    setShowBoxes(true);
    setEditingRegions(false);
  }
  function lookupPhraseSelection(box: Box) {
    const input = phraseInputs.current.get(box.id);
    if (!input) return;
    const liveSelection = { start: input.selectionStart, end: input.selectionEnd };
    const remembered = phraseSelections.current.get(box.id);
    const { start, end } = liveSelection.end > liveSelection.start ? liveSelection : remembered || liveSelection;
    const selectedText = start !== end ? input.value.slice(start, end) : box.transcription;
    if (selectedText.trim()) props.onLookup(box, selectedText, start !== end ? start : 0);
  }
  async function fullscreen() {
    try {
      if (document.fullscreenElement) await document.exitFullscreen();
      else await imagePane.current?.requestFullscreen();
    } catch (error) {
      props.onError(error);
    }
  }
  return (
    <section
      className="book-workbench"
      aria-label="Đối chiếu sách và Gán nhãn"
      onKeyDown={(event) => {
        const target = event.target as HTMLElement;
        const reviewKind = event.key === '1' ? 'match' : event.key === '2' ? 'mismatch' : event.key === '3' ? 'unknown' : null;
        if (
          step === 4 &&
          event.altKey &&
          !event.ctrlKey &&
          !event.metaKey &&
          reviewKind &&
          selected &&
          !target.closest('select, [contenteditable="true"]')
        ) {
          event.preventDefault();
          const phraseInput = ocrGranularity === 'phrase' && language === 'han'
            ? phraseInputs.current.get(selected)
            : undefined;
          const selectionStart = phraseInput?.selectionStart ?? 0;
          const selectionEnd = phraseInput?.selectionEnd ?? 0;
          const selectedRange = selectionEnd > selectionStart && phraseInput
            ? {
                start: Array.from(phraseInput.value.slice(0, selectionStart)).length,
                end: Array.from(phraseInput.value.slice(0, selectionEnd)).length,
              }
            : undefined;
          markBox(selected, reviewKind, selectedRange);
          return;
        }
        if (
          step === 2 &&
          (event.ctrlKey || event.metaKey) &&
          event.key.toLowerCase() === 'a' &&
          !target.closest(
            'input, textarea, select, [contenteditable]:not([contenteditable="false"])',
          )
        ) {
          event.preventDefault();
          setSelectedPageIds(pages.map((item) => item.id));
          return;
        }
        if (
          event.key !== 'Delete' ||
          event.repeat ||
          event.defaultPrevented ||
          event.ctrlKey ||
          event.metaKey ||
          event.altKey ||
          event.shiftKey ||
          target.closest(
            'input, textarea, select, [contenteditable]:not([contenteditable="false"])',
          )
        )
          return;
        if (canDeleteSelection) {
          event.preventDefault();
          deleteSelection();
        }
      }}
    >
      <nav className="workflow-stepper" aria-label="Các bước chi tiết OCR">
        {(
          [
            [1, 'Thêm nội dung'],
            [2, 'Gắn nhãn trang'],
            [3, 'Lưu & OCR toàn bộ sách'],
            [4, 'Gán nhãn & hoàn thành'],
          ] as const
        ).map(([number, label]) => (
          <button
            key={number}
            type="button"
            className={`workflow-step-btn ${step === number ? 'is-active' : ''}`}
            aria-current={step === number ? 'step' : undefined}
            disabled={
              props.busy ||
              uploading ||
              (number === 4 && !page)
            }
            onClick={() => {
              if (number === 4 && page) openReview(page.id);
              else goToStep(number);
            }}
          >
            <span className="step-num">{number}</span>
            {label}
          </button>
        ))}
      </nav>
      {step === 1 ? (
        <div className="workbench-content-step">
          <div className="workbench-content-heading">
            <h3>Thêm nội dung đối chiếu</h3>
            <span>TXT tùy chọn · UTF-8 · tối đa 2 MB mỗi tệp</span>
          </div>
          {sourcesError && (
            <div className="workbench-source-error" role="alert">
              {sourcesError}
              <button
                type="button"
                className="text-button"
                onClick={() => setSourcesReload((value) => value + 1)}
              >
                Thử lại
              </button>
            </div>
          )}
          <div className="workbench-content-sources">
            {(['han', 'vi'] as const).map((kind) => {
              const title = kind === 'han' ? 'Hán/Nôm' : 'Quốc ngữ';
              const reference = sources[kind];
              return (
                <section
                  className="workbench-content-card"
                  key={kind}
                  aria-label={`Nguồn TXT ${title}`}
                >
                  <h4>{title}</h4>
                  <span className="workbench-source-filename">
                    {reference?.filename ||
                      (sourcesReady
                        ? 'Chưa có TXT'
                        : sourcesError
                          ? 'Chưa tải được nguồn'
                          : 'Đang tải nguồn…')}
                  </span>
                  <label>
                    {reference ? 'Thay TXT' : 'Tải TXT'} {title}
                    <input
                      type="file"
                      accept=".txt,text/plain"
                      disabled={!sourcesReady || uploading || acting || props.busy}
                      onChange={(event) => {
                        const file = event.target.files?.[0];
                        if (file) void upload(file, kind);
                        event.target.value = '';
                      }}
                    />
                  </label>
                  {reference && (
                    <textarea
                      className={kind === 'han' ? 'han-text' : ''}
                      readOnly
                      aria-label={`Bản TXT ${title} đã tải`}
                      value={reference.text}
                    />
                  )}
                </section>
              );
            })}
          </div>
          <div className="workbench-content-actions">
            {uploading && <span role="status">Đang lưu TXT…</span>}
            <button
              type="button"
              className="primary-button"
              disabled={uploading || acting || props.busy}
              onClick={() => goToStep(2)}
            >
              Tiếp tục: Gắn nhãn trang <ArrowRight size={15} />
            </button>
          </div>
        </div>
      ) : (
        <>
          <div className="workbench-topbar">
            <span>
              {step === 4 ? (
                <>
                  <strong>{pages.filter((p) => p.status === 'done').length}</strong> /{' '}
                  {pages.length} trang đã xác nhận
                </>
              ) : (
                <>
                  <strong>{pages.length}</strong> trang ·{' '}
                  {pages.filter((p) => p.ocr_skip || p.category === 'blank').length} bỏ qua OCR
                </>
              )}
            </span>
            <BookOCRPanel
              disabled={
                props.busy || !layoutReady || layoutSaving || layoutError || !unfinishedPages.length
              }
              job={props.job}
              showStart={step === 3}
              showResume={step !== 2}
              acting={acting}
              onAction={act}
            />
          </div>
          <div className={`workbench-body ${step !== 4 ? 'workbench-preparation' : ''}`}>
            <aside className="workbench-pages" aria-label="Danh sách trang">
              {step === 3 && (
                <select
                  className="workbench-page-filter"
                  aria-label="Trạng thái trang trong bước OCR"
                  value={pageFilter}
                  onChange={(event) => setPageFilter(event.target.value as typeof pageFilter)}
                >
                  <option value="pending">Chưa xong ({unfinishedPages.length})</option>
                  <option value="done">
                    Đã xong ({eligiblePages.length - unfinishedPages.length})
                  </option>
                  <option value="all">Tất cả ({eligiblePages.length})</option>
                </select>
              )}
              <label className="workbench-search">
                <Search size={14} />
                <input
                  aria-label="Tìm trang"
                  placeholder="Tìm trang…"
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                />
              </label>
              <div className="workbench-thumbnails">
                {filteredPages.map((p) => (
                    <button
                      key={p.id}
                      data-page-id={p.id}
                      className={`workbench-thumbnail ${p.id === page?.id ? 'selected' : ''} ${selectedPageIds.includes(p.id) ? 'multi-selected' : ''}`}
                      aria-pressed={selectedPageIds.includes(p.id)}
                      disabled={props.busy}
                      title={`Trang ${p.number} · OCR ${ocrFinished(p) ? 'đã xong' : 'chưa xong'} · Gán nhãn ${p.status === 'done' ? 'đã xong' : 'chưa xong'}`}
                      onClick={(event) => {
                        if (step === 2 && (event.ctrlKey || event.metaKey)) {
                          setSelectedPageIds((current) =>
                            current.includes(p.id)
                              ? current.filter((id) => id !== p.id)
                              : [...current, p.id],
                          );
                        } else {
                          setSelectedPageIds([]);
                          props.onNavigate(p.id);
                        }
                      }}
                    >
                      <img
                        loading="lazy"
                        src={`${p.image_url}?thumbnail=true`}
                        alt={`Trang ${p.number}`}
                      />
                      <span>
                        {String(p.number).padStart(3, '0')}{' '}
                        {(step === 3 ? ocrFinished(p) : p.status === 'done') ? (
                          <Check size={12} />
                        ) : (
                          <span className="pending-mark">•</span>
                        )}
                      </span>
                    </button>
                  ))}
              </div>
            </aside>
            {page ? (
              <>
                <div
                  className="workbench-image"
                  ref={imagePane}
                  tabIndex={0}
                  aria-label={
                    step === 2
                      ? 'Ảnh trang sách và vùng đọc'
                      : 'Ảnh trang sách và bounding box OCR'
                  }
                  onPointerDownCapture={(event) => {
                    if ((event.target as Element).closest('.manuscript-stage')) {
                      event.currentTarget.focus({ preventScroll: true });
                    }
                  }}
                >
                  <div className="workbench-image-toolbar">
                    <strong>
                      Trang {page.number} <small>/ {pages.length}</small>
                    </strong>
                    <div className="image-controls">
                      {(step === 2 || step === 4) && (
                        <>
                          <button
                            className="icon-button"
                            aria-label={step === 4 ? 'Chọn box chữ' : 'Chọn vùng'}
                            aria-pressed={tool === 'select'}
                            title={
                              step === 4
                                ? 'Chọn, di chuyển hoặc chỉnh góc box chữ'
                                : 'Chọn vùng đọc'
                            }
                            onClick={() => setTool('select')}
                          >
                            <MousePointer2 size={16} />
                          </button>
                          <button
                            className="icon-button"
                            aria-label={step === 4 ? 'Alt + kéo để vẽ box chữ' : 'Vẽ vùng đọc'}
                            aria-pressed={tool === 'draw'}
                            title={
                              step === 4
                                ? 'Alt + kéo để thêm box chữ; kéo vùng trống để chọn nhiều box'
                                : 'Vẽ vùng đọc'
                            }
                            disabled={
                              props.busy || acting || (step === 2 && !layoutReady) || skipped
                            }
                            onClick={() => {
                              setEditingRegions(step === 2);
                              setTool('draw');
                              setShowBoxes(true);
                            }}
                          >
                            <SquareDashedMousePointer size={17} />
                          </button>
                          <button
                            type="button"
                            className="workbench-delete-selection"
                            aria-label={step === 4 ? 'Xóa box chữ đã chọn' : 'Xóa vùng chọn'}
                            aria-keyshortcuts="Delete"
                            title={
                              step === 4
                                ? 'Xóa box và chữ tương ứng (Delete)'
                                : 'Xóa vùng đọc đang chọn (Delete)'
                            }
                            disabled={!canDeleteSelection}
                            onClick={deleteSelection}
                          >
                            <Trash2 size={15} />
                            {step === 4 ? 'Xóa box' : 'Xóa vùng chọn'}
                          </button>
                          {step === 4 && (
                            <button
                              type="button"
                              className="secondary-button"
                              aria-label="OCR lại ảnh này"
                              title="Chạy OCR lại cho riêng trang đang mở"
                              disabled={
                                props.busy ||
                                acting ||
                                props.rerunningPage ||
                                skipped
                              }
                              onClick={() => {
                                if (page) void props.onRerunPage(page, settings);
                              }}
                            >
                              {props.rerunningPage ? (
                                <LoaderCircle size={15} className="spin" />
                              ) : (
                                <ScanLine size={15} />
                              )}
                              {props.rerunningPage ? 'Đang OCR trang…' : 'OCR lại trang'}
                            </button>
                          )}
                          {step === 4 && (
                            <button
                              type="button"
                              className="secondary-button"
                              aria-label="OCR lại box đã chọn"
                              disabled={props.busy || acting || props.recognizingBox || skipped || !ocrBoxes.length}
                              onClick={() => {
                                if (ocrBoxes.length) void props.onRecognizeBoxes(ocrBoxes, language);
                              }}
                            >
                              {props.recognizingBox ? <LoaderCircle size={15} className="spin" /> : <ScanLine size={15} />}
                              {props.recognizingBox ? 'Đang OCR box…' : ocrBoxes.length > 1 ? 'OCR lại ' + ocrBoxes.length + ' box' : 'OCR lại box'}
                            </button>
                          )}
                        </>
                      )}
                      <button
                        className="icon-button"
                        aria-label={showBoxes ? 'Ẩn bounding box' : 'Hiện bounding box'}
                        onClick={() => setShowBoxes(!showBoxes)}
                      >
                        {showBoxes ? <Eye size={16} /> : <EyeOff size={16} />}
                      </button>
                      <button
                        className="icon-button"
                        aria-label="Thu nhỏ"
                        onClick={() => setZoom(Math.max(50, zoom - 25))}
                      >
                        <Minus size={15} />
                      </button>
                      <button
                        className="zoom-reset"
                        title="Vừa chiều rộng"
                        onClick={() => setZoom(100)}
                      >
                        {zoom}%
                      </button>
                      <button
                        className="icon-button"
                        aria-label="Phóng to"
                        onClick={() => setZoom(Math.min(300, zoom + 25))}
                      >
                        <Plus size={15} />
                      </button>
                      <button
                        className="icon-button"
                        aria-label={full ? 'Thoát toàn màn hình' : 'Ảnh toàn màn hình'}
                        onClick={() => void fullscreen()}
                      >
                        {full ? <Minimize2 size={17} /> : <Maximize2 size={17} />}
                      </button>
                    </div>
                  </div>
                  <ManuscriptViewer
                    page={page}
                    boxes={skipped ? [] : editingRegions ? regionBoxes : boxes}
                    selected={selected}
                    boxNumber={(item, index) =>
                      step === 4 && language === 'han' && !editingRegions
                        ? item.review_order === undefined ? index + 1 : item.review_order ?? '—'
                        : index + 1
                    }
                    selectedIds={selectedBoxIds}
                    setSelected={selectFromImage}
                    onSelectionChange={setSelectedBoxIds}
                    showBoxes={showBoxes}
                    showFullPageRegion={step === 2 && !skipped && !regions.length}
                    tool={tool}
                    zoom={zoom}
                    allowAltDraw={step === 4}
                    readOnly={(step !== 2 && step !== 4) || props.busy || acting || skipped}
                    onBoxes={step === 2 ? saveRegions : changeTextBoxes}
                    onDrawn={() => {
                      setTool('select');
                      if (editingRegions) setSelected(`region-${regions.length}`);
                    }}
                  />
                  {step === 2 && (
                    <div className="workbench-regionbar">
                      {editingPageCrop ? (
                        <button
                          className="text-button"
                          disabled={props.busy}
                          onClick={() => {
                            if (ownRegions.length)
                              props.onPatch({ source_regions: null, target_regions: null });
                            setEditingPageCrop(false);
                            setSelected(null);
                            setTool('select');
                          }}
                        >
                          Dùng vùng chung
                        </button>
                      ) : (
                        <button
                          className="text-button"
                          disabled={props.busy || acting || !layoutReady || skipped}
                          onClick={() => {
                            setEditingPageCrop(true);
                            setTool('draw');
                            setSelected(null);
                            setShowBoxes(true);
                          }}
                        >
                          Cắt lại trang này
                        </button>
                      )}
                      {layoutSaving && <small role="status">Đang lưu…</small>}
                    </div>
                  )}
                </div>
                <aside className={`workbench-text ${step !== 4 ? 'workbench-setup' : ''}`}>
                  {step === 2 && (
                    <h3 className="workbench-setup-title">Nhãn trang {page.number}</h3>
                  )}
                  {step === 4 && (
                    <div
                      className="workbench-language-tabs"
                      role="tablist"
                      aria-label="Văn bản đối chiếu"
                    >
                      {(page.category === 'ch' || (page.category !== 'vi' && page.category !== 'blank' && page.category !== 'misc' && page.ocr_languages.includes('han'))) && <button
                        role="tab"
                        aria-selected={language === 'han'}
                        onClick={() => selectLanguage('han')}
                      >
                        Hán Nôm
                      </button>}
                      {(page.category === 'vi' || (page.category !== 'ch' && page.category !== 'blank' && page.category !== 'misc' && page.ocr_languages.includes('vi'))) && <button
                        role="tab"
                        aria-selected={language === 'vi'}
                        onClick={() => selectLanguage('vi')}
                      >
                        Quốc ngữ
                      </button>}
                    </div>
                  )}
                  {step === 4 &&
                    language === 'vi' &&
                    page.ocr_languages.includes('han') &&
                    !characterEditing && (
                      <div className="character-review-toolbar" aria-label="Đánh dấu từ Quốc ngữ">
                        <span>
                          {selectedTargetWord !== null
                            ? `${orderedSourceBoxes[selectedTargetWord]?.transcription || '—'} ↔ ${targetWords[selectedTargetWord] || '—'}`
                            : 'Chọn một từ Quốc ngữ để đánh dấu cùng chữ Hán/Nôm thứ tự đó'}
                        </span>
                        <button
                          type="button"
                          disabled={selectedTargetWord === null || !orderedSourceBoxes[selectedTargetWord] || props.busy || acting}
                          onClick={() => selectedTargetWord !== null && orderedSourceBoxes[selectedTargetWord] && markBox(orderedSourceBoxes[selectedTargetWord].id, 'match')}
                        >
                          Đen
                        </button>
                        <button
                          type="button"
                          disabled={selectedTargetWord === null || !orderedSourceBoxes[selectedTargetWord] || props.busy || acting}
                          onClick={() => selectedTargetWord !== null && orderedSourceBoxes[selectedTargetWord] && markBox(orderedSourceBoxes[selectedTargetWord].id, 'mismatch')}
                        >
                          Đỏ
                        </button>
                        <button
                          type="button"
                          disabled={selectedTargetWord === null || !orderedSourceBoxes[selectedTargetWord] || props.busy || acting}
                          onClick={() => selectedTargetWord !== null && orderedSourceBoxes[selectedTargetWord] && markBox(orderedSourceBoxes[selectedTargetWord].id, 'unknown')}
                        >
                          Thiếu từ điển
                        </button>
                        <button
                          type="button"
                          disabled={props.busy || acting}
                          onClick={() => markAllBoxes('match')}
                        >
                          Đặt hết đen
                        </button>
                        <small>Màu áp dụng lên chữ Hán/Nôm và từ Quốc ngữ cùng thứ tự.</small>
                      </div>
                    )}
                  {step === 2 && (
                    <div className="workbench-setup-options">
                      <label className="workbench-region-language">
                        Chiều đọc Hán/Nôm mặc định cho cả sách
                        <select
                          aria-label="Chiều đọc Hán/Nôm mặc định cho cả sách"
                          value={layout.reading_direction || 2}
                          disabled={props.busy || acting || !layoutReady}
                          onChange={(event) =>
                            persistLayout({
                              ...layout,
                              reading_direction: Number(event.target.value) as 1 | 2,
                            })
                          }
                        >
                          <option value={1}>Dọc · trên xuống dưới, cột phải sang trái</option>
                          <option value={2}>Ngang · trái sang phải</option>
                        </select>
                        <small>Trang chỉ có Quốc ngữ luôn đọc ngang, trái sang phải.</small>
                      </label>
                      <div className="workbench-bulk-tag">
                        <small>
                          Giữ Ctrl và nhấp để chọn nhiều trang · Ctrl+A chọn toàn bộ trang
                        </small>
                        <div className="workbench-bulk-selection">
                          <button
                            type="button"
                            disabled={props.busy || acting || selectedPageIds.length === pages.length}
                            onClick={() => setSelectedPageIds(pages.map((item) => item.id))}
                          >
                            Chọn tất cả ({pages.length})
                          </button>
                          {selectedPageIds.length > 0 && (
                            <button
                              type="button"
                              disabled={props.busy || acting}
                              onClick={() => setSelectedPageIds([])}
                            >
                              Bỏ chọn
                            </button>
                          )}
                        </div>
                        {selectedPageIds.length > 0 && (
                          <div className="workbench-bulk-actions">
                            <span>{selectedPageIds.length} trang đã chọn</span>
                            <div className="workbench-bulk-shortcuts">
                              <button type="button" disabled={props.busy || acting} onClick={() => void tagSelectedPages('ch')}>
                                Hán/Nôm
                              </button>
                              <button type="button" disabled={props.busy || acting} onClick={() => void tagSelectedPages('vi')}>
                                Quốc ngữ
                              </button>
                              <button type="button" disabled={props.busy || acting} onClick={() => void tagSelectedPages('both')}>
                                Cả hai
                              </button>
                            </div>
                            <select
                              aria-label="Nhãn khác áp dụng cho trang đã chọn"
                              value={bulkCategory}
                              disabled={props.busy}
                              onChange={(event) =>
                                setBulkCategory(event.target.value as Category)
                              }
                            >
                              <option value="intro">Giới thiệu</option>
                              <option value="ref">Chú thích</option>
                              <option value="toc">Mục lục</option>
                              <option value="blank">Trang trắng</option>
                              <option value="misc">Khác</option>
                            </select>
                            <button
                              type="button"
                              className="secondary-button"
                              disabled={props.busy || acting}
                              onClick={() => void tagSelectedPages(bulkCategory)}
                            >
                              Gắn nhãn đã chọn
                            </button>
                          </div>
                        )}
                      </div>
                      <div className="workbench-tags" role="group" aria-label={`Một nhãn nội dung cho trang ${page.number}`}>
                        <button
                          aria-pressed={page.category === 'ch'}
                          disabled={props.busy || acting}
                          onClick={() => props.onPatch({ category: 'ch' })}
                        >
                          文 Hán/Nôm
                        </button>
                        <button
                          aria-pressed={page.category === 'vi'}
                          disabled={props.busy || acting}
                          onClick={() => props.onPatch({ category: 'vi' })}
                        >
                          Aa Quốc ngữ
                        </button>
                        <button
                          aria-pressed={page.category === 'both'}
                          disabled={props.busy || acting}
                          onClick={() => props.onPatch({ category: 'both' })}
                        >
                          Cả hai
                        </button>
                        <label>
                          <input
                            type="checkbox"
                            checked={!!skipped}
                            disabled={props.busy || acting}
                            onChange={(event) =>
                              props.onPatch({
                                ocr_skip: event.target.checked,
                                ...(page.category === 'blank' && !event.target.checked
                                  ? { category: 'both' as Category }
                                  : {}),
                              })
                            }
                          />
                          Bỏ qua OCR
                        </label>
                        <select
                          aria-label="Nhãn nội dung khác cho trang"
                          disabled={props.busy || acting}
                          value={
                            ['intro', 'ref', 'toc', 'blank', 'misc'].includes(page.category)
                              ? page.category
                              : ''
                          }
                          onChange={(event) => props.onPatch({ category: event.target.value as Category })}
                        >
                          <option value="" disabled>Nhãn khác</option>
                          <option value="intro">Giới thiệu</option>
                          <option value="ref">Chú thích</option>
                          <option value="toc">Mục lục</option>
                          <option value="blank">Trang trắng</option>
                          <option value="misc">Khác</option>
                        </select>
                      </div>
                      {page.category !== 'blank' && page.category !== 'misc' &&
                        (page.ocr_languages.includes('han') ? (
                          <label className="workbench-region-language">
                            Chiều đọc riêng của trang {page.number}
                            <select
                              aria-label={`Chiều đọc riêng của trang ${page.number}`}
                              value={page.reading_direction_override ?? ''}
                              disabled={props.busy || acting}
                              onChange={(event) => props.onPatch({
                                reading_direction_override: event.target.value
                                  ? Number(event.target.value) as 1 | 2
                                  : null,
                              })}
                            >
                              <option value="">Theo sách · {layout.reading_direction === 1 ? 'dọc' : 'ngang trái sang phải'}</option>
                              <option value={2}>Ngang · trái sang phải</option>
                              <option value={1}>Dọc · trên xuống dưới, cột phải sang trái</option>
                            </select>
                          </label>
                        ) : (
                          <div className="workbench-region-language">
                            Chiều đọc trang {page.number}
                            <strong>Ngang · trái sang phải</strong>
                          </div>
                        ))}
                      <div className="workbench-page-links" aria-label="Liên kết trang để căn chỉnh song ngữ">
                        <strong>Trang liên kết · căn chỉnh song ngữ</strong>
                        <small>Chọn các trang có câu Hán Nôm và Quốc ngữ nằm lệch trang. Liên kết được lưu ngay; OCR và box hiện tại vẫn giữ nguyên.</small>
                        <input
                          type="search"
                          aria-label="Tìm trang để liên kết"
                          placeholder="Tìm số trang…"
                          value={linkSearch}
                          onChange={(event) => setLinkSearch(event.target.value)}
                        />
                        <div className="workbench-link-options">
                          {pages.filter((candidate) => candidate.id !== page.id &&
                            (!linkSearch || String(candidate.number).includes(linkSearch)) &&
                            (!candidate.ocr_skip || page.linked_page_ids.includes(candidate.id)))
                            .map((candidate) => (
                              <label key={candidate.id}>
                                <input
                                  type="checkbox"
                                  checked={page.linked_page_ids.includes(candidate.id)}
                                  disabled={props.busy || acting}
                                  onChange={(event) => void props.onSaveLinks(page.id,
                                    event.target.checked
                                      ? [...page.linked_page_ids, candidate.id]
                                      : page.linked_page_ids.filter((id) => id !== candidate.id),
                                  ).catch(props.onError)}
                                />
                                Trang {String(candidate.number).padStart(3, '0')} · {candidate.ocr_languages.length === 2 ? 'cả hai' : candidate.ocr_languages[0] === 'han' ? 'Hán Nôm' : 'Quốc ngữ'}
                              </label>
                            ))}
                        </div>
                        {!!page.linked_page_ids.length && <small>Đã liên kết {page.linked_page_ids.length} trang: {page.linked_page_ids.map((id) => pages.find((item) => item.id === id)?.number).filter(Boolean).join(', ')}</small>}
                      </div>
                    </div>
                  )}
                  {step === 3 && (
                    <div className="workbench-ocr-summary">
                      <strong>OCR toàn bộ sách</strong>
                      <span>
                        {pages.filter((p) => !p.ocr_skip && p.category !== 'blank').length} trang xử
                        lý · {pages.filter((p) => p.ocr_skip || p.category === 'blank').length}{' '}
                        trang bỏ qua
                      </span>
                      <span>
                        Hán/Nôm:{' '}
                        {
                          pages.filter(
                            (p) =>
                              !p.ocr_skip &&
                              p.category !== 'blank' &&
                              p.ocr_languages.includes('han'),
                          ).length
                        }{' '}
                        trang · Quốc ngữ:{' '}
                        {
                          pages.filter(
                            (p) =>
                              !p.ocr_skip &&
                              p.category !== 'blank' &&
                              p.ocr_languages.includes('vi'),
                          ).length
                        }{' '}
                        trang
                      </span>
                      <strong>
                        {unfinishedPages.length} trang chưa hoàn thành ·{' '}
                        {eligiblePages.length - unfinishedPages.length} đã hoàn thành
                      </strong>
                      {page && (
                        <span>
                          Trang {page.number}:{' '}
                          {hasContent(page) ? 'Có kết quả để Gán nhãn' : 'Đang chờ kết quả OCR'}
                        </span>
                      )}
                      {props.job && (
                        <div className="workbench-job-pages">
                          {stagePages.map((p) => {
                            const state = props.job?.pages.find((item) => item.page_id === p.id);
                            return (
                              <div key={p.id}>
                                <span>Trang {p.number}</span>
                                <div>
                                  <span>
                                    {p.status === 'done'
                                      ? 'Đã hoàn thành'
                                      : state?.status === 'running'
                                        ? `Đang OCR${props.job?.current_page?.page_id === p.id && props.job.current_language === 'vi' ? ' Quốc ngữ' : props.job?.current_page?.page_id === p.id && props.job.current_language === 'han' ? ' Hán Nôm' : ''}`
                                        : state?.status === 'partial'
                                          ? 'Hán Nôm đã lưu · Quốc ngữ lỗi'
                                          : state?.status === 'failed'
                                            ? 'OCR gặp lỗi'
                                            : state?.status === 'skipped' || hasContent(p)
                                              ? 'Đã có OCR · Chờ Gán nhãn'
                                              : 'Chờ OCR'}
                                  </span>
                                  {state?.error && <small className="workbench-job-page-error">{state.error}</small>}
                                </div>
                              </div>
                            );
                          })}
                        </div>
                      )}
                    </div>
                  )}
                  {step === 4 && (
                    <>
                      {sources[language] && (
                        <div className="workbench-sourcebar">
                          <label>
                            Nguồn đối chiếu{' '}
                            <select
                              aria-label="Nguồn đối chiếu đã tải"
                              value={effectiveSource}
                              onChange={(event) => setSource(event.target.value as 'ocr' | 'txt')}
                            >
                              <option value="ocr">OCR</option>
                              <option value="txt">TXT đã tải</option>
                            </select>
                          </label>
                          {effectiveSource === 'txt' && (
                            <small>{sources[language]?.filename}</small>
                          )}
                        </div>
                      )}
                      <div className="workbench-editor" ref={editor}>
                        {effectiveSource === 'txt' && (
                          <label className="workbench-txt-reference">
                            {sources[language]?.filename || 'Chọn TXT để đối chiếu'}
                            <textarea
                              className={language === 'han' ? 'han-text' : ''}
                              aria-label="Bản TXT đối chiếu"
                              readOnly
                              value={referenceForPage(sources[language]?.text || '', page.number)}
                              placeholder="Không có đoạn TXT khớp số trang này."
                            />
                          </label>
                        )}
                        {!characterEditing && (
                          <label className="workbench-page-text">
                            {effectiveSource === 'txt' ? 'Bản Gán nhãn' : 'Văn bản OCR'}
                            <textarea
                              className={language === 'han' ? 'han-text' : ''}
                              aria-label={`Văn bản ${language === 'han' ? 'Nôm' : 'Quốc ngữ'}`}
                              disabled={props.busy || acting}
                              readOnly={language === 'han' && boxes.length > 0}
                              value={text}
                              placeholder="Văn bản sẽ xuất hiện khi OCR hoàn tất."
                              onChange={(event) => {
                                const value = event.target.value;
                                props.onPatch({
                                  [textKey]: value,
                                  ...(language === 'vi'
                                    ? {
                                        vi_boxes: syncTextLinesToBoxes(boxes, text, value),
                                        ...(targetWordCount(text) !== targetWordCount(value)
                                          ? {
                                              boxes: page.boxes.map((box) => ({
                                                ...box,
                                                review_kind: undefined,
                                                review_marks: undefined,
                                              })),
                                            }
                                          : {}),
                                      }
                                    : {}),
                                });
                              }}
                              onSelect={(event) => {
                                const input = event.currentTarget,
                                  position = input.selectionStart;
                                setSelectedTargetWord(targetWordIndexAt(input.value, position));
                                let cursor = 0;
                                const box = boxes.find((item) => {
                                  const start = input.value.indexOf(item.transcription, cursor);
                                  if (start < 0) return false;
                                  cursor = start + item.transcription.length;
                                  return position >= start && position < cursor;
                                });
                                if (box) {
                                  setSelected(box.id);
                                  setShowBoxes(true);
                                  setEditingRegions(false);
                                }
                              }}
                            />
                          </label>
                        )}
                        {characterEditing && (
                          <CharacterBoxEditor
                            boxes={boxes}
                            selected={selected}
                            selectedIds={selectedBoxIds}
                            disabled={props.busy || acting}
                            onSelect={(id) => {
                              setSelected(id);
                              setSelectedBoxIds([id]);
                              setShowBoxes(true);
                            }}
                            onHover={(id) => {
                              if (selectedBoxIds.length > 1) return;
                              setSelected(id);
                              setSelectedBoxIds([id]);
                              setShowBoxes(true);
                            }}
                            onChange={updateBox}
                            onLookup={props.onLookup}
                            onOrder={(box, order) => {
                              const next = boxes.map((item, index) => ({
                                ...item,
                                review_order: item.id === box.id ? order : item.review_order === undefined ? index + 1 : item.review_order,
                              }));
                              const values = next.map((item) => item.review_order);
                              const valid = values.every((value) => value != null) &&
                                new Set(values).size === next.length &&
                                [...values].sort((a, b) => a! - b!).every((value, index) => value === index + 1);
                              props.onPatch({
                                boxes: next,
                                ...(valid ? {
                                  source_text: groupCharacterBoxes(next, readingDirection)
                                    .map((row) => row.map((item) => item.transcription).join('')).join('\n'),
                                } : {}),
                              });
                            }}
                            onRenumber={() => {
                              const chosen = new Set(selectedBoxIds);
                              if (chosen.size < 2) return;
                              const reordered = groupCharacterBoxes(boxes, readingDirection, false)
                                .flat()
                                .map((box, index) => ({ ...box, review_order: index + 1 }));
                              props.onPatch({
                                boxes: reordered,
                                source_text: groupCharacterBoxes(reordered, readingDirection)
                                  .map((row) => row.map((item) => item.transcription).join('')).join('\n'),
                              });
                            }}
                            onMark={markBox}
                            onMarkAll={markAllBoxes}
                            pairedWords={targetWords}
                          />
                        )}
                        {!characterEditing && boxes.length > 0 && (
                          <div className="workbench-box-lines">
                            <small>{boxes.length} vùng chữ</small>
                            {language === 'han' && step === 4 && <small> · Alt + 1: đen; 2: đỏ; 3: thiếu từ điển</small>}
                            {boxes.map((box, index) => {
                              let offset = 0;
                              let reviewOffset = 0;
                              const rowWordStart = targetWordStart(index);
                              const reviewKind = language === 'han' ? box.review_kind || 'match' : undefined;
                              return (
                                <div
                                  key={box.id}
                                  data-row={box.id}
                                  className={`workbench-box-row ${selected === box.id ? 'selected' : ''} ${reviewKind ? `review-${reviewKind}` : ''}`}
                                  onMouseEnter={() => {
                                    if (!editingRegions) {
                                      setSelected(box.id);
                                      if (language === 'vi' && targetWordCount(box.transcription))
                                        setSelectedTargetWord(rowWordStart);
                                      setShowBoxes(true);
                                    }
                                  }}
                                >
                                  <span className="line-num">{index + 1}</span>
                                  <div>
                                    {language === 'han' ? (
                                      <>
                                        <div className="workbench-phrase-input">
                                        <textarea
                                          className="han-text"
                                          aria-label={`Vùng chữ ${index + 1}`}
                                          rows={2}
                                          ref={(element) => {
                                            if (element) phraseInputs.current.set(box.id, element);
                                            else phraseInputs.current.delete(box.id);
                                          }}
                                          style={{
                                            color:
                                              reviewKind === 'mismatch' || reviewKind === 'unknown'
                                                ? '#c00'
                                                : undefined,
                                          }}
                                          disabled={props.busy || acting}
                                          readOnly={step !== 4}
                                          value={box.transcription}
                                            onSelect={(event) => {
                                              const { selectionStart, selectionEnd } = event.currentTarget;
                                              if (selectionEnd > selectionStart)
                                                phraseSelections.current.set(box.id, { start: selectionStart, end: selectionEnd });
                                            }}
                                          onFocus={() => {
                                            setEditingRegions(false);
                                            setSelected(box.id);
                                            setShowBoxes(true);
                                          }}
                                          onChange={(event) => updateBox(box, event.target.value)}
                                        />
                                        {step === 4 && <button
                                          type="button"
                                          className="character-dictionary-button phrase-dictionary-button"
                                          aria-label={`Tra từ đang chọn trong vùng ${index + 1}`}
                                          title="Bôi đen chữ hoặc từ rồi tra cứu"
                                          disabled={props.busy || acting}
                                          onMouseDown={(event) => event.preventDefault()}
                                          onClick={() => lookupPhraseSelection(box)}
                                        >
                                          <Search size={12} />
                                        </button>}
                                        </div>
                                        <div className="workbench-characters han-text">
                                          {Array.from(box.transcription).map((character) => {
                                            const charIndex = offset;
                                            const characterIndex = reviewOffset++;
                                            offset += character.length;
                                            const characterReviewKind = boxReviewKindAt(box, characterIndex);
                                            return (
                                              <button
                                                key={charIndex}
                                                className={`review-${characterReviewKind}`}
                                                style={{ color: characterReviewKind === 'mismatch' || characterReviewKind === 'unknown' ? '#c00' : '#000' }}
                                                title={`Tra chữ ${character}`}
                                                onMouseEnter={() => {
                                                  setEditingRegions(false);
                                                  setSelected(box.id);
                                                  setShowBoxes(true);
                                                }}
                                                onFocus={() => {
                                                  setEditingRegions(false);
                                                  setSelected(box.id);
                                                  setShowBoxes(true);
                                                }}
                                                onClick={() => {
                                                  if (step === 4) props.onLookup(box, character, charIndex);
                                                }}
                                              >
                                                {character}
                                              </button>
                                            );
                                          })}
                                        </div>
                                      </>
                                    ) : (
                                      <VietnameseBoxEditor
                                        box={box}
                                        index={index}
                                        rowWordStart={rowWordStart}
                                        reviewKinds={page.boxes.map((item) => item.review_kind)}
                                        disabled={step !== 4 || props.busy || acting}
                                        onChange={updateBox}
                                        onSelectWord={(wordIndex, boxId) => {
                                          setEditingRegions(false);
                                          setSelected(boxId);
                                          selectTargetWord(wordIndex, boxId);
                                        }}
                                        onFocus={() => {
                                          setEditingRegions(false);
                                          setSelected(box.id);
                                          if (targetWordCount(box.transcription))
                                            setSelectedTargetWord(rowWordStart);
                                          setShowBoxes(true);
                                        }}
                                      />
                                    )}
                                  </div>
                                </div>
                              );
                            })}
                          </div>
                        )}
                      </div>
                    </>
                  )}
                  <div className="workbench-confirm">
                    {step !== 4 ? (
                      <>
                        <button
                          className={step === 2 ? 'primary-button' : 'secondary-button'}
                          disabled={
                            props.busy ||
                            acting ||
                            !layoutReady ||
                            layoutSaving ||
                            layoutError ||
                            uploading
                          }
                          onClick={() => (step === 2 ? continueToOCR() : goToStep(2))}
                        >
                          {step === 2 ? (
                            <>
                              Tiếp tục: Lưu & OCR <ArrowRight size={14} />
                            </>
                          ) : (
                            <>
                              <ArrowLeft size={14} />
                              Gắn nhãn trang
                            </>
                          )}
                        </button>
                        {step === 3 && (
                          <button
                            className="text-button"
                            disabled={props.busy || acting || !page}
                            onClick={() => {
                              if (page) openReview(page.id);
                            }}
                          >
                            Gán nhãn trang {page.number} <ArrowRight size={14} />
                          </button>
                        )}
                      </>
                    ) : (
                      <>
                        <span role="status">
                          {props.dirty ? 'Chưa lưu' : page.status === 'done' ? 'Đã lưu & hoàn thành' : 'Chưa hoàn thành'}
                        </span>
                        <div className="workbench-confirm-actions">
                        <button
                          className="primary-button"
                          disabled={
                            props.busy ||
                            acting ||
                            props.recognizingBox ||
                            layoutSaving ||
                            layoutError ||
                            uploading ||
                            (!skipped &&
                              ['running', 'pending'].includes(
                                props.job?.pages.find((item) => item.page_id === page.id)?.status ||
                                  '',
                              ) &&
                              ['running', 'pausing'].includes(props.job?.status || ''))
                          }
                          onClick={() => void completePage()}
                        >
                          <Save size={15} />
                          Lưu & hoàn thành
                        </button>
                        {!skipped && <label className="workbench-phrase-toggle">
                          <input type="checkbox" checked={ocrGranularity === 'phrase'}
                            disabled={props.busy || acting}
                            onChange={(event) => props.onPatch({ ocr_granularity: event.target.checked ? 'phrase' : 'character' })} />
                          Chia theo cụm
                        </label>}
                        </div>
                      </>
                    )}
                  </div>
                </aside>
              </>
            ) : (
              <div className="workbench-empty">
                {step === 3
                  ? unfinishedPages.length
                    ? 'Không có trang phù hợp với bộ lọc.'
                    : eligiblePages.length
                      ? 'Quyển đã hoàn thành. Không còn trang nội dung chưa xác nhận.'
                      : 'Không có trang nội dung cần xử lý. Kiểm tra nhãn ở bước 2.'
                  : 'Đang tải trang sách…'}
              </div>
            )}
          </div>
          <div className="workbench-navigation">
            <span>
              {step === 4 ? 'Nháp được giữ khi chuyển trang. Bấm Lưu & hoàn thành để ghi kết quả.' : 'Chỉnh sửa được tự động lưu.'}
            </span>
            <div>
              <button
                className="icon-button"
                aria-label="Trang trước"
                disabled={props.busy || acting || pageIndex <= 0}
                onClick={() => props.onNavigate(navigationPages[pageIndex - 1].id)}
              >
                <ChevronLeft size={17} />
              </button>
              <button
                className="icon-button"
                aria-label="Trang tiếp theo"
                disabled={
                  props.busy ||
                  acting ||
                  pageIndex >= navigationPages.length - 1
                }
                onClick={() => props.onNavigate(navigationPages[pageIndex + 1].id)}
              >
                <ChevronRight size={17} />
              </button>
            </div>
          </div>
        </>
      )}
    </section>
  );
}
