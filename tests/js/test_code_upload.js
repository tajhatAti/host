/* Code Studio file upload — single file.
 *
 * BRIEF
 *   drag-and-drop zone + "Upload file" button, both through one handler;
 *   language auto-detected from the extension; 9-10MB cap; text/code only,
 *   rejected on BOTH extension and actual content because an extension can
 *   be spoofed; and once loaded the content behaves exactly like typed code.
 *
 * WHY THE CONTENT CHECK IS THE ONE THAT MATTERS
 *   This code can later be deployed as a RunSpace job, so "it ends with .py"
 *   is not evidence of anything -- renaming payload.exe to main.py takes a
 *   second. Every rejection case below is therefore fed REAL bytes: an ELF
 *   header, a PE header, a PNG, a zip, a UTF-16 BOM, embedded NULs. If the
 *   sniffer is ever weakened these fail.
 *
 * The upload module is loaded out of pro.js and executed in isolation: the
 * whole file cannot run under jsdom (it boots the app, opens sockets), so
 * the self-contained upload section is extracted and evaluated on its own.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const R = path.resolve(__dirname, '../../');
const html = fs.readFileSync(path.join(R, 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(R, 'static', 'app.css'), 'utf8');
const JS = fs.readFileSync(path.join(R, 'static', 'pro.js'), 'utf8');

let pass = 0, fail = 0;
function ok(name, cond, extra) {
  if (cond) pass++;
  else { fail++; console.log(`  FAIL ${name}${extra ? ' -> ' + extra : ''}`); }
}

/* ── load the upload module in isolation ───────────────────────────────── */
/* Slice from the start of the block COMMENT, not from the marker word
   inside it -- starting mid-comment leaves an unterminated comment and the
   Function constructor throws on the prose. */
const marker = 'CODE STUDIO — FILE UPLOAD';
const mi = JS.indexOf(marker);
const from = JS.lastIndexOf('/*', mi);
const src = JS.slice(from);

const dom = new JSDOM(html, { pretendToBeVisual: true, url: 'https://example.test/' });
const win = dom.window;
const d = win.document;
d.querySelectorAll('link[rel=stylesheet]').forEach(l => l.remove());
const st = d.createElement('style'); st.textContent = CSS; d.head.appendChild(st);

// Stand-ins for the app globals the module touches.
const toasts = [];
const sandbox = {
  window: win, document: d,
  toast: (m, k) => toasts.push({ m: String(m), k }),
  editingSnippetId: 'PRE-EXISTING',
  cmEditor: null,
  updateCodeMirrorMode: () => { sandbox._modeCalls = (sandbox._modeCalls || 0) + 1; },
  updateEditorMeta: () => {},
  runLivePreview: () => { sandbox._previewCalls = (sandbox._previewCalls || 0) + 1; },
  TextDecoder: win.TextDecoder || global.TextDecoder,
  Uint8Array, setTimeout, console,
};
const fn = new Function(...Object.keys(sandbox), src + `
  return { _csHandleUpload, _csSniff, _csExt, _csLoadTextIntoEditor,
           _csRefreshEmptyState, _initCsUpload, CS_EXT_LANG,
           CS_BLOCKED_EXT, CS_UPLOAD_MAX_BYTES };`);
const M = fn(...Object.values(sandbox));
ok('the upload module exists in pro.js', mi > 0);
ok('it evaluates standalone', !!M && typeof M._csHandleUpload === 'function');

/* A minimal File: only .name/.size/.arrayBuffer() are used. */
function fileOf(name, bytes) {
  const u8 = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  return { name, size: u8.length, arrayBuffer: async () => u8.buffer };
}
const textBytes = (s) => new Uint8Array(Buffer.from(s, 'utf8'));
const lastToast = () => toasts.length ? toasts[toasts.length - 1] : null;
const editorValue = () => d.getElementById('snippetContent').value;
const editorLang  = () => d.getElementById('snippetLanguage').value;

