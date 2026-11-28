import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import * as runtime from 'react/jsx-runtime';
import { renderToStaticMarkup } from 'react-dom/server';
import { reviewImageRegions, imageRegionBounds } from '../src/components/quickReviewRegions.ts';

const han = { id: 'han-box', transcription: '𤾓𢆥', points: [[100, 50], [120, 50], [120, 150], [100, 150]] };
const vi = { id: 'vi-box', transcription: 'Trăm năm', points: [[50, 20], [210, 20], [210, 40], [50, 40]] };
const source = { id: 'p46', number: 46, width: 600, height: 800, reading_direction: 1, boxes: [han], vi_boxes: [] };
const target = { ...source, id: 'p47', number: 47, reading_direction: 2, boxes: [], vi_boxes: [vi] };
const card = { row_id: 'r', index: 1, ranges: { source: [1, 2], target: [5, 8] }, row: {
  id: 'r', source: '𤾓𢆥', target: 'Trăm năm', source_page_id: 'p46', target_page_id: 'p47',
  source_refs: [{ box_id: 'han-box', start: 0, end: 2 }], target_refs: [{ box_id: 'vi-box', start: 0, end: 8 }],
} };
const original = JSON.stringify({ source, target, card });
let region = reviewImageRegions(card, source, 'source');
assert.deepEqual(region.line[0].points, han.points);
assert.deepEqual(region.focus[0].points, [[100, 100], [120, 100], [120, 150], [100, 150]]);
assert.equal(region.approximate, true, 'A subdivided phrase box must not pretend to be a saved glyph box');
assert.deepEqual(imageRegionBounds(region.focus, source, 10), [90, 90, 40, 70]);
region = reviewImageRegions(card, target, 'target');
assert.deepEqual(region.focus[0].points, [[150, 20], [210, 20], [210, 40], [150, 40]]);
assert.deepEqual(reviewImageRegions(card, source, 'target').line, [], 'Do not look for Quốc ngữ boxes on the Nôm page');
const glyphPage = { ...source, boxes: [
  { ...han, id: 'g1', transcription: '𤾓', points: [[100, 50], [120, 50], [120, 100], [100, 100]] },
  { ...han, id: 'g2', transcription: '𢆥', points: [[100, 100], [120, 100], [120, 150], [100, 150]] },
] };
const glyphCard = { ...card, row: { ...card.row, source_refs: [
  { box_id: 'g1', start: 0, end: 1 }, { box_id: 'g2', start: 0, end: 1 },
] } };
region = reviewImageRegions(glyphCard, glyphPage, 'source');
assert.equal(region.approximate, false);
assert.deepEqual(region.focus[0].points, glyphPage.boxes[1].points);
const stale = { ...card, row: { ...card.row, target: 'Trăm nămt' } };
region = reviewImageRegions(stale, target, 'target');
assert.equal(region.canLocateWord, false);
assert.deepEqual(region.focus, region.line, 'Changed text falls back to the linked line, not a guessed word');
const invalid = { ...card, row: { ...card.row, target_refs: [{ box_id: 'vi-box', start: 0, end: 99 }] } };
assert.deepEqual(reviewImageRegions(invalid, target, 'target').line[0].points, vi.points);
assert.equal(JSON.stringify({ source, target, card }), original, 'Image overlays must never mutate saved geometry');
assert.deepEqual(reviewImageRegions({ ...card, index: null }, target, 'target').focus[0].points, vi.points);
console.log('Quick review images: separate linked pages, Unicode offsets, exact/estimated boxes, stale refs and unchanged geometry OK.');

const loaded = { key: 'p46:p47:fp', source: { ...source, image_url: '/image46' }, target: { ...target, image_url: '/image47' }, errors: [] };
const effects = [], requested = [];
let hook = 0;
const react = { ...React, useState(initial) { return [hook++ === 0 ? loaded : initial, () => {}]; }, useEffect(fn) { effects.push(fn); } };
const file = new URL('../src/components/QuickReviewImages.tsx', import.meta.url);
const code = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const module = new vm.SourceTextModule(code);
await module.link(specifier => {
  const exports = specifier === 'react' ? react : specifier === 'react/jsx-runtime' ? runtime :
    specifier === './quickReviewRegions' ? { imageRegionBounds, reviewImageRegions } :
    specifier === '../api' ? { api: { page(id) { requested.push(id); return Promise.resolve(id === 'p46' ? loaded.source : loaded.target); } } } : null;
  assert.ok(exports, specifier);
  return new vm.SyntheticModule(Object.keys(exports), function () { for (const [name, value] of Object.entries(exports)) this.setExport(name, value); });
});
await module.evaluate();
const html = renderToStaticMarkup(React.createElement(module.namespace.default, { card: { ...card, id: 'card', fingerprint: 'fp' } }));
assert.ok(html.includes('Ảnh Hán Nôm trang 46') && html.includes('Ảnh Quốc ngữ trang 47'));
assert.ok(html.includes('href="/image46"') && html.includes('href="/image47"'));
assert.equal((html.match(/<clipPath/g) || []).length, 2, 'Both images must clip to their crop, including letterboxed columns');
assert.equal((html.match(/class="quick-image-focus estimated"/g) || []).length, 2);
const cleanups = effects.map(fn => fn());
await Promise.resolve();
assert.deepEqual(requested, ['p46', 'p47'], 'Fetch the explicit target page, not source page + 1 or source image reused');
cleanups.forEach(fn => fn?.());
console.log('Quick review image panels: separate page loading, page labels, overlays and crop clipping render OK.');
