import assert from 'node:assert/strict';
import { cleanExportText } from '../src/alignmentText.ts';
import { referencesForPart } from '../src/components/alignmentReferences.ts';
import { reviewColorsForAlignmentRows } from '../src/reviewColors.ts';

assert.equal(cleanExportText(' 12 THIÊN, ٣ ĐỊA!\n2024 NGƯỜI ', 'target').text, 'thiên địa người');
assert.equal(cleanExportText(' 𡗶 123 地。\n玄黃 ', 'source').text, '𡗶地玄黃');
const cleaned = cleanExportText('  1 THIÊN   ĐỊA! ', 'target', Array(17).fill('mismatch'));
assert.equal(cleaned.colors.length, Array.from(cleaned.text).length);
assert.ok(Array.from(cleaned.text).every((char, index) => char === ' ' || cleaned.colors[index] === 'mismatch'));
const refs = [{ box_id: 'a', start: 0, end: 2 }, { box_id: 'b', start: 0, end: 2 }];
assert.deepEqual(referencesForPart(refs, '𡗶地玄黃', '𡗶地'), [{ box_id: 'a', start: 0, end: 2 }]);
assert.deepEqual(referencesForPart(refs, '𡗶地玄黃', '玄黃', true), [{ box_id: 'b', start: 0, end: 2 }]);
assert.deepEqual(referencesForPart([{ box_id: 'vi', start: 0, end: 9 }], 'thiên địa', 'địa', true), [
  { box_id: 'vi', start: 6, end: 9 },
]);
console.log('Result cleanup, Unicode colors and split box references: OK');

const boxes = [
  { id: 'old', transcription: '玄黃', points: [], review_kind: 'mismatch' },
  { id: 'current', transcription: '天地', points: [], review_kind: 'match',
    review_marks: [{ start: 1, end: 2, kind: 'mismatch' }] },
];
const row = { id: 'pair', sentence_id: 'Book.001.1', source: '天地', target: 'thiên địa',
  source_page_id: 'page', source_line_index: 0 };
assert.deepEqual(reviewColorsForAlignmentRows([row], boxes, 'source').get('pair'), ['match', 'mismatch']);
const half = { ...row, source: '地', target: 'địa', source_refs: [{ box_id: 'current', start: 1, end: 2 }] };
assert.deepEqual(reviewColorsForAlignmentRows([half], boxes, 'source').get('pair'), ['mismatch']);
console.log('Legacy line mismatch and split range colors: OK');
