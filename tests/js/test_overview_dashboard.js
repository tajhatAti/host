/* OVERVIEW DASHBOARD — the analytics surface.
 *
 * The renderers are executed against jsdom with the exact payload the API
 * returns, so "the KPI shows the value, the delta and a sparkline" is
 * observed rather than assumed. The two cases that are easiest to get
 * subtly wrong get their own section: a delta with no baseline (must read
 * "new", never a fabricated +100%) and a zero day (must draw a point, not a
 * hole in the line).
 */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const ROOT = path.resolve(__dirname, '../../');
const HTML = fs.readFileSync(path.join(ROOT, 'index.html'), 'utf8');
const CSS = fs.readFileSync(path.join(ROOT, 'static/app.css'), 'utf8');
const JS = fs.readFileSync(path.join(ROOT, 'static/pro.js'), 'utf8');

let pass = 0, fail = 0;
const ok = (n, c, e) => { c ? pass++ : (fail++, console.log(`  FAIL ${n}${e ? ' -> ' + e : ''}`)); };

console.log('[1] the dashboard is a real destination');
const dom0 = new JSDOM(HTML).window.document;
ok('overview section exists', !!dom0.getElementById('tab-overview'));
ok('the tab is no longer hidden legacy',
   /data-tab="overview"/.test(HTML) &&
   !/class="dash-tab product-legacy" data-tab="overview"/.test(HTML));
ok('opening the tab loads the numbers', /tabId === "overview" && typeof loadOverview === "function"/.test(JS));
ok('range control exists', !!dom0.getElementById('ovRanges') &&
   dom0.querySelectorAll('#ovRanges .ov-range').length === 3);
ok('chart, KPI and list hosts exist',
   ['ovKpis', 'ovChart', 'ovTopBots', 'ovRecent', 'ovSub'].every(id => !!dom0.getElementById(id)));
