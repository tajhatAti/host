const fs = require('fs');
const vm = require('vm');
const src = fs.readFileSync('static/pro.js', 'utf8');
const start = src.indexOf('const JOB_SECTIONS');
const end = src.indexOf('const TAB_PATHS', start);
const context = {};
vm.createContext(context);
vm.runInContext(src.slice(start, end), context);
const parse = context.parseJobPath;
function eq(path, expected) {
  const got = JSON.parse(JSON.stringify(parse(path)));
  if (JSON.stringify(got) !== JSON.stringify(expected)) throw new Error(`${path}: ${JSON.stringify(got)}`);
}
eq('/bots/my-bot', {slug:'my-bot',section:'editor',legacy:false});
eq('/bots/my-bot/logs', {slug:'my-bot',section:'logs',legacy:false});
eq('/bots/my-bot/database/', {slug:'my-bot',section:'database',legacy:false});
eq('/bots/owner/my-bot', {slug:'my-bot',section:'editor',legacy:true});
eq('/bots/owner/my-bot/page', {slug:'my-bot',section:'details',legacy:true});
eq('/bots/logs', {slug:'logs',section:'editor',legacy:false});
eq('/runspace/old-bot', {slug:'old-bot',section:'editor',legacy:false});
if (!parse('/bots/my-bot/typo/extra')?.invalid) throw new Error('mistyped section accepted');
console.log('8 bot URL checks passed');
