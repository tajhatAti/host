/* Bot Store UI.
 *
 * Two layers, because the two failure modes are different:
 *
 *  1. STATIC — the shell has a real Store tab, a real /store URL, the three
 *     modals, and the deploy hand-off goes through the ONE Add Bot wizard
 *     instead of inventing a second deploy path.
 *
 *  2. DOM — the renderer is executed for real against jsdom with stubbed
 *     data, so "the card shows the title, the summary, the size and the
 *     rating" is observed rather than assumed, and a hostile listing title
 *     is proven to be inert text rather than markup.
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const HTML = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');
const PY = fs.readFileSync(path.join(ROOT, 'routes/store.py'), 'utf8');
const SVC = fs.readFileSync(path.join(ROOT, 'services/store.py'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

console.log('[1] the store is a real destination');
ok('desktop nav has a Store tab', /class="dash-tab" data-tab="store"/.test(HTML));
ok('store section exists', /id="tab-store"/.test(HTML));
ok('store is a real URL', /"\/store":\s*"store"/.test(JS));
ok('server serves /store as the SPA shell', /"dashboard", "code", "bots", "activity", "store"/.test(
  fs.readFileSync(path.join(ROOT, 'app.py'), 'utf8')));
ok('opening the tab loads the shelf', /tabId === "store" && typeof loadStore === "function"/.test(JS));
ok('bottom nav exposes all four real destinations',
   ((HTML.match(/<nav class="bottom-nav bot-bottom-nav"[\s\S]*?<\/nav>/) || [''])[0].match(/data-tab=/g) || []).length === 4);
ok('mobile reaches the store from the one Bots menu', /id="btnStoreInMenu"/.test(HTML) &&
   /btnStoreInMenu"\);[\s\S]{0,120}switchTab\("store"\)/.test(JS));

console.log('[2] the shelf is browsable');
ok('search box exists', /id="storeSearch"/.test(HTML));
ok('search is debounced, not per keystroke', /_storeSearchTimer = setTimeout/.test(JS));
ok('sort chips exist', /id="storeSorts"/.test(HTML) && /data-sort="rating"/.test(HTML));
ok('category rail is rendered from the API', /function _storeRenderCategories/.test(JS) &&
   /_storeFacets.categories/.test(JS));
ok('an empty search says so instead of going blank', /id="storeEmpty"/.test(HTML) &&
   /empty.classList.toggle\("hidden", _storeItems.length > 0\)/.test(JS));
ok('facets line states the product rule', /every listing is one Python file/.test(JS));

console.log('[3] a listing is the file itself');
ok('detail modal shows the code', /id="storeDetailCode"/.test(HTML) && /id="storeCodeLabel"/.test(HTML));
ok('signed-in readers get the whole file', /item.code_full/.test(JS) && /"code": code/.test(SVC));
ok('anonymous readers get a bounded preview', /code_preview/.test(JS) && /PREVIEW_LINES = 40/.test(SVC));
ok('code can be copied in one tap', /storeCopyCode/.test(HTML) && /navigator.clipboard.writeText/.test(JS));
ok('features are listed, not implied', /id="storeDetailFeatures"/.test(HTML));
ok('ratings and reviews are visible', /id="storeRating"/.test(HTML) && /id="storeReviews"/.test(HTML));

console.log('[4] deploy goes through the one wizard');
ok('install is recorded server-side', /\/install`, "POST"/.test(JS) &&
   /store_installs/.test(SVC));
ok('the listing file fills the single job editor', /_storeDeployCurrent[\s\S]*_jobCmSetValue\(item.code\)/.test(JS));
ok('the shared deploy path is reused, not reimplemented',
   /_storeDeployCurrent[\s\S]*await _analyzeRunSpaceBot\(\)/.test(JS));
ok('the wizard still gates on a verified token', /openAddBot\(\)/.test(JS) &&
   /_setBotWizardStage\("code"\)/.test(JS));
ok('double deploy is guarded', /_storeDeploying/.test(JS));
ok('unsaved code is never silently replaced', /Replace the current code with this store bot/.test(JS));

console.log('[5] publishing and library');
ok('publish form exists', /id="storePublishModal"/.test(HTML) && /id="storePubCode"/.test(HTML));
ok('the rules are stated on the form', /must compile, read <code>BOT_TOKEN<\/code>/.test(HTML));
ok('submission posts to the store API', /api\("\/api\/store\/items", "POST"/.test(JS));
ok('server rejects a bad file before spending the budget',
   /validate_submission\(body.model_dump\(\)\)[\s\S]{0,240}rate_limit_user/.test(PY));
ok('library shows saved, deployed and published', /id="storeLibraryModal"/.test(HTML) &&
   /"Deployed"[\s\S]*"Published by you"/.test(JS));
ok('moderation stays owner-only and stealthy', /require_admin\(authorization\)/.test(PY));

console.log('[6] visual rules');
ok('cards collapse to one column on a phone', /\.store-grid \{ grid-template-columns: 1fr; \}/.test(CSS));
ok('the code well uses the console surface', /\.store-code \{[\s\S]*background: var\(--bg-deep\)/.test(CSS));
/* Judge the store's OWN rule bodies. The old version looked 400 characters
   past any occurrence of "store", which reached into unrelated rules the
   moment another section was appended to the sheet. */