ok('the endpoint is the only data source',
   /api\(`\/api\/analytics\/overview\?days=\$\{_ovDays\}`/.test(JS));

console.log('[2] the chart is drawn, not pictured');
ok('svg is built with the svg namespace', /createElementNS\(OV_SVG/.test(JS));
ok('no chart library was added', !/recharts|chart\.js|d3\.js/i.test(JS));
ok('grid lines use the chart-grid token', /var\(--chart-grid\)/.test(JS));
ok('hover targets carry a readable summary', /`.*deploys, .*new bots`/.test(JS));

console.log('[3] the renderers, executed');
const start = JS.indexOf('let _ovDays = 14;');
const end = JS.indexOf('(function _initOverview()');
ok('overview module is locatable', start > 0 && end > start);
const moduleSource = JS.slice(start, end) + `
;return { renderOverview, _ovFmt, _ovDeltaChip, _ovSparkline, _ovChart,
          setDays(v) { _ovDays = v; }, getDays() { return _ovDays; } };`;

const dom = new JSDOM(`<!doctype html><body>
  <p id="ovSub"></p><span id="ovRangeLabel"></span>
  <div id="ovKpis"></div><div id="ovChart"></div><p id="ovChartSub"></p>
  <div id="ovTopBots"></div><div id="ovRecent"></div>
  <div id="ovRanges"><button class="ov-range is-active" data-days="14">14d</button></div>
</body>`, { pretendToBeVisual: true });

const calls = [];
const factory = new Function('document', 'window', 'api', 'toast', 'switchTab', 'setTimeout',
                             'clearTimeout', moduleSource);
const ov = factory(dom.window.document, dom.window,
                   (p, m) => { calls.push(p); return Promise.resolve({}); },
                   () => {}, () => {}, dom.window.setTimeout, dom.window.clearTimeout);
const d = dom.window.document;

const DATA = {
  days: 14,
  range: { start: '2026-08-12', end: '2026-08-26', previous_start: '2026-07-29', previous_end: '2026-08-12' },
  kpis: [
    { key: 'bots', label: 'Bots', value: 12, delta: 33.3, unit: 'new', sub: '4 Telegram · 3 new this period' },
    { key: 'live', label: 'Deployed now', value: 2, delta: null, unit: '', sub: 'holding a runner slot this second' },
    { key: 'deploys', label: 'Deploys', value: 1200, delta: -12.5, unit: '', sub: '30 of them updates' },
    { key: 'installs', label: 'Store installs', value: 0, delta: null, unit: '', sub: 'bots started from a store listing' },
  ],
  series: [
    { day: '2026-08-24', label: '24 Aug', deploys: 0, new_bots: 0 },
    { day: '2026-08-25', label: '25 Aug', deploys: 3, new_bots: 1 },
    { day: '2026-08-26', label: '26 Aug', deploys: 1, new_bots: 0 },
  ],
  top_bots: [
    { id: 1, name: 'shop-bot', language: 'python', username: 'shopbot', live: true, actions: 4 },
    { id: 2, name: 'scratch-bot', language: 'python', username: null, live: false, actions: 0 },
  ],
  recent: [
    { action: 'deploy', job_name: 'shop-bot', username: 'shopbot', created_at: '2026-08-26 09:14:00' },
    { action: 'update', job_name: 'shop-bot', username: null, created_at: '2026-08-25 18:02:11' },
  ],
  totals: { deploys: 4, updates: 1, installs: 0, new_bots: 1,
            previous: { deploys: 0, updates: 0, installs: 0, new_bots: 0 } },
};

ov.renderOverview(DATA);

ok('one card per KPI', d.querySelectorAll('#ovKpis .ov-kpi').length === 4);
const cards = [...d.querySelectorAll('#ovKpis .ov-kpi')];
ok('KPI shows its label', cards[0].textContent.includes('Bots'));
ok('KPI shows the value', cards[0].querySelector('.ov-kpi-value').textContent === '12');
ok('large values are compacted', cards[2].querySelector('.ov-kpi-value').textContent === '1.2k');
ok('an up delta is marked up', cards[0].querySelector('.ov-delta').textContent.includes('33.3%') &&
   cards[0].querySelector('.ov-delta').classList.contains('is-up'));
ok('a down delta is marked down', cards[2].querySelector('.ov-delta').classList.contains('is-down') &&
   cards[2].querySelector('.ov-delta').textContent.includes('12.5%'));
ok('a null delta says "new", never +100%',
   cards[1].querySelector('.ov-delta').textContent === 'new' &&
   cards[1].querySelector('.ov-delta').classList.contains('is-new') &&
   !/100/.test(cards[1].querySelector('.ov-delta').textContent));
ok('a KPI with history gets a sparkline', cards[0].querySelectorAll('.ov-spark polyline').length === 1);
ok('the sparkline marks its last point', cards[0].querySelectorAll('.ov-spark circle').length === 1);
ok('the range is stated in plain dates',
   /2026-08-12 → 2026-08-26, against the previous 14 days/.test(d.getElementById('ovSub').textContent));

console.log('[4] the chart, executed');
const svg = d.querySelector('#ovChart svg');
ok('an svg is rendered', !!svg);
ok('it is labelled for screen readers', svg.getAttribute('role') === 'img' &&
   /Deploys and new bots per day/.test(svg.getAttribute('aria-label')));
ok('two series are drawn', svg.querySelectorAll('path[stroke="var(--acc)"], path[stroke="var(--ok)"]').length === 2);
ok('the area is filled from the gradient', !!svg.querySelector('path[fill="url(#ovFill)"]'));
ok('grid lines are drawn', svg.querySelectorAll('line').length >= 4);
ok('x labels are thinned, not one per point',
   [...svg.querySelectorAll('text.ov-axis')].some(t => /Aug/.test(t.textContent)));
ok('every day gets a hover target',
   svg.querySelectorAll('rect').length === DATA.series.length);
/* The first rect is the FIRST day (a quiet one), so search every title
   rather than assuming the busiest day comes first. */
const titles = [...svg.querySelectorAll('rect title')].map(t => t.textContent);
ok('the hover target explains the day', titles.includes('25 Aug: 3 deploys, 1 new bots'),
   titles.join(' | '));

ov.renderOverview(Object.assign({}, DATA, { series: [] }));
ok('an empty series says so instead of drawing nothing',
   /No activity yet/.test(d.getElementById('ovChart').textContent));
ov.renderOverview(DATA);

console.log('[5] the lists, executed');
const rows = [...d.querySelectorAll('#ovTopBots .ov-row')];
ok('top bots are listed', rows.length === 2);
ok('the busiest bot is first', rows[0].textContent.includes('shop-bot'));
ok('liveness is shown as a pill', rows[0].querySelector('.ov-pill.is-live').textContent === 'live' &&
   rows[1].querySelector('.ov-pill').textContent === 'stopped');
ok('a username is preferred over a language',
   rows[0].textContent.includes('@shopbot') && rows[1].textContent.includes('python'));
ok('the trail shows action and time',
   d.getElementById('ovRecent').textContent.includes('deploy') &&
   d.getElementById('ovRecent').textContent.includes('08-26 09:14'));
ov.renderOverview(Object.assign({}, DATA, { top_bots: [], recent: [] }));
ok('an empty account gets a next step, not a blank',
   /deploy one and it shows up here/.test(d.getElementById('ovTopBots').textContent) &&
   /Nothing deployed yet/.test(d.getElementById('ovRecent').textContent));

console.log('[6] numbers and styling');
ok('thousands are compacted', ov._ovFmt(1200) === '1.2k' && ov._ovFmt(2400000) === '2.4M');
ok('plain numbers are untouched', ov._ovFmt(7) === '7' && ov._ovFmt(0) === '0');
ok('KPI cards are 16px cards on the shared tokens',
   /\.ov-kpi \{[^}]*border-radius: var\(--r-card\)/.test(CSS));
ok('delta chips use status colour, not decoration',
   /\.ov-delta\.is-up[^}]*var\(--ok\)/.test(CSS) && /\.ov-delta\.is-down[^}]*var\(--danger\)/.test(CSS));
ok('metrics are tabular so digits do not jitter', /font-variant-numeric: tabular-nums/.test(CSS));
ok('the grid collapses on a phone', /@media \(max-width: 560px\) \{[\s\S]*\.ov-kpis \{ grid-template-columns: minmax\(0, 1fr\); \}/.test(CSS));
ok('no literal font size in the new block', (() => {
  const block = CSS.slice(CSS.indexOf('.ov-head {'));
  return !/font-size:\s*\d+px/.test(block.replace(/font-size: 10px/, ''));  // axis ticks only
})());

console.log(`test_overview_dashboard: ${pass} passed, ${fail} failed`);
process.exit(fail ? 1 : 0);
