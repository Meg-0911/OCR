import assert from 'node:assert/strict';
import { defaultLinkedRows, reorderLinkedTargets } from '../src/components/linkedAlignment.ts';

const page = { id: 'han-page', number: 7, source_text: '一\n二\n三', boxes: [] };
const targets = ['A', 'B', 'C'].map((text, lineIndex) => ({ text, pageId: 'vi-page', lineIndex }));
let index = 0;
const rows = defaultLinkedRows(page, 'Sách', targets, () => `row-${++index}`);
assert.deepEqual(rows.map((row) => row.sentence_id), ['Sách.007.1', 'Sách.007.2', 'Sách.007.3']);
assert.deepEqual(rows.map((row) => row.target), ['A', 'B', 'C']);
assert(rows.every((row) => row.source_page_id === 'han-page' && row.page_linked));

const moved = reorderLinkedTargets(rows, { rowId: rows[1].id, target: targets[1] }, 0);
assert.deepEqual(moved.map((row) => row.target), ['B', 'A', 'C']);
assert.deepEqual(moved.map((row) => row.target_line_index), [1, 0, 2]);
assert.deepEqual(moved.map((row) => row.sentence_id), rows.map((row) => row.sentence_id));
assert.deepEqual(moved.map((row) => row.id), rows.map((row) => row.id));

const extra = { text: 'D', pageId: 'other-page', lineIndex: 0 };
const inserted = reorderLinkedTargets(moved, { target: extra }, 1);
assert.deepEqual(inserted.map((row) => row.target), ['B', 'D', 'C']);
assert.equal(inserted[1].target_page_id, 'other-page');
assert.equal(inserted[1].reviewed, false);
// Moving across several rows swaps only the selected pair, without shifting a range.
const swapped = reorderLinkedTargets(rows, { rowId: rows[2].id, target: targets[2] }, 0);
assert.deepEqual(swapped.map((row) => row.target), ['C', 'B', 'A']);
assert.strictEqual(swapped[1], rows[1]);
assert.deepEqual(swapped.map((row) => row.id), rows.map((row) => row.id));
// An empty destination releases the original assignment, without moving neighbours.
const emptyLast = rows.map((row, index) => index === 2
  ? { ...row, target: '', target_page_id: null, target_line_index: null } : row);
const filled = reorderLinkedTargets(emptyLast, { rowId: rows[0].id, target: targets[0] }, 2);
assert.deepEqual(filled.map((row) => row.target), ['', 'B', 'A']);
assert.strictEqual(filled[1], rows[1]);
// A stale pool selection that is already assigned cannot duplicate the target.
const fromPool = reorderLinkedTargets(rows, { target: targets[2] }, 0);
assert.deepEqual(fromPool.map((row) => row.target), ['C', 'B', 'A']);
assert.strictEqual(reorderLinkedTargets(rows, { target: extra }, -1), rows);
assert.strictEqual(reorderLinkedTargets(rows, { rowId: 'deleted', target: extra }, 0), rows);
console.log('Linked alignment defaults, local swaps, pool assignment, and IDs: OK');
