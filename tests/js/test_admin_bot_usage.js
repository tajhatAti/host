const fs = require('fs');
const vm = require('vm');
const {JSDOM} = require('jsdom');
const html = `<div id="admBotStats"></div><div id="admBotSpark"></div><div id="admBotCommands"></div><div id="admBotPeople"></div><table id="admBotEvents"></table><select id="admBotDays"><option value="30">30</option></select><button id="admBotCsv"></button>`;
const dom = new JSDOM(html, {url:'https://example.test/admin'});
const src = fs.readFileSync('static/pro.js','utf8');
const start = src.indexOf('function _admAgo');
const end = src.indexOf('function renderAdminStats', start);
const context = {document:dom.window.document, Date, console, localStorage:dom.window.localStorage,
  fetch:async()=>({ok:false}), URL:dom.window.URL, setTimeout};
vm.createContext(context); vm.runInContext(src.slice(start,end), context);
const attack='<img src=x onerror="globalThis.pwned=1">';
context.renderAdminBotUsage({people:1,linked_people:0,unlinked_people:1,actions:1,today:1,failures:1,
 daily:[{day:'2026-08-18',count:1}], commands:[{command:attack,count:1,failures:1}],
 users:[{chat_id:'1',display_name:attack,actions:1,last_seen:'2026-08-18 10:00:00'}],
 events:[{created_at:'2026-08-18T10:00:00+00:00',chat_id:'1',display_name:attack,command:attack,payload:attack,outcome:'error'}]});
if (dom.window.document.querySelector('img')) throw new Error('untrusted Telegram data became HTML');
if (!dom.window.document.body.textContent.includes(attack)) throw new Error('untrusted text not rendered');
if (dom.window.document.querySelectorAll('#admBotSpark > i').length !== 1) throw new Error('sparkline missing');
const ago=context._admAgo('2026-08-18T10:00:00+00:00');
if (!ago.includes('ago')) throw new Error('offset timestamp not parsed: '+ago);
console.log('4 admin bot usage checks passed');
