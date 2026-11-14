import assert from 'node:assert/strict';
import { allocateAlignmentOcrBoxes, boundsFromOcrBoxes, characterCount } from '../src/components/alignmentOcrBoxes.ts';
import { splitAlignmentText } from '../src/components/alignmentSplit.ts';
import { groupCharacterBoxes } from '../src/components/boxText.ts';
import { reviewColorsForAlignmentRows, reviewColorsForText } from '../src/reviewColors.ts';

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
