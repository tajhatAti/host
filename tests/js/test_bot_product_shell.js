const fs = require('fs');
const html = fs.readFileSync('index.html', 'utf8');
const js = fs.readFileSync('static/pro.js', 'utf8');
const css = fs.readFileSync('static/app.css', 'utf8');

let passed = 0;
function ok(name, value) {
  if (!value) throw new Error('FAIL: ' + name);
  passed += 1;
}

// The signed-in shell presents the product's actual information architecture.
const bottom = html.match(/<nav class="bottom-nav bot-bottom-nav"[\s\S]*?<\/nav>/)?.[0] || '';
ok('mobile navigation exists', !!bottom);
ok('mobile navigation has Bots', />Bots</.test(bottom));
ok('mobile navigation has one Add Bot action', /id="bnAddBot"/.test(bottom));
ok('mobile navigation has Account', />Account</.test(bottom));
ok('mobile navigation advertises Store', />Store</.test(bottom));
ok('mobile navigation advertises Code', />Code</.test(bottom));
ok('mobile navigation does not advertise generic Home', !/>Home</.test(bottom));
ok('mobile navigation does not advertise a second Menu', !/>Menu</.test(bottom));
ok('four real mobile destinations exist', (bottom.match(/data-tab=/g) || []).length === 4);

// Existing bookmarks keep working, but the bot product owns the default route.
ok('/bots is the canonical jobs route', /"\/bots":\s*"jobs"/.test(js));
ok('legacy dashboard opens Bots', /"\/dashboard":\s*"jobs"/.test(js));
ok('signed-in root is replaced with /bots', /replaceState\(\{\},\s*"",\s*"\/bots"\)/.test(js));
ok('Bots is the initial app state', /let currentTab = "jobs";/.test(js));
ok('new bot URLs use /bots, never /runspace', /return "\/bots\/" \+ _slugify/.test(js) && !/return "\/runspace\/" \+ _slugify/.test(js));
ok('bot name is hidden and detected from token', /id="jobName"[^>]*type="text"/.test(html) && /class="rs-meta" hidden/.test(html) && /telegram_bot_username[\s\S]*name\.value/.test(js));
ok('token is the first Add Bot step', /data-rs-step="connect"><b>1<\/b> Connect bot/.test(html));

// One action implementation is shared by all surfaces.
ok('one openAddBot helper exists', (js.match(/function openAddBot\s*\(/g) || []).length === 1);
ok('Add Bot delegates to canonical rail control', /function openAddBot[\s\S]*getElementById\("btnNew"\)[\s\S]*button\.click\(\)/.test(js));
ok('mobile Add Bot uses shared helper', /bnAddBot\.addEventListener\("click", openAddBot\)/.test(js));

// RunSpace becomes the product surface instead of sitting below a second header.
ok('generic header is hidden inside Bots', /body\.rs-active \.dash-bar\s*\{[^}]*display:\s*none\s*!important/.test(css));
ok('legacy general-purpose navigation is hidden', /\.product-legacy\s*\{\s*display:\s*none\s*!important/.test(css));
ok('account remains reachable from bot menu', /id="rsAccountMenu"/.test(html));
ok('starter journey is described as two steps', /<ol class="steps bot-steps">/.test(html) && /Connect &amp; deploy/.test(html));

console.log(`test_bot_product_shell: ${passed} passed`);