const storeRules = (CSS.replace(/\/\*[\s\S]*?\*\//g, '').match(/\.store-[^{}]*\{[^}]*\}/g) || []);
ok('every store rule is parsed for the check', storeRules.length > 20, String(storeRules.length));
ok('the store adds no colour of its own',
   !storeRules.some(r => /#[0-9a-fA-F]{3,8}\b/.test(r)),
   (storeRules.find(r => /#[0-9a-fA-F]{3,8}\b/.test(r)) || '').slice(0, 80));
ok('no frosted glass in the store', !/\.store-[^{]*\{[^}]*backdrop-filter/.test(CSS));

console.log('[7] the renderer, executed');
// Slice the store module (state + renderers) out of pro.js and run it against
// a real DOM. Everything it calls out to is stubbed, so this exercises the
// actual shipping render code rather than a copy of it.
const start = JS.indexOf('let _storeItems = [];');
const end = JS.indexOf('/* ---------------- publish a listing ---------------- */');
ok('store module is locatable in pro.js', start > 0 && end > start);
const moduleSource = JS.slice(start, end) + `
;return {
  setItems(v) { _storeItems = v; },
  setFacets(v) { _storeFacets = v; },
  setQuery(v) { _storeQuery = v; },
  setFav(v) { _storeFavs = v; },
  setTaken(v) { _storeTaken = v; },
  render() { renderStore(); },
  card(item) { return _storeCard(item); },
  detail(item) { _storeRenderDetail(item); },
};`;

const dom = new JSDOM(`<!doctype html><body>
  <div id="storeCategories"></div><div id="storeFacets"></div>
  <div id="storeGrid"></div><div id="storeEmpty" class="hidden"></div>
  <h3 id="storeDetailTitle"></h3><p id="storeDetailSummary"></p>
  <div id="storeDetailMeta"></div><div id="storeDetailFeatures"></div>
  <pre id="storeDetailCode"></pre><span id="storeCodeLabel"></span>
  <button id="storeFavBtn"></button><button id="storeDeployBtn"></button>
  <div id="storeRating"></div><div id="storeReviews"></div>
</body>`, { pretendToBeVisual: true });

const calls = [];
const factory = new Function('document', 'window', 'api', 'toast', 'openModal', 'closeModal',
                             'confirm', 'navigator', 'setTimeout', 'clearTimeout', 'prompt',
                             moduleSource);
const store = factory(dom.window.document, dom.window,
                      (p, m, b) => { calls.push([p, m]); return Promise.resolve({}); },
                      () => {}, () => {}, () => {}, () => true,
                      { clipboard: { writeText: async () => {} } },
                      dom.window.setTimeout, dom.window.clearTimeout, () => '');

const ITEMS = [
  { slug: 'complete-commerce', title: 'Complete Telegram store', summary: 'Catalog, cart, checkout.',
    category: 'Commerce', difficulty: 'Advanced', language: 'python', framework: 'python-telegram-bot',
    code_lines: 56, install_count: 12, rating: 4.5, rating_count: 2, featured: true, source: 'built-in',
    author: 'CodeNest', version: '1.0.0' },
  { slug: 'order-tracker', title: 'Order tracker', summary: 'Tracks orders and notifies buyers.',
    category: 'Utilities', difficulty: 'Beginner', language: 'python', framework: 'pyTelegramBotAPI',
    code_lines: 84, install_count: 3, rating: 0, rating_count: 0, featured: false, source: 'community',
    author: 'rahim', version: '1.2.0' },
];

store.setFacets({ listings: 8, community: 1, installs: 15,
                  categories: [{ name: 'Commerce', count: 1 }, { name: 'Utilities', count: 1 }],
                  allowed: ['Utilities'] });
store.setItems(ITEMS);
store.setFav(new Set(['order-tracker']));
store.setTaken(new Set(['complete-commerce']));
store.render();

const d = dom.window.document;
const cards = d.querySelectorAll('#storeGrid .store-card');
ok('one card per listing', cards.length === 2, `got ${cards.length}`);
ok('card shows the title', cards[0].textContent.includes('Complete Telegram store'));
ok('card shows the summary', cards[0].textContent.includes('Catalog, cart, checkout.'));
ok('card shows file size and framework', /56 lines · python-telegram-bot/.test(cards[0].textContent));
ok('card shows rating with its count', /★ 4.5 \(2\)/.test(cards[0].textContent));
ok('card marks a community author', cards[1].textContent.includes('by rahim'));
ok('card marks what you already deployed', cards[0].textContent.includes('Installed'));
ok('unrated listing shows installs instead of a fake score',
   !/★ 0/.test(cards[1].textContent) && cards[1].textContent.includes('3 installs'));
ok('cards are buttons, so they are keyboard reachable', cards[0].tagName === 'BUTTON' &&
   cards[0].getAttribute('type') === 'button');
ok('category rail renders counts', d.getElementById('storeCategories').textContent.includes('Commerce') &&
   d.getElementById('storeCategories').querySelectorAll('.store-cat').length === 3);
ok('facets line is filled in', /8 complete bots · 1 from the community · 15 installs/.test(
   d.getElementById('storeFacets').textContent));

store.setItems([]);
store.render();
ok('empty shelf un-hides the empty state',
   !d.getElementById('storeEmpty').classList.contains('hidden') &&
   d.getElementById('storeGrid').children.length === 0);
store.setItems(ITEMS);
store.render();
ok('a non-empty shelf hides it again', d.getElementById('storeEmpty').classList.contains('hidden'));

console.log('[8] hostile listing data stays text');
const evil = Object.assign({}, ITEMS[1], {
  title: '<img src=x onerror="alert(1)">',
  summary: '"><script>steal()</script>',
});
const evilCard = store.card(evil);
ok('a markup title is rendered as text', !evilCard.querySelector('img') && !evilCard.querySelector('script'));
ok('the raw markup is visible, not executed', evilCard.textContent.includes('<img src=x onerror="alert(1)">'));

console.log('[9] the detail view, executed');
store.setFav(new Set(['complete-commerce']));
const FULL = {
  slug: 'complete-commerce', title: 'Complete Telegram store', summary: 'Catalog, cart, checkout.',
  category: 'Commerce', difficulty: 'Advanced', framework: 'python-telegram-bot', version: '1.0.0',
  code_lines: 56, install_count: 12, rating: 4.5, rating_count: 2, author: 'CodeNest',
  features: ['Cart and checkout', 'Order history'], code_full: true, code: 'import os\nprint("hi")\n',
  reviews: [{ rating: 5, comment: 'Works.', author: 'rahim' }],
};
store.detail(FULL);
ok('detail shows the title and summary', d.getElementById('storeDetailTitle').textContent === 'Complete Telegram store' &&
   d.getElementById('storeDetailSummary').textContent === 'Catalog, cart, checkout.');
ok('detail prints the full source', d.getElementById('storeDetailCode').textContent.includes('import os'));
ok('detail labels the file honestly', /One complete Python file · 56 lines/.test(
   d.getElementById('storeCodeLabel').textContent));
ok('features are listed', d.getElementById('storeDetailFeatures').querySelectorAll('span').length === 2);
ok('star row is five buttons', d.querySelectorAll('#storeRating .store-star').length === 5);
ok('review count is stated', /4.5 from 2 reviews/.test(d.getElementById('storeRating').textContent));
ok('a saved listing reads as saved', d.getElementById('storeFavBtn').textContent === 'Saved ✓');
store.setFav(new Set());
store.detail(FULL);
ok('an unsaved listing offers to save it', d.getElementById('storeFavBtn').textContent === 'Save');
store.setFav(new Set(['complete-commerce']));

store.detail({
  slug: 'x', title: 'Preview bot', summary: 'Preview only.', category: 'Tools', difficulty: 'Beginner',
  framework: 'aiogram', version: '1.0.0', code_lines: 40, install_count: 0, rating: 0, rating_count: 0,
  author: 'someone', features: [], code_full: false, code_preview: 'import os', reviews: [],
});
ok('anonymous detail shows a preview, not the file',
   /sign in to read and deploy the whole file/.test(d.getElementById('storeDetailCode').textContent));
ok('deploy is disabled without the file', d.getElementById('storeDeployBtn').disabled === true);
ok('and it says why', /Preview — the full file opens when you are signed in/.test(
   d.getElementById('storeCodeLabel').textContent));

console.log(`test_store_ui: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
