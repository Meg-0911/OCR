import assert from 'node:assert/strict';
import { allocateAlignmentOcrBoxes, boundsFromOcrBoxes, characterCount } from '../src/components/alignmentOcrBoxes.ts';
import { splitAlignmentText } from '../src/components/alignmentSplit.ts';
import { groupCharacterBoxes } from '../src/components/boxText.ts';
import { reviewColorsForAlignmentRows, reviewColorsForText, reviewColorsForLines, withReviewMarks, targetGlyphReviews } from '../src/reviewColors.ts';
import { reconcileInputRevisions, patchDraft, draftPatch } from '../src/drafts.ts';
import { pageStatusLabel } from '../src/pageStatus.ts';
import { cleanAlignmentText } from '../src/alignmentText.ts';

function box(id, transcription, order, x, y) {
  return {
    id, transcription, review_order: order,
    points: [[x, y], [x + 10, y], [x + 10, y + 10], [x, y + 10]],
  };
}

const ocr = [
  box('fifth', '', 5, 40, 0),
  box('first', '', 1, 0, 0),
  box('third', '', 3, 20, 0),
  box('second', '', 2, 10, 0),
  box('fourth', '', 4, 30, 0),
];
const rows = [
  { id: 'one', source: '上岸', target: '...' },
  { id: 'two', source: '姑、關 文', target: '...' },
];
const matches = allocateAlignmentOcrBoxes(ocr, rows);
assert.deepEqual(matches.get('one')?.map((item) => item.id), ['first', 'second']);
assert.deepEqual(matches.get('two')?.map((item) => item.id), ['third', 'fourth', 'fifth']);
assert.deepEqual(boundsFromOcrBoxes(matches.get('two'), 'horizontal'),
  [[20, 0], [50, 0], [50, 10], [20, 10]]);
assert.equal(boundsFromOcrBoxes(matches.get('two'), 'vertical'), null);
assert.equal(allocateAlignmentOcrBoxes(ocr, [{ id: 'whole', source: '上岸姑關文', target: '...' }]).get('whole')?.length, 5);
assert.equal(allocateAlignmentOcrBoxes(ocr, [{ id: 'too-long', source: '上岸姑關文天', target: '...' }]).size, 0);
assert.equal(characterCount(' 姑、關 文 '), 3);

const repeated = [box('a', '上', 1, 0, 0), box('b', '上', 2, 10, 0)];
const repeatMatches = allocateAlignmentOcrBoxes(repeated, [
  { id: 'first-repeat', source: '上', target: '...' },
  { id: 'second-repeat', source: '上', target: '...' },
]);
assert.equal(repeatMatches.get('first-repeat')?.[0].id, 'a');
assert.equal(repeatMatches.get('second-repeat')?.[0].id, 'b');

const horizontalLines = [
  box('line-1-first', '甲', 1, 0, 0),
  box('line-1-second', '乙', 2, 10, 0),
  box('line-2-first', '丙', 3, 0, 30),
  box('line-2-second', '丁', 4, 10, 30),
];
assert.deepEqual(
  groupCharacterBoxes(horizontalLines, 2).map((group) => group.map((item) => item.id)),
  [['line-1-first', 'line-1-second'], ['line-2-first', 'line-2-second']],
);

const verticalColumns = [
  box('column-1-first', '甲', 1, 40, 0),
  box('column-1-second', '乙', 2, 40, 10),
  box('column-2-first', '丙', 3, 10, 0),
  box('column-2-second', '丁', 4, 10, 10),
];
assert.deepEqual(
  groupCharacterBoxes(verticalColumns, 1).map((group) => group.map((item) => item.id)),
  [['column-1-first', 'column-1-second'], ['column-2-first', 'column-2-second']],
);

assert.deepEqual(
  splitAlignmentText('天地玄黃', 'một hai ba bốn năm sáu bảy tám', 'source', 2),
  { source: ['天地', '玄黃'], target: ['một hai', 'ba bốn năm sáu bảy tám'] },
);
assert.deepEqual(
  splitAlignmentText('天地玄黃', 'một hai ba bốn năm sáu bảy tám', 'target', 7),
  { source: ['天地', '玄黃'], target: ['một hai', 'ba bốn năm sáu bảy tám'] },
);
assert.deepEqual(
  splitAlignmentText('天地\n玄黃', 'Trời đất  huyền vàng', 'source', 3),
  { source: ['天地', '玄黃'], target: ['Trời đất', 'huyền vàng'] },
);
assert.equal(splitAlignmentText('天地', 'Trời đất', 'source', 0), null);
assert.equal(splitAlignmentText('天地玄黃', 'Trời đất huyền vàng', undefined, 2), null);

const coloredRows = reviewColorsForAlignmentRows([
  { id: 'colored-first', source: '甲', target: 'sai' },
  { id: 'colored-second', source: '乙', target: 'đúng' },
], [
  { id: 'red-word', transcription: '甲', review_kind: 'mismatch', points: [] },
  { id: 'black-word', transcription: '乙', review_kind: 'match', points: [] },
], 'target');
assert.deepEqual(coloredRows.get('colored-first'), ['mismatch', 'mismatch', 'mismatch']);
assert.deepEqual(coloredRows.get('colored-second'), ['match', 'match', 'match', 'match']);

