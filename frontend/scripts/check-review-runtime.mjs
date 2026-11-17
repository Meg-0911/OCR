import assert from 'node:assert/strict';
import vm from 'node:vm';
import React from 'react';
import * as jsxRuntime from 'react/jsx-dev-runtime';
import { renderToStaticMarkup } from 'react-dom/server';
import { reviewColorsForText } from '../src/reviewColors.ts';
import { cleanAlignmentText } from '../src/alignmentText.ts';

// Use Vite's dev output: production builds hoist imports differently and can
// conceal a React import placed after a top-level memo() call.
const origin = process.argv[2] || 'http://127.0.0.1:5173';
let createWholePage;
const runtime = { ...jsxRuntime, jsxDEV(type, props, ...args) {
  if (type === 'button' && typeof props.children === 'string' && props.children.startsWith('Tạo cặp nháp'))
    createWholePage = props.onClick;
  return jsxRuntime.jsxDEV(type, props, ...args);
} };
async function loadComponent(name) {
const url = `${origin}/src/components/${name}.tsx`;
const response = await fetch(url);
assert.equal(response.status, 200, `Cannot load the running Vite dev server at ${url}`);
const source = await response.text();
const module = new vm.SourceTextModule(source, {
  identifier: url,
  initializeImportMeta(meta) { meta.url = url; },
});

await module.link((specifier) => {
  let exports;
  if (specifier.startsWith('/@vite/client')) exports = { createHotContext: () => undefined };
  else if (specifier.startsWith('/@react-refresh')) exports = {
    register() {},
    createSignatureFunctionForTransform: () => (component) => component,
  };
  else if (specifier.includes('react_jsx-dev-runtime')) exports = { default: runtime };
  else if (specifier.includes('/react.js')) exports = { default: React };
  else if (specifier.startsWith('/src/reviewColors.ts')) exports = { reviewColorsForText };
  else if (specifier.startsWith('/src/alignmentText.ts')) exports = { cleanAlignmentText };
  else if (specifier.includes('lucide-react')) exports = { Plus: () => null };
  else if (/\/src\/components\/(AlignmentBoxEditor|ManuscriptViewer)\.tsx/u.test(specifier)) exports = { default: () => null };
  else throw new Error(`Unexpected dev import: ${specifier}`);
  return new vm.SyntheticModule(Object.keys(exports), function () {
    for (const [name, value] of Object.entries(exports)) this.setExport(name, value);
  });
});
await module.evaluate();
return module.namespace.default;
}
const ReviewText = await loadComponent('ReviewText');
const markup = renderToStaticMarkup(React.createElement(ReviewText, {
  text: '𡗶地玄', colors: ['match', 'match', 'mismatch'],
}));
assert.equal(markup, '<span class="review-match">𡗶地</span><span class="review-mismatch">玄</span>');
console.log('Vite dev ReviewText initializes and renders Unicode review colors: OK');

const AlignmentSources = await loadComponent('AlignmentSources');
const source = ' ١，𡗶 地。\u200b\n\n';
const target = ' 660- THIÊN,   ĐỊA!\u200b';
const box = { id: 'source', transcription: source, points: [[0,0],[100,0],[100,30],[0,30]], review_kind: 'mismatch' };
const page = { id: 'page', number: 110, source_text: source, target_text: target,
  boxes: [box], vi_boxes: [{ ...box, id: 'target', transcription: target }], export_boxes: [],
  linked_page_ids: [], ocr_languages: ['han','vi'], reading_direction: 2, image_url: '/image' };
let created;
const panels = renderToStaticMarkup(React.createElement(AlignmentSources, {
  page, pages: [page], reference: null, busy: false, alignments: [], onBoxes() {},
  onCreate: (...values) => { created = values; },
}));
const textUnderImage = (label) => {
  const match = panels.match(new RegExp(`aria-label="${label}"[^>]*>([\\s\\S]*?)</div>`, 'u'));
  assert.ok(match, `Missing cleaned text panel: ${label}`);
  return match[1].replace(/<[^>]+>/gu, '');
};
assert.equal(textUnderImage('Văn bản Hán Nôm đã làm sạch'), '𡗶地');
assert.equal(textUnderImage('Văn bản Quốc ngữ đã làm sạch'), 'thiên địa');
assert.equal(typeof createWholePage, 'function');
createWholePage();
assert.deepEqual(created, ['𡗶地', 'thiên địa']);
console.log('Text below both alignment images is cleaned immediately; creating a pair uses the same clean text: OK');
