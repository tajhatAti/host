const fs=require('fs'),vm=require('vm');const {JSDOM}=require('jsdom');
const JS=fs.readFileSync('static/pro.js','utf8'),FRAG=fs.readFileSync('templates/admin_panel.html','utf8'),CSS=fs.readFileSync('static/app.css','utf8');
function extract(name){let s=JS.indexOf(`function ${name}(`),i=JS.indexOf('{',s),d=0;for(let k=i;k<JS.length;k++){if(JS[k]==='{')d++;else if(JS[k]==='}'&&!--d)return JS.slice(s,k+1);}throw Error(name);}
const dom=new JSDOM(FRAG);const ctx={document:dom.window.document,console,_admToggleRunner:()=>{},_admDeleteRunner:()=>{},_botText:(t,v,c)=>{const e=dom.window.document.createElement(t);if(c)e.className=c;e.textContent=v??'—';return e;}};vm.createContext(ctx);vm.runInContext(extract('renderAdminRunners'),ctx);
const attack='<img src=x onerror=alert(1)>';ctx.renderAdminRunners({total_enabled:1,runners:[{id:1,label:attack,url:'https://runner.example/'+attack,enabled:true,online:true,jobs:2,capacity:5,mem_mb:90,assigned_jobs:2}],environment_runners:[]});
if(dom.window.document.querySelector('img'))throw Error('runner metadata became HTML');
if(!dom.window.document.body.textContent.includes(attack))throw Error('runner full information missing');
if(!dom.window.document.getElementById('admRunnerSave')||!dom.window.document.getElementById('admRunnerGenerate'))throw Error('easy add-runner controls missing');
if(!/\.adm-runner-fields[^}]*grid-template-columns/.test(CSS))throw Error('runner form layout missing');
if(/id="admRunnerSecret"[^>]*value=/.test(FRAG))throw Error('runner secret embedded in markup');
console.log('5 admin runner UI checks passed');