async function main() {
/* ── 1. UI ─────────────────────────────────────────────────────────────── */
console.log('[1] both entry points exist and share one input');
ok('a file input exists', !!d.getElementById('csFileInput'));
ok('it is hidden from the layout', d.getElementById('csFileInput').hasAttribute('hidden'));
ok('the menu has an Upload row', !!d.getElementById('btnUploadFile'));
ok('the empty state has an Upload button', !!d.getElementById('btnUploadFileEmpty'));
ok('there is a drop zone', !!d.getElementById('csDropZone'));
ok('both buttons drive the SAME input (one code path)',
   /menuBtn[\s\S]{0,200}input\.click\(\)|const pick[\s\S]{0,120}input\.click\(\)/.test(src));
{
  const zone = win.getComputedStyle(d.getElementById('csDropZone'));
  ok('the drop zone is invisible until a drag starts', zone.display === 'none', zone.display);
  ok('it covers the editor when shown', zone.position === 'absolute', zone.position);
}

/* ── 2. single file loads, language detected ───────────────────────────── */
console.log('\n[2] a code file opens with the right language');
const LANG_CASES = [
  ['main.py', 'python', 'print("hi")\n'],
  ['app.js', 'javascript', 'console.log(1)\n'],
  ['index.html', 'html', '<h1>hi</h1>\n'],
  ['style.css', 'css', 'body{color:red}\n'],
  ['data.json', 'json', '{"a":1}\n'],
  ['notes.md', 'markdown', '# hi\n'],
  ['run.sh', 'bash', 'echo hi\n'],
  ['q.sql', 'sql', 'select 1;\n'],
  ['Main.java', 'java', 'class Main{}\n'],
  ['a.cpp', 'cpp', 'int main(){}\n'],
  ['m.go', 'go', 'package main\n'],
  ['i.php', 'php', '<?php echo 1;\n'],
  ['s.rb', 'ruby', 'puts 1\n'],
  ['t.ts', 'typescript', 'const a: number = 1\n'],
  ['readme.txt', 'text', 'plain\n'],
];
for (const [name, lang, body] of LANG_CASES) {
  await (M._csHandleUpload(fileOf(name, textBytes(body))));
  ok(`${name} -> ${lang}`, editorLang() === lang, editorLang());
  ok(`${name} content loaded verbatim`, editorValue() === body,
     JSON.stringify(editorValue()).slice(0, 40));
}
// An unknown extension must still open, as plain text.
await (M._csHandleUpload(fileOf('weird.xyzzy', textBytes('hello\n'))));
ok('an unknown extension still opens, as text', editorLang() === 'text' && editorValue() === 'hello\n');

console.log('\n[2b] the title comes from the file name');
await (M._csHandleUpload(fileOf('my_bot.py', textBytes('x=1\n'))));
ok('title is the name without its extension',
   d.getElementById('snippetTitle').value === 'my_bot',
   d.getElementById('snippetTitle').value);

/* ── 3. size limit ─────────────────────────────────────────────────────── */
console.log('\n[3] the size cap');
ok('the cap is in the 9-10MB band the brief asks for',
   M.CS_UPLOAD_MAX_BYTES >= 9 * 1024 * 1024 && M.CS_UPLOAD_MAX_BYTES <= 10 * 1024 * 1024,
   String(M.CS_UPLOAD_MAX_BYTES));
{
  const before = editorValue();
  const huge = { name: 'big.py', size: M.CS_UPLOAD_MAX_BYTES + 1,
                 arrayBuffer: async () => new Uint8Array(0).buffer };
  await (M._csHandleUpload(huge));
  ok('an oversized file is refused', editorValue() === before);
  ok('and the message names the limit', /limit is/i.test((lastToast() || {}).m || ''),
     (lastToast() || {}).m);
  // Exactly at the limit must be allowed: an off-by-one here is a silent
  // "nothing happened" for the user.
  const atCap = new Uint8Array(1024); atCap.fill(0x41);
  await (M._csHandleUpload(fileOf('ok.py', atCap)));
  ok('a file under the cap is accepted', editorValue().length === 1024);
}

/* ── 4. rejection by extension ─────────────────────────────────────────── */
console.log('\n[4] binaries are refused by extension');
for (const bad of ['exe', 'dll', 'so', 'jar', 'class', 'pyc', 'png', 'jpg',
                   'pdf', 'mp4', 'sqlite', 'woff2', 'wasm', 'apk']) {
  const before = editorValue();
  await (M._csHandleUpload(fileOf('payload.' + bad, textBytes('anything'))));
  ok(`.${bad} refused`, editorValue() === before, 'editor changed!');
}

/* ── 5. rejection by CONTENT — the check that actually matters ─────────── */
console.log('\n[5] spoofed extensions are caught by the bytes');
const SPOOFS = [
  ['ELF binary named .py',   'main.py',  [0x7f, 0x45, 0x4c, 0x46, 0x02, 0x01, 0x01]],
  ['Windows .exe named .py', 'main.py',  [0x4d, 0x5a, 0x90, 0x00, 0x03]],
  ['Java class named .txt',  'a.txt',    [0xca, 0xfe, 0xba, 0xbe, 0x00]],
  ['PNG named .js',          'a.js',     [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a]],
  ['JPEG named .css',        'a.css',    [0xff, 0xd8, 0xff, 0xe0]],
  ['GIF named .md',          'a.md',     [0x47, 0x49, 0x46, 0x38, 0x39]],
  ['PDF named .txt',         'a.txt',    [0x25, 0x50, 0x44, 0x46, 0x2d]],
  ['gzip named .sh',         'a.sh',     [0x1f, 0x8b, 0x08, 0x00]],
  ['zip bytes named .py',    'a.py',     [0x50, 0x4b, 0x03, 0x04, 0x14]],
  ['RAR named .json',        'a.json',   [0x52, 0x61, 0x72, 0x21, 0x1a]],
  ['7z named .py',           'a.py',     [0x37, 0x7a, 0xbc, 0xaf, 0x27]],
  ['wasm named .js',         'a.js',     [0x00, 0x61, 0x73, 0x6d, 0x01]],
  ['Mach-O named .py',       'a.py',     [0xcf, 0xfa, 0xed, 0xfe, 0x0c]],
];
for (const [label, name, bytes] of SPOOFS) {
  const before = editorValue();
  await (M._csHandleUpload(fileOf(name, new Uint8Array(bytes))));
  ok(`${label} refused`, editorValue() === before, 'IT LOADED — sniffer blind');
  ok(`  and the reason is specific`, /looks like|binary|not text/i.test((lastToast() || {}).m || ''),
     (lastToast() || {}).m);
}
{
  // No magic number, but NUL bytes in the middle: still binary.
  const sneaky = new Uint8Array([...Buffer.from('#!/usr/bin/env python\n'), 0x00, 0x01, 0x02, 0x00]);
  const before = editorValue();
  await (M._csHandleUpload(fileOf('sneaky.py', sneaky)));
  ok('embedded NUL bytes refused', editorValue() === before);

  // Mostly control characters, no NUL.
  const ctrl = new Uint8Array(400).fill(0x01);
  await (M._csHandleUpload(fileOf('ctrl.py', ctrl)));
  ok('a control-character blob refused', editorValue() === before);

  // UTF-16 is text, but would decode to mojibake: refuse and say so.
  const u16 = new Uint8Array([0xff, 0xfe, 0x70, 0x00, 0x72, 0x00]);
  await (M._csHandleUpload(fileOf('u16.py', u16)));
  ok('UTF-16 refused with a useful message', /UTF-16/i.test((lastToast() || {}).m || ''),
     (lastToast() || {}).m);

  // Invalid UTF-8 that is not caught by the sniffer must not become U+FFFD soup.
  const badUtf8 = new Uint8Array([0x70, 0x72, 0xC3, 0x28, 0x69]);
  await (M._csHandleUpload(fileOf('bad.py', badUtf8)));
  ok('invalid UTF-8 refused', /UTF-8/i.test((lastToast() || {}).m || ''), (lastToast() || {}).m);
}

console.log('\n[5b] legitimate text with unusual bytes still opens');
{
  await (M._csHandleUpload(fileOf('emoji.py', textBytes('# ✅ héllo → 世界\nx = 1\n'))));
  ok('UTF-8 accents, arrows, CJK and emoji are fine', /世界/.test(editorValue()), editorValue().slice(0, 20));
  await (M._csHandleUpload(fileOf('tabs.py', textBytes('def f():\n\treturn 1\n\n'))));
  ok('tabs and blank lines are fine', /\t/.test(editorValue()));
  await (M._csHandleUpload(fileOf('crlf.py', textBytes('a = 1\r\nb = 2\r\n'))));
  /* A CRLF file must LOAD; it must not be rejected as binary. It is wrong to
     assert the CR survives: the HTML spec has <textarea>.value perform
     newline normalisation, so a browser and jsdom both hand back LF only.
     Checking for \r\n here was testing the DOM, not the uploader. */
  ok('a CRLF file loads (CR normalised by the textarea, per spec)',
     editorValue() === 'a = 1\nb = 2\n', JSON.stringify(editorValue()));
  await (M._csHandleUpload(fileOf('empty.py', new Uint8Array(0))));
  ok('an empty file is allowed', editorValue() === '');
}

/* ── 6. zip is deferred, and says so ───────────────────────────────────── */
console.log('\n[6] .zip is refused with an honest reason');
{
  const before = editorValue();
  await (M._csHandleUpload(fileOf('project.zip', new Uint8Array([0x50, 0x4b, 0x03, 0x04]))));
  ok('a zip does not load', editorValue() === before);
  ok('the message explains it needs the file tree',
     /file-tree|file tree/i.test((lastToast() || {}).m || ''), (lastToast() || {}).m);
}

/* ── 7. no separate path for uploaded content ──────────────────────────── */
console.log('\n[7] uploaded content is an ordinary draft');
{
  sandbox.editingSnippetId = 'SOME-OLD-ID';
  await (M._csHandleUpload(fileOf('fresh.py', textBytes('print(1)\n'))));
  ok('the same textarea the app saves from is populated',
     d.getElementById('snippetContent').value === 'print(1)\n');
  ok('syntax highlighting is refreshed', (sandbox._modeCalls || 0) > 0);
  ok('the live preview is refreshed', (sandbox._previewCalls || 0) > 0);
  ok('no "uploaded" flag is introduced anywhere',
     !/isUploaded|uploadedContent|fromUpload/.test(src));
  ok('it becomes a NEW draft rather than overwriting the open snippet',
     /editingSnippetId\s*=\s*null/.test(src));
}

/* ── 8. drag and drop wiring ───────────────────────────────────────────── */
console.log('\n[8] drag and drop');
ok('dragenter/dragover/drop are handled', /dragenter/.test(src) && /dragover/.test(src) && /"drop"/.test(src));
ok('the browser default (navigate away) is suppressed',
   /\["dragover", "drop"\][\s\S]{0,320}preventDefault/.test(src));
ok('only file drags are intercepted', /types \|\| \[\]\)\]\.includes\("Files"\)/.test(src));
ok('enter/leave is depth-counted so it cannot flicker',
   /depth\+\+/.test(src) && /depth--/.test(src));
ok('a multi-file drop is refused rather than silently taking the first',
   /files\.length > 1/.test(src));
ok('dropping runs the same handler as the button',
   /drop[\s\S]{0,400}_csHandleUpload\(files\[0\]\)/.test(src));

/* ── 9. re-selecting the same file works ───────────────────────────────── */
console.log('\n[9] the same file can be chosen twice');
ok('the input is cleared after each change',
   /input\.value = "";/.test(src),
   'without this, picking the same file again fires no event');



console.log(`\ntest_code_upload: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
}

main().catch(e => { console.log('  FAIL suite crashed -> ' + e.message); process.exit(1); });
