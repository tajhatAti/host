const fs=require('fs');
const HTML=fs.readFileSync('index.html','utf8'),CSS=fs.readFileSync('static/app.css','utf8'),JS=fs.readFileSync('static/pro.js','utf8');
let pass=0,fail=0;const ok=(n,c,e)=>{if(c)pass++;else{fail++;console.log(`  FAIL ${n}${e?' -> '+e:''}`)}};
console.log('[1] one top-level control');
ok('legacy hamburger is visually removed',/#tab-jobs #wbMenuBtn,[\s\S]{0,180}#tab-jobs #btnInspector \{ display:none !important/.test(CSS));
ok('header Run is not force-hidden',!/#tab-jobs #btnRunQuick[\s\S]{0,40}display:none !important/.test(CSS));
ok('header Save sits beside Run',/id="btnSaveQuick"/.test(HTML)&&/id="btnRunQuick"/.test(HTML));
ok('Save writes without redeploying',/save_only:\s*true/.test(JS));
ok('Ctrl+S saves the bot instead of running it',/key: "Mod-s"[\s\S]{0,90}saveJobCode/.test(JS));
ok('three-dot remains the unified trigger',/id="rsMoreBtn"/.test(HTML)&&/id="rsMoreMenu"/.test(HTML));
ok('old standalone bot-list panel is gone',!(/id="rsJobsPop"/.test(HTML)));
ok('breadcrumb opens the same three-dot menu',/rsCrumbRoot[\s\S]{0,300}rsMoreBtn[\s\S]{0,30}\.click/.test(JS));
console.log('[2] complete but minimal contents');
for(const id of ['rsMenuCurrent','rsUnifiedBotList','btnNewInMenu','btnStartJob','btnRestartJob','btnStopJob','btnFullDetails','btnDeleteInMenu'])ok(`${id} is in the panel`,HTML.includes(`id="${id}"`));
ok('primary action says Save & Run',/id="btnStartJob"[\s\S]{0,500}>Save &amp; Run</.test(HTML));
ok('status copy distinguishes process/stopped/problem',/Process running/.test(JS)&&/Needs attention/.test(JS)&&/Stopped/.test(JS));
ok('bot rows switch in place, not to another page',/rs-jp-item[\s\S]{0,900}selectJob\(row\.getAttribute/.test(JS));
ok('bot rows expose direct delete',/data-delete-jid/.test(JS)&&/deleteJobById\(id,del\)/.test(JS));
/* [3] compact OPAQUE visual. This used to require a bounded backdrop blur.
   test_no_glass.js is the newer and stricter brief — "remove it entirely, no
   exceptions" — and the panel's own mobile override already set
   backdrop-filter:none, so desktop was the only place glass survived. The
   panel is now a solid card at every width; one rule, not two. */
console.log('[3] compact opaque visual');
ok('panel is capped at 310px',/#tab-jobs #rsMoreMenu \{[^}]*width:310px/.test(CSS));
ok('panel is a solid card, never frosted',
   /#tab-jobs #rsMoreMenu \{[^}]*background:var\(--card\)/.test(CSS) &&
   !/#tab-jobs #rsMoreMenu \{[^}]*backdrop-filter:blur/.test(CSS));
ok('panel stays below viewport height',/#tab-jobs #rsMoreMenu \{[^}]*max-height:min\(72dvh,620px\)/.test(CSS));
ok('the panel is the only scroll owner',/#tab-jobs #rsUnifiedBotList \{ overflow:visible; \}/.test(CSS)&&!/#tab-jobs #rsUnifiedBotList \{[^}]*overflow-y:auto/.test(CSS));
ok('reduced transparency has a solid fallback',/@media \(prefers-reduced-transparency:reduce\)[\s\S]{0,180}backdrop-filter:none/.test(CSS));
console.log(`test_runspace_top_menu: ${pass} passed, ${fail} failed`);process.exit(fail?1:0);