const reorderedBoxes = [
  { id: 'third-order', transcription: '丙', review_kind: 'match', review_order: 3, points: [] },
  { id: 'first-order', transcription: '甲', review_kind: 'match', review_order: 1, points: [] },
  { id: 'second-order', transcription: '乙', review_kind: 'mismatch', review_order: 2, points: [] },
];
assert.deepEqual(
  reviewColorsForText('甲乙丙', reorderedBoxes, 'source'),
  ['match', 'mismatch', 'match'],
);
assert.deepEqual(
  reviewColorsForText('một hai ba', reorderedBoxes, 'target'),
  ['match', 'match', 'match', 'match', 'mismatch', 'mismatch', 'mismatch', 'match', 'match', 'match'],
);

assert.deepEqual(
  reviewColorsForText('天地方', [{
    id: 'phrase-box', transcription: '天地方', review_kind: 'mismatch',
    review_marks: [{ start: 1, end: 2, kind: 'match' }], points: [],
  }], 'source'),
  ['mismatch', 'match', 'mismatch'],
);

console.log('OCR alignment boxes: OK');

const phraseInput = [
  { ...box('phrase-one', '𡗶地', 1, 0, 0), export_group: 'line-one', review_kind: 'match',
    review_marks: [{ start: 1, end: 2, kind: 'mismatch' }] },
  { ...box('phrase-two', '玄黃', 2, 0, 30), export_group: 'line-two', review_kind: 'match',
    review_marks: [{ start: 0, end: 1, kind: 'mismatch' }] },
];
assert.deepEqual(reviewColorsForText('𡗶地\n玄黃', phraseInput, 'source'), ['match', 'mismatch', 'match', 'mismatch', 'match']);
assert.deepEqual(reviewColorsForLines('trời đất\nhuyền hoàng', phraseInput, 'target'), [
  ['match','match','match','match','match','mismatch','mismatch','mismatch'],
  ['mismatch','mismatch','mismatch','mismatch','mismatch','match','match','match','match','match','match'],
]);
assert.deepEqual(withReviewMarks('𡗶地玄', [], [{ source_start: 1, source_end: 2, kind: 'mismatch' }], 'source'), ['match','mismatch','match']);
const shorterFirstTarget = targetGlyphReviews('trời\nhuyền hoàng', phraseInput);
assert.deepEqual(shorterFirstTarget.map((glyph) => [glyph.box.id, glyph.index, glyph.kind]), [
  ['phrase-one',0,'match'], ['phrase-two',0,'mismatch'], ['phrase-two',1,'match'],
]);
assert.equal(reviewColorsForText('trời\nhuyền hoàng', phraseInput, 'target')[5], 'mismatch');
const storageData = new Map([
  ['nom-input-revision-required','previous'], ['nom-alignment-required','stale'], ['nom-session-required','stale'],
]);
const storage = {
  getItem: (key) => storageData.get(key) ?? null,
  setItem: (key, value) => storageData.set(key, value),
  removeItem: (key) => storageData.delete(key),
};
const reconciled = reconcileInputRevisions([
  { id: 'required', input_revision: 'latest' }, { id: 'unchanged', input_revision: '' },
], { old: { book_id: 'required' }, keep: { book_id: 'unchanged' }, outside: { book_id: 'outside' } }, storage);
assert.deepEqual(Object.keys(reconciled.drafts), ['keep']);
assert.deepEqual([...reconciled.replaced], ['required']);
assert.equal(storageData.has('nom-alignment-required'), false);
assert.equal(storageData.has('nom-session-required'), false);
assert.deepEqual(Object.keys(reconcileInputRevisions([
  { id: 'required', input_revision: 'latest' },
], { current: { book_id: 'required' } }, storage).drafts), ['current']);
console.log('Phrase colors, Unicode offsets and replacement drafts: OK');

const anchoredRows = [
  { id: 'second', sentence_id: 'Book.003.2', source: '玄黃', target: 'huyền hoàng', source_page_id: 'page', source_line_index: 1 },
  { id: 'first', sentence_id: 'Book.003.1', source: '𡗶地', target: 'trời', source_page_id: 'page', source_line_index: 0 },
];
assert.deepEqual(reviewColorsForAlignmentRows(anchoredRows, phraseInput, 'source').get('second'), ['mismatch', 'match']);
const characterLines = [
  { ...box('first-one', '天', 1, 0, 0), review_kind: 'match' },
  { ...box('first-two', '地', 2, 12, 0), review_kind: 'mismatch' },
  { ...box('second-one', '玄', 3, 0, 40), review_kind: 'mismatch' },
  { ...box('second-two', '黃', 4, 12, 40), review_kind: 'match' },
];
assert.equal(reviewColorsForText('trời\nhuyền hoàng', characterLines, 'target')[5], 'mismatch');
assert.equal(pageStatusLabel({ category: 'ch', status: 'pending', review_state: 'unchecked' }), 'Chưa kiểm tra');
assert.equal(pageStatusLabel({ category: 'ch', status: 'pending', review_state: 'in_progress' }), 'Chưa hoàn thành');
assert.equal(pageStatusLabel({ category: 'ch', status: 'done' }), 'Đã hoàn thành');
assert.equal(pageStatusLabel({ category: 'misc', status: 'pending' }), 'Chưa phân loại');
assert.equal(pageStatusLabel({ category: 'misc', status: 'pending', ocr_skip: true }), 'Bỏ qua');
console.log('Stable phrase mapping and independent page completion: OK');

