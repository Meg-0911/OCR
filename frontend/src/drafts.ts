import type { Page } from './types';

const editableFields = [
  'boxes', 'export_boxes', 'category', 'reading_direction', 'reading_direction_override', 'source_text', 'target_text', 'vi_boxes',
  'ocr_skip', 'source_regions', 'target_regions', 'ocr_languages', 'ocr_granularity',
] as const;
type EditableField = (typeof editableFields)[number];
export type Draft = Pick<Page, 'boxes' | 'category'> & Partial<Pick<Page, EditableField>> & {
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
    ...page, ...previous, ...patch,
    dirty_fields: Array.from(new Set([...(previous?.dirty_fields || []), ...keys])),
    manual_fields: Array.from(manualFields),
  };
}

export function afterAutomaticSave(snapshot: Draft, savedKeys: string[]): Draft | undefined {
  const dirty = (snapshot.dirty_fields || Object.keys(draftPatch(snapshot))).filter((key) => !savedKeys.includes(key));
  return dirty.length ? { ...snapshot, dirty_fields: dirty } : undefined;
}
