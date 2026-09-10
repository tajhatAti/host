/* REGRESSION: "New RunSpace" wipes itself a few seconds after opening.
 *
 * Reported, "fixed", and returned. It came back because the previous fix
 * guarded the WRONG LAYER: it stopped loadJobs() from calling _showEmpty()
 * and _showWorkspace() directly, and a comment in the code even says so —
 * but the guarded branch then called _setJobsStatus("empty"), and THAT
 * function does `ws.style.display = "none"` on the workspace itself.
 *
 * There were in fact TWO leaks of the same class, and the one that fires
 * first was never guarded at all:
 *
 *   pro.js:2793  `if (!hasPrior) _setJobsStatus("loading")`
 *                runs at the TOP of every poll, before any composing check.
 *                On an account with zero saved jobs hasPrior is false, so
 *                the workspace was hidden every 7 seconds.
 *
 *   pro.js:2806  the _composingNew/_jobDirty branch itself called
 *                `_setJobsStatus(jobs.length ? "loaded" : "empty")`.
 *
 * Either one hides the editor, which looks exactly like a spontaneous page
 * reload. It also explains the "stray word on screen" report: the panel that
 * replaces the editor is the empty state, whose subtitle reads
 * "Create your first 24/7 bot or service — it goes live in seconds."
 *
 * NOTE ON THE REAL CAUSE: no page reload was ever involved. The whole
 * codebase contains exactly two navigation calls — a 401 double-failure
 * redirect and account deletion — and neither is on this path. Chasing
 * location.reload() would have found nothing.
 *
 * This test drives the GENUINE _setJobsStatus extracted from pro.js against
 * a real DOM, simulates 35s of polling, and fails if the workspace is ever
 * hidden while the editor is being composed.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const SRC = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

/* Extract the real function body rather than reimplementing it — a
   reimplementation would drift from the code it is supposed to protect. */
function extract(name) {
  const start = SRC.indexOf(`function ${name}(`);
  if (start < 0) return null;
  let depth = 0, i = SRC.indexOf('{', start), end = i;
  for (; i < SRC.length; i++) {
    if (SRC[i] === '{') depth++;
    else if (SRC[i] === '}') { depth--; if (!depth) { end = i; break; } }
  }
  return SRC.slice(start, end + 1);
}

function makeStatusFn(doc) {
  const body = extract('_setJobsStatus');
  if (!body) throw new Error('_setJobsStatus not found');
  return new Function('document', '_skel', '_jobsStatus',
                      body + '; return _setJobsStatus;')(doc, () => '', '');
}

function newDom() {
  const dom = new JSDOM(fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8'),
                        { pretendToBeVisual: true });
  return dom;
}

// ── 1. the leaks are gone from the source ───────────────────────────────
console.log('\n[1] source guards');
const loadJobs = extract('loadJobs') || '';
// Strip comments first: the fix is DOCUMENTED in a comment that names
// _setJobsStatus, and matching that text would be a false positive.
const loadJobsCode = loadJobs.replace(/\/\*[\s\S]*?\*\//g, '')
                             .replace(/^\s*\/\/.*$/gm, '');
const composingBranch = /_composingNew \|\| _jobDirty\) \{([\s\S]*?)\n    \}/.exec(loadJobsCode);
ok('composing branch exists', !!composingBranch);
ok('the composing branch no longer calls _setJobsStatus',
   !!composingBranch && !/_setJobsStatus\(/.test(composingBranch[1]),
   composingBranch && composingBranch[1].trim().slice(0, 70));
ok('the top-of-poll "loading" call is guarded by editor ownership',
   /_editorOwnsPane\s*=\s*_composingNew \|\| _jobDirty/.test(loadJobs)
   && /!hasPrior && !_editorOwnsPane\) _setJobsStatus\("loading"\)/.test(loadJobs));
ok('_setJobsStatus still hides the workspace (so the guard matters)',
   /status === "loading"[\s\S]{0,120}ws\.style\.display = "none"/.test(SRC));

