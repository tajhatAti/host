const fs = require('fs');
const vm = require('vm');
const {JSDOM} = require('jsdom');
const src = fs.readFileSync('static/pro.js', 'utf8');
const start = src.indexOf('let _adminFetching');
const end = src.indexOf('/* Live refresh for the admin panel.', start);
const dom = new JSDOM('<div class="dash-tabs"></div><main class="dash-main"></main>', {url:'https://site.test/admin'});
let attempts=0, switched=[], notices=[];
const fragment='<div class="dash-tab-content" id="tab-admin"><div id="admStats"></div></div>';
const context={window:dom.window, document:dom.window.document, localStorage:dom.window.localStorage,
  API:'', authToken:'token', currentTab:'overview', _clientPath:()=>'/admin',
  fetch:async()=>{ attempts++; return attempts===1 ? {ok:false,status:503} : {ok:true,status:200,text:async()=>fragment}; },
  switchTab:(tab)=>switched.push(tab), loadAdminPanel:()=>{}, toast:(m)=>notices.push(m),
  console, Promise, setTimeout};
vm.createContext(context); vm.runInContext(src.slice(start,end), context);
context.applyAdminVisibility({is_admin:1});
setTimeout(()=>{
  if(attempts!==1) throw new Error('initial protected markup request not made');
  if(!notices.length) throw new Error('transient failure stayed silent');
  const btn=dom.window.document.getElementById('tabBtnAdmin');
  if(!btn) throw new Error('admin button missing');
  btn.click();
  setTimeout(()=>{
    if(attempts!==2) throw new Error('click did not retry failed request');
    if(!dom.window.document.getElementById('tab-admin')) throw new Error('admin fragment not mounted');
    if(switched.at(-1)!=='admin') throw new Error('direct /admin intent was not completed');
    console.log('5 admin boot/retry checks passed');
  },0);
},0);
