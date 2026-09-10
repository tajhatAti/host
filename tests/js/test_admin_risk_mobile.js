const fs=require('fs'), vm=require('vm');
const {JSDOM}=require('jsdom');
const JS=fs.readFileSync('static/pro.js','utf8'), CSS=fs.readFileSync('static/app.css','utf8');
const dom=new JSDOM(`<div id="admRiskStats"></div><div id="admIpClusters"></div><div id="admFpClusters"></div><div id="admSignupFlags"></div><div id="admActiveBlocks"></div><button id="admRiskRefresh"></button><button id="admBlockConfirm"></button>`,{url:'https://x.test/admin'});
const context={document:dom.window.document, console, prompt:()=>null, openAdminUser:()=>{}, openModal:()=>{}, closeModal:()=>{}, toast:()=>{}, loadAdminPanel:async()=>{}, api:async()=>{},
  _botText:(tag,value,cls)=>{const e=dom.window.document.createElement(tag);if(cls)e.className=cls;e.textContent=value==null?'—':String(value);return e;}};
vm.createContext(context);
const a=JS.indexOf('let _admBlockDraft'), b=JS.indexOf('function _admAgo',a);
vm.runInContext(JS.slice(a,b),context);
const attack='<img src=x onerror=alert(1)>';
context.renderAdminRisk({clusters:[{ip:'203.0.113.1',account_count:2,device_count:1,running_jobs:2,job_limit:9,accounts:[{id:2,username:attack}]}]},
 {clusters:[{fingerprint:attack,fingerprint_full:'a'.repeat(64),account_count:2,running_jobs:2,job_limit:3,accounts:[]}]},
 {flags:[]},{active:1,blocks:[{id:1,active:true,scope:'ip',value:attack,reason:attack,expires_at:null}]});
if(dom.window.document.querySelector('img')) throw new Error('risk data parsed as HTML');
if(!dom.window.document.body.textContent.includes(attack)) throw new Error('full risk information missing');
if(dom.window.document.querySelectorAll('.adm-risk-card').length!==2) throw new Error('cluster cards missing');
if(!/\.adm-risk-grid[^\{]*\{[^}]*grid-template-columns:1fr/.test(CSS)) throw new Error('mobile risk stack missing');
if(!/\.adm-detail-modal \.ah-modal-card\s*\{[^}]*width:100%/.test(CSS)) throw new Error('mobile bottom sheet missing');
console.log('5 admin risk/mobile checks passed');