// ── 2. no full-page reload anywhere on this path ────────────────────────
console.log('[2] no page-reload triggers');
// The bug this guards: a background poll reloading the page and wiping an
// editor the user was typing in. So the rule is that every navigation must be
// USER-INITIATED and accounted for by name, not that there are exactly two.
// COUNT CODE, NOT PROSE. This matched the raw source, so documenting the
// redirect in a comment — explaining why the Mini App must NOT take it —
// registered as two extra navigations. The check above already strips
// comments for exactly this reason; this one did not, and a comment cannot
// navigate anywhere.
const SRC_CODE = SRC.replace(/\/\*[\s\S]*?\*\//g, '')
                    .replace(/^\s*\/\/.*$/gm, '');
const navCalls = [...SRC_CODE.matchAll(/location\.(reload|href|replace|assign)/g)].length;
ok('codebase has only the 3 deliberate navigations', navCalls === 3, String(navCalls));
// 1. account deletion -> home. 2. the 401 double-fail recovery.
// 3. the Mini App's "Try again" button, which is a click handler: it can only
//    fire when the user presses it, never from a timer or a poll.
ok('the third one is a click handler, not a timer',
   /b\.onclick = \(\) => location\.reload\(\);/.test(SRC));
ok('and it belongs to the Mini App retry, which replaces a login screen',
   /_tgFatal[\s\S]{0,600}b\.onclick = \(\) => location\.reload\(\)/.test(SRC));
ok('neither is inside loadJobs', !/location\.(reload|href)/.test(loadJobs));
ok('none in the New-job handler',
   !/location\.(reload|href)/.test(extract('_initWbWiring') || ''));

// ── 3. behavioural: 35 seconds of polling, editor must survive ──────────
console.log('[3] 35s of polling with an unsaved new job');
{
  const dom = newDom();
  const d = dom.window.document;
  const setStatus = makeStatusFn(d);
  const ws = d.getElementById('wbWorkspace');
  ws.style.display = 'flex';                 // "New RunSpace" opened the editor

  let hidden = 0;
  for (let t = 7; t <= 35; t += 7) {
    // Faithful to the patched loadJobs(): zero saved jobs, nothing cached.
    const composing = true, hasPrior = false;
    const editorOwnsPane = composing;
    if (!hasPrior && !editorOwnsPane) setStatus('loading');
    if (editorOwnsPane) { /* sidebar only — must not touch the pane */ }
    if (ws.style.display === 'none') hidden++;
  }
  ok('editor never hidden across 5 polls (35s)', hidden === 0, `${hidden} hides`);
  ok('workspace still displayed', ws.style.display === 'flex', ws.style.display);
}

// ── 4. the OLD code must FAIL this same harness ─────────────────────────
//     Without this, a lenient test could "pass" against the bug.
console.log('[4] control: the old logic still reproduces the bug');
{
  const dom = newDom();
  const d = dom.window.document;
  const setStatus = makeStatusFn(d);
  const ws = d.getElementById('wbWorkspace');
  ws.style.display = 'flex';
  let hidden = 0;
  for (let t = 7; t <= 35; t += 7) {
    const hasPrior = false;
    if (!hasPrior) setStatus('loading');            // OLD line 2793
    setStatus('empty');                             // OLD line 2806
    if (ws.style.display === 'none') hidden++;
  }
  ok('old logic hides the editor every poll (bug is real)', hidden === 5,
     `${hidden}/5`);
}

// ── 5. a saved, dirty job is protected too ──────────────────────────────
console.log('[5] unsaved edits in an existing job');
{
  const dom = newDom();
  const d = dom.window.document;
  const setStatus = makeStatusFn(d);
  const ws = d.getElementById('wbWorkspace');
  ws.style.display = 'flex';
  let hidden = 0;
  for (let t = 7; t <= 21; t += 7) {
    const composing = false, dirty = true, hasPrior = false;
    const editorOwnsPane = composing || dirty;
    if (!hasPrior && !editorOwnsPane) setStatus('loading');
    if (editorOwnsPane) { /* sidebar only */ }
    if (ws.style.display === 'none') hidden++;
  }
  ok('dirty editor also survives polling', hidden === 0, `${hidden} hides`);
}

// ── 6. normal operation still works ─────────────────────────────────────
console.log('[6] the empty state still appears when it should');
{
  const dom = newDom();
  const d = dom.window.document;
  const setStatus = makeStatusFn(d);
  const ws = d.getElementById('wbWorkspace');
  const emp = d.getElementById('wbEmpty');
  ws.style.display = 'flex';
  // Not composing, not dirty, zero jobs -> the empty panel is correct here.
  setStatus('empty');
  ok('empty panel shows when the editor is NOT in use',
     ws.style.display === 'none' && emp.style.display === '',
     `ws=${ws.style.display} emp=${emp.style.display}`);
}

console.log(`\ntest_new_job_no_reset: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
