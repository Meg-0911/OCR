// Pure React rendering smoke test: no browser or user data mutations.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import vm from 'node:vm';
import ts from 'typescript';
import React from 'react';
import * as runtime from 'react/jsx-runtime';
import { renderToStaticMarkup } from 'react-dom/server';

let states = [], index = 0;
const react = { ...React, useState(initial) { return [index < states.length ? states[index++] : initial, () => {}]; },
  useEffect() {}, useRef(value) { return { current: value }; } };
const file = new URL('../src/components/QuickReview.tsx', import.meta.url);
const source = ts.transpileModule(fs.readFileSync(file, 'utf8'), { compilerOptions: {
  target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.ESNext, jsx: ts.JsxEmit.ReactJSX,
} }).outputText;
const module = new vm.SourceTextModule(source);
await module.link(specifier => {
  const exports = specifier === 'react' ? react : specifier === 'react/jsx-runtime' ? runtime :
    specifier === '../api' ? { api: {} } : specifier === './QuickReviewImages' ? { default: () => null } : specifier === 'lucide-react' ?
    Object.fromEntries(['Check','X','SkipForward','RotateCcw','Search','ExternalLink','ScanLine','BookOpen','ArrowLeft'].map(k => [k, () => null])) : null;
  assert.ok(exports, `Unexpected import ${specifier}`);
  return new vm.SyntheticModule(Object.keys(exports), function () {
    for (const [name, value] of Object.entries(exports)) this.setExport(name, value);
  });
});
await module.evaluate();
const QuickReview = module.namespace.default;
const card = { id: 'card', row_id: 'r', fingerprint: 'hash', index: 1, page_number: 250,
  source: '𢆥', target: 'nămt', expected_source: '𢆥', expected_target: 'năm', query: 'năm',
  reason: 'Khác nguồn tham khảo', row: { source: '𤾓𢆥', target: 'Trăm nămt' },
  reference: { source: '𤾓𢆥', target: 'Trăm năm', position: 1, label: '1' } };
const status = { job: { status: 'completed' }, counts: { pending: 2, done: 1 }, card, dictionary_ready: true, is_kieu: true };
function render(s, detail = null) {
  states = [s, '', false, false, s.card?.source || '', s.card?.target || '', s.card?.query || '', null, detail, '', false, false, null]; index = 0;
  return renderToStaticMarkup(React.createElement(QuickReview, { bookId: 'book', onChanged() {}, onOpenAlignment() {} }));
}
let html = render(status);
assert.ok(html.includes('𢆥'));
assert.ok(html.includes('nămt'));
assert.equal((html.match(/Mẫu:/g) || []).length, 1, 'Only the differing side should show its reference');
assert.ok(!html.includes('Trăm nămt'), 'Full row context is collapsed by default');
assert.ok(html.includes('Đúng · đen') && html.includes('Thiếu từ điển') && html.includes('Để sau'));
assert.ok(html.includes('quick-back-button') && html.includes('Hoàn tác lần bấm vừa rồi'));
html = render({ ...status, card: { ...card, index: null, source: '𤾓𢆥', target: 'trăm năm nữa', expected_source: '𤾓𢆥', expected_target: 'trăm năm' } });
assert.ok(html.includes('CẢ DÒNG') && html.includes('trăm năm nữa') && html.includes('Chọn chữ để tra:'));
html = render({ ...status, card: { ...card, stale: true } });
assert.ok(html.includes('Dòng đã được sửa ở nơi khác'));
assert.ok((html.match(/disabled=""/g) || []).length >= 4);
assert.ok(render({ ...status, card: null }).includes('Đã hết thẻ'));
html = render(status, { character: '結', meanings: [], examples: [], variants: [
  { character: '结', kind: 'Giản thể', source: 'Nôm Na Việt', readings: ['kết'] },
], historical_forms: [{ id: 'seal1', script_type: 'seal', source: 'Nôm Na Việt', image_url: 'https://api.nomnaviet.com/api/dictionary/glyph/test.png' }] });
assert.ok(html.includes('Dị thể có thể chọn') && html.includes('结') && html.includes('Giản thể'));
assert.ok(html.includes('Ảnh các dạng chữ cổ') && html.includes('Triện thư'));
assert.ok(!render(status, { character: '𢆥', meanings: [], examples: [], variants: [], historical_forms: [] }).includes('Dị thể có thể chọn'));
console.log('Quick review: Unicode card rendering, differing-side references, full lines, stale guards and completion OK.');
