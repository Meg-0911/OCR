import type { Book, Page } from './types';

const editableFields = [
  'boxes', 'export_boxes', 'category', 'reading_direction', 'reading_direction_override', 'source_text', 'target_text', 'vi_boxes',
  'ocr_skip', 'source_regions', 'target_regions', 'ocr_languages', 'ocr_granularity',
] as const;
type EditableField = (typeof editableFields)[number];
export type Draft = Pick<Page, 'boxes' | 'category'> & Partial<Pick<Page, EditableField | 'input_revision' | 'book_id' | 'version' | 'id'>> & {
  dirty_fields?: string[];
  manual_fields?: string[];
};

export function draftPatch(draft: Draft, mode: 'all' | 'automatic' = 'all') {
  return Object.fromEntries(
    (draft.dirty_fields || editableFields)
      .filter((key) => editableFields.includes(key as EditableField) && key in draft &&
        (mode === 'all' || !draft.manual_fields?.includes(key)))
      .map((key) => [key, draft[key as EditableField]]),
  ) as Partial<Pick<Page, EditableField>>;
}

export function patchDraft(previous: Draft | undefined, page: Page, patch: Partial<Draft>, manual: boolean): Draft {
  const keys = Object.keys(patch).filter((key) => editableFields.includes(key as EditableField));
  const manualFields = new Set(previous?.manual_fields || []);
  for (const key of keys) {
    if (manual) manualFields.add(key);
    else manualFields.delete(key);
  }
  return {
    id: page.id, book_id: page.book_id, input_revision: page.input_revision,
    version: previous?.version ?? page.version, boxes: page.boxes, category: page.category,
    ...(previous ? draftPatch(previous) : {}), ...patch,
    dirty_fields: Array.from(new Set([...(previous?.dirty_fields || []), ...keys])),
    manual_fields: Array.from(manualFields),
  };
}

export function afterAutomaticSave(snapshot: Draft, savedKeys: string[]): Draft | undefined {
  const dirty = (snapshot.dirty_fields || Object.keys(draftPatch(snapshot))).filter((key) => !savedKeys.includes(key));
  return dirty.length ? { ...snapshot, dirty_fields: dirty } : undefined;
}

export function reconcileInputRevisions(books: Book[], drafts: Record<string, Draft>, storage: Pick<Storage, 'getItem' | 'setItem' | 'removeItem'>, known?: ReadonlyMap<string, string>) {
  const replaced = new Set<string>();
  const eligible = new Set(books.map((book) => book.id));
  for (const book of books) {
    const key = `nom-input-revision-${book.id}`;
    const revision = book.input_revision || '';
    let previous = known?.get(book.id);
    if (previous === undefined) {
      try { previous = storage.getItem(key) || ''; } catch { previous = ''; }
    }
    if (revision !== previous) {
      replaced.add(book.id);
      try {
        storage.removeItem(`nom-alignment-${book.id}`);
        storage.removeItem(`nom-session-${book.id}`);
      } catch { /* The server also rejects saves from an old input revision. */ }
    }
    try { storage.setItem(key, revision); } catch { /* Keep the current revision in memory. */ }
  }
  const kept = Object.fromEntries(Object.entries(drafts).filter(([, draft]) => {
    const owner = (draft as Partial<Page>).book_id;
    return !owner || (eligible.has(owner) && !replaced.has(owner));
  }));
  try { storage.setItem('nom-drafts-v1', JSON.stringify(kept)); } catch { /* Server state stays authoritative. */ }
  return { drafts: kept, replaced };
}