const incompleteRows = [
  { id: 'empty-source', sentence_id: 'Book.003.1', source: '', target: 'chưa có', source_page_id: 'p', source_line_index: 0, marks: [] },
  { id: 'actual', sentence_id: 'Book.003.2', source: '玄黃', target: 'huyền hoàng', source_page_id: 'p', source_line_index: 1, marks: [] },
];
const incompleteBoxes = [{ ...phraseInput[1], alignment_id: 'actual' }];
const incompleteColors = reviewColorsForText('chưa có\nhuyền hoàng', incompleteBoxes, 'target', 2, incompleteRows);
assert.equal(incompleteColors[0], 'match');
assert.equal(incompleteColors[8], 'mismatch');
const incompleteGlyphs = targetGlyphReviews('chưa có\nhuyền hoàng', incompleteBoxes, 2, incompleteRows);
assert.equal(incompleteGlyphs[0], undefined);
assert.equal(incompleteGlyphs[2].box.id, 'phrase-two');
assert.equal(incompleteGlyphs[2].index, 0);
console.log('Empty source phrase cannot shift colors or selected glyphs to another phrase: OK');

const editorPage = {
  id: 'page', book_id: 'book', version: 7, category: 'ch', boxes: phraseInput,
  source_text: '𡗶地\n玄黃', target_text: 'trời đất\nhuyền hoàng', review_rows: anchoredRows,
  export_boxes: phraseInput,
};
const edit = patchDraft(undefined, editorPage, { source_text: '天地\n玄黃' }, false);
assert.deepEqual(draftPatch(edit), { source_text: '天地\n玄黃' });
assert.equal(edit.review_rows, undefined);
assert.equal(edit.export_boxes, undefined);
const continuedEdit = patchDraft({ ...editorPage, ...edit }, editorPage, { target_text: 'trời' }, false);
assert.deepEqual(draftPatch(continuedEdit), { source_text: '天地\n玄黃', target_text: 'trời' });
assert.equal(continuedEdit.review_rows, undefined);
assert.equal(continuedEdit.version, 7);
console.log('Typing drafts retain only editable changes and their saved version: OK');

const dirtyHan = ' ١，𡗶 地。\u200b\n\n ٢\n玄黃！\ufeff';
const dirtyHanColors = Array.from(dirtyHan).map((char) => char === '地' || char === '黃' ? 'mismatch' : 'match');
assert.deepEqual(cleanAlignmentText(dirtyHan, 'source', dirtyHanColors), {
  text: '𡗶地\n玄黃', colors: ['match', 'mismatch', 'match', 'match', 'mismatch'],
});
const dirtyVietnamese = ' 660- THIÊN,   ĐỊA!\r\n\n ١٢٣\u200b\nNGƯỜI ②.\t';
const dirtyVietnameseColors = Array.from(dirtyVietnamese).map((char) => 'ĐỊA'.includes(char) ? 'mismatch' : 'match');
const cleanedVietnamese = cleanAlignmentText(dirtyVietnamese, 'target', dirtyVietnameseColors);
assert.equal(cleanedVietnamese.text, 'thiên địa\nngười');
assert.equal(cleanedVietnamese.colors.length, Array.from(cleanedVietnamese.text).length);
assert.deepEqual(cleanedVietnamese.colors.slice(6, 9), ['mismatch', 'mismatch', 'mismatch']);
assert.equal(cleanAlignmentText('□𡗶一', 'source').text, '□𡗶一');
assert.equal(cleanAlignmentText(' 123，。\u200b\n', 'source').text, '');
assert.deepEqual(cleanAlignmentText(cleanedVietnamese.text, 'target', cleanedVietnamese.colors), cleanedVietnamese);
const numberedTarget = '660- THIÊN, ĐỊA!';
const numberedColors = reviewColorsForText(numberedTarget, phraseInput.slice(0, 1), 'target', 2, undefined, true);
assert.deepEqual(cleanAlignmentText(numberedTarget, 'target', numberedColors).colors,
  ['match','match','match','match','match','match','mismatch','mismatch','mismatch']);
const numberedRow = [{ ...anchoredRows[1], target: numberedTarget }];
const numberedRowColors = reviewColorsForText(numberedTarget, phraseInput.slice(0, 1), 'target', 2, numberedRow, true);
assert.deepEqual(cleanAlignmentText(numberedTarget, 'target', numberedRowColors).colors,
  ['match','match','match','match','match','match','mismatch','mismatch','mismatch']);
console.log('Visible alignment cleanup keeps lines, Vietnamese word spaces, and Unicode review colors: OK');
