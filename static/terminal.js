/* ============================================================
   AHAD CO · TERMUX-STYLE PTY TERMINAL  (v=20260722k — multi-slot tabs)
   Real bash PTY. Multiple concurrent shell slots per user.
   🔥 = 24/7 slot (never idled out; auto-runs ~/.ahad_slots/N/run.sh on boot).
   Extra-keys 2-row bar pinned above soft keyboard via visualViewport.
   ============================================================ */
(function(){
  'use strict';
  if (window.__wbTermLoaded) return;
  window.__wbTermLoaded = true;

  var instances = {};
  var timers = {};
  var $ = function(id){ return document.getElementById(id); };
  var wsProto = location.protocol === 'https:' ? 'wss' : 'ws';
  var token = function(){ return (localStorage.getItem('ahad_token')||'').trim(); };
  var _termPage=null,_termStandalone=null,_termCtx=null,_termLoading=null;
  var _cachedFS = -1, _fsW = -1;

  // ---------- Standalone multi-slot state ----------
  var stand = {
    slots: [],        // [{id, ticket, slot, name, persist, ws, open, buf, raf, …}]
    activeIdx: -1,
    nextSlot: 1,
    hostEl: null,
    slotsBar: null,
    kbdEl: null,
    bodyEl: null,
    landingEl: null,
    termBase: null,    // shared xterm Terminal (only one visible at a time)
    fitAddon: null,
    ctrl:false, alt:false,
    _lastCols:0, _lastRows:0,
  };

  function fontSz(){
    var w = window.innerWidth || 1024;
    if (w === _fsW) return _cachedFS;
    _fsW = w;
    _cachedFS = (w <= 360) ? 12 : (w <= 480) ? 13 : 14;
    return _cachedFS;
  }

  function safeFitTerm(term, host){
    if (!term) return;
    try {
      var par = host && host.parentElement;
      if (!par) return;
      term.__fitRetries = (term.__fitRetries|0) + 1;
      if (term.__fitRetries > 20) { term.__fitRetries=0; return; }
      var core = term._core;
      var rs = core && core._renderService;
      var dim = rs && rs.dimensions;
      var cell = dim && dim.css && dim.css.cell;
      if (!cell || !(cell.width>0) || !(cell.height>0)){
        clearTimeout(term.__fitT);
        term.__fitT = setTimeout(function(){ safeFitTerm(term, host); }, 180);
        return;
      }
      var r = par.getBoundingClientRect();
      if (r.width < 20 || r.height < 20){
        clearTimeout(term.__fitT);
        term.__fitT = setTimeout(function(){ safeFitTerm(term, host); }, 200);
        return;
      }
      term.__fitRetries = 0;
      if (stand.fitAddon && stand.fitAddon.fit) stand.fitAddon.fit();
    } catch(e){}
  }

  /* xterm is no longer a blocking <script> in the document head — it is
     300KB+ of CDN payload that only matters once a terminal is opened, and
     in the Telegram webview those round-trips were a large part of the
     startup lag. Fetch it the first time it is actually needed.

     Concurrent callers share one promise: without that, opening two slots
     quickly would inject the script twice and race. */
  var _xtermLoading = null;
  function _ensureXterm(){
    if (window.Terminal && window.FitAddon) return Promise.resolve(true);
    if (_xtermLoading) return _xtermLoading;
    _xtermLoading = new Promise(function(resolve){
      var pending = 2, failed = false;
      function one(src){
        var el = document.createElement('script');
        el.src = src;
        el.async = true;
        el.onload  = function(){ if (--pending === 0) resolve(!failed); };
        el.onerror = function(){ failed = true; if (--pending === 0) resolve(false); };
        document.head.appendChild(el);
      }
      one('https://cdn.jsdelivr.net/npm/xterm@5.3.0/lib/xterm.min.js');
      one('https://cdn.jsdelivr.net/npm/xterm-addon-fit@0.8.0/lib/xterm-addon-fit.min.js');
    });
    return _xtermLoading;
  }

  function makeXterm(){
    if (window.Terminal === undefined) return null;
    var t = new Terminal({
      cursorBlink: true, cursorStyle: 'bar', cursorWidth: 1,
      fontFamily: '"Courier New", ui-monospace, Menlo, Consolas, monospace',
      fontSize: fontSz(), lineHeight: 1.1, letterSpacing: 0,
      scrollback: 2000, convertEol: false,
      rendererType: 'canvas', allowProposedApi: true, allowTransparency: false,
      allowTouchSelection: true, rightClickSelectsWord: false,
      fastScrollSensitivity: 40, scrollSensitivity: 40,
      ignoreBracketedPasteMode: false,
      theme: {
        background: '#000000', foreground: '#c0c0c0',
        cursor: '#c0c0c0', cursorAccent: '#000000',
        selectionBackground: 'rgba(255,255,255,.25)',
        black:'#000',red:'#c91b00',green:'#00c200',yellow:'#c7c400',
        blue:'#0225c7',magenta:'#ca30c7',cyan:'#00c5c7',white:'#c7c7c7',
        brightBlack:'#676767',brightRed:'#ff6d67',brightGreen:'#5ff967',
        brightYellow:'#fefb67',brightBlue:'#6871ff',brightMagenta:'#ff76ff',
        brightCyan:'#5ffdff',brightWhite:'#feffff',
      },
    });
    try { var fa = new FitAddon.FitAddon(); t.loadAddon(fa); stand.fitAddon = fa; } catch(e){}
    return t;
  }

  // ---------- Context menu (long press) ----------
  function bindLongPress(el){
    if (!el || el._lpBound) return;
    el._lpBound = true;
    var tt = null, start = null, fired = false;
    function clr(){ if(tt){clearTimeout(tt);tt=null;} start=null; fired=false; }
    function onDown(e){
      if (e.target && e.target.closest && e.target.closest('button, .wb-term-kbd, .term-ctx, .wb-term-exit-fab, .wb-term-head, .wb-term-slots')) return;
      var p = (e.touches ? e.touches[0] : e); if (!p) return;
      start = { x: p.clientX, y: p.clientY }; fired = false; clr();
      tt = setTimeout(function(){
        if (!start) { tt=null; return; } fired = true;
        try{ if(e.cancelable) e.preventDefault(); }catch(_){}
        showCtxMenu(start.x, start.y);
        if (navigator.vibrate) try{navigator.vibrate(20);}catch(_){} tt=null;
      }, 420);
    }
    function onMove(e){
      if (!start) return; var p=(e.touches?e.touches[0]:e); if(!p) return;
      if (Math.abs(p.clientX-start.x)>14||Math.abs(p.clientY-start.y)>14) clr();
    }
    el.addEventListener('touchstart', onDown, {passive:true});
    el.addEventListener('touchmove', onMove, {passive:true});
    el.addEventListener('touchend', clr, {passive:true});
    el.addEventListener('touchcancel', clr, {passive:true});
    el.addEventListener('contextmenu', function(e){ e.preventDefault(); showCtxMenu(e.clientX,e.clientY); });
  }

  var _ctxOpen=false;
  function showCtxMenu(x,y){
    if (x==null||y==null) return;
    var slot = activeSlot(); if (!slot) return;
    var menu=$('termCtxMenu'); if(!menu) return;
    menu.style.display='flex';
    var w=180,h=220;
    var vv=window.visualViewport;
    var vx=vv?vv.offsetLeft:0, vy=vv?vv.offsetTop:0;
    var vw=vv?vv.width:window.innerWidth, vh=vv?vv.height:window.innerHeight;
    var left=Math.min(x-vx,vw-w-4); if(left<0) left=4;
    var top =Math.min(y-vy,vh-h-4); if(top<0)  top=4;
    menu.style.left=(vx+left)+'px'; menu.style.top=(vy+top)+'px';
    _ctxOpen=true;
    if(navigator.vibrate) try{navigator.vibrate(15);}catch(e){}
  }
  function hideCtxMenu(){ var m=$('termCtxMenu'); if(m) m.style.display='none'; _ctxOpen=false; }
  function ctxAction(act){
    var slot=activeSlot(); hideCtxMenu(); if(!slot) return;
    try{stand.termBase.focus();}catch(e){}
    if(act==='paste') doPaste(slot);
    else if(act==='copy') doCopy(slot);
    else if(act==='selectAll'){ try{stand.termBase.selectAll();}catch(e){} }
    else if(act==='ctrlc'){ sendRaw(slot,'\x03'); }
  }
  function initCtxMenu(){
    var menu=$('termCtxMenu'); if(!menu||menu._bound) return;
    menu._bound=true;
    menu.addEventListener('click',function(ev){
      var b=ev.target.closest('button[data-act]'); if(!b) return;
      ctxAction(b.getAttribute('data-act'));
    });
    ['touchstart','mousedown'].forEach(function(ev){
      document.addEventListener(ev,function(e){ if(!_ctxOpen) return; if(menu.contains(e.target)) return; hideCtxMenu(); },{passive:true});
    });
    window.addEventListener('scroll',hideCtxMenu,{passive:true});
    window.addEventListener('resize',hideCtxMenu);
    document.addEventListener('paste',function(ev){
      var slot=activeSlot(); if(!slot) return;
      var ta=stand.termBase.textarea;
      if(ta&&(ev.target===ta||(ta.contains&&ta.contains(ev.target)))) return;
      var txt=''; if(ev.clipboardData&&ev.clipboardData.getData) txt=ev.clipboardData.getData('text');
      if(!txt) return; ev.preventDefault(); pasteToTerm(slot,txt);
    });
    document.addEventListener('copy',function(ev){
      if(!stand.termBase) return; var sel='';
      try{if(stand.termBase.hasSelection()) sel=stand.termBase.getSelection();}catch(e){}
      if(!sel) return; if(ev.clipboardData){ ev.preventDefault(); ev.clipboardData.setData('text/plain',sel); }
    });
  }

  function activeSlot(){
    if (stand.activeIdx<0) return null;
    return stand.slots[stand.activeIdx] || null;
  }

  // ---------- WS IO ----------
  function sendRaw(slot,data){
    if(!slot||!slot.ws||slot.ws.readyState!==1) return false;
    try{slot.ws.send(JSON.stringify({type:'in',data:data})); return true;}catch(e){return false;}
  }
  function sendResize(slot){
    if(!slot||!slot.ws||slot.ws.readyState!==1||!stand.termBase) return;
    try{
      var cols=Math.max(10,(stand.termBase.cols|0)||80);
      var rows=Math.max(3,(stand.termBase.rows|0)||24);
      if(slot._lastCols===cols&&slot._lastRows===rows) return;
      slot._lastCols=cols; slot._lastRows=rows;
      slot.ws.send(JSON.stringify({type:'resize',cols:cols,rows:rows}));
    }catch(e){}
  }
  function disconnect(slot){
    if(!slot) return;
    if(timers[slot.id]){clearTimeout(timers[slot.id]);timers[slot.id]=null;}
    try{ if(slot._outT){cancelAnimationFrame(slot._outT); slot._outT=0;} }catch(e){slot._outT=0;}
    try{ if(slot._outBuf){ var d=slot._outBuf; slot._outBuf=''; if(d) stand.termBase.write(d); } }catch(e){}
    if(slot.ws){try{slot.ws.close();}catch(e){} slot.ws=null;}
  }

  function slotFromHello(slot, hello){
    slot.id = hello.id;
    slot.ticket = hello.ticket || slot.ticket;
    slot.slot = hello.slot || slot.slot;
    slot.name = hello.name || slot.name || ('Shell '+(hello.slot||slot.slot));
    slot.persist = !!hello.persist;
  }

  function flushOutSlot(slot){
    slot._outT=0;
    if(!slot._outBuf) return;
    // Only write if this slot is currently attached to the shared term
    var d=slot._outBuf; slot._outBuf='';
    if (activeSlot()===slot){ try{stand.termBase.write(d);}catch(e){} }
    else {
      // Ring buffer for offline slot
      slot._ring=(slot._ring||'')+d;
      if (slot._ring.length > 65536) slot._ring = slot._ring.slice(-65536);
    }
  }

  function connect(slot, opts){
    opts = opts||{};
    disconnect(slot);
    var tok=token();
    if(!tok){ timers[slot.id]=setTimeout(function(){connect(slot,opts);},1500); return; }
    slot._connecting=true;
    var body = {shell:'bash',cols:stand.termBase?(stand.termBase.cols||80):80,rows:stand.termBase?(stand.termBase.rows||24):24};
    if (slot.slot) body.slot = slot.slot;
    if (slot.name) body.name = slot.name;
    if (typeof slot.persist==='boolean') body.persist = slot.persist;
    body.reuse = !opts.force;
    fetch('/api/terminals',{
      method:'POST',
      headers:{'Content-Type':'application/json','Authorization':'Bearer '+tok},
      body: JSON.stringify(body),
    }).then(function(r){return r.json().then(function(j){return{ok:r.ok,j:j};});})
      .then(function(resp){
        slot._connecting=false;
        if(!resp.ok||!resp.j||!resp.j.ticket){
          timers[slot.id]=setTimeout(function(){connect(slot,opts);},2500); return;
        }
        slot.ticket=resp.j.ticket;
        slot.id=resp.j.id;
        slot.slot=resp.j.slot||slot.slot;
        slot.name=resp.j.name||slot.name;
        slot.persist=!!resp.j.persist;
        slot._outBuf=''; slot._outT=0; slot._ring='';
        var url=wsProto+'://'+location.host+'/api/term/ws?ticket='+encodeURIComponent(slot.ticket);
        var ws=new WebSocket(url);
        slot.ws=ws; ws.binaryType='arraybuffer';
        ws.onopen=function(){
          renderSlots();
          setTimeout(function(){ if(activeSlot()===slot){ safeFitTerm(stand.termBase, stand.bodyEl); try{stand.termBase.focus();}catch(e){} } },160);
          if(stand.landingEl) stand.landingEl.style.display='none';
        };
        ws.onmessage=function(ev){
          var obj; try{obj=JSON.parse(ev.data);}catch(e){return;}
          if(obj.type==='hello'){ slotFromHello(slot,obj); renderSlots(); attachSlot(slot); return; }
          if(obj.type==='out'&&typeof obj.data==='string'){
            slot._outBuf+=obj.data;
            if(!slot._outT) slot._outT=requestAnimationFrame(function(){flushOutSlot(slot);});
          } else if(obj.type==='exit'){
            if(slot._outT){cancelAnimationFrame(slot._outT); slot._outT=0;}
            if(slot._outBuf){flushOutSlot(slot);}
            // 24/7 slots auto-reconnect (respawn) — same as RunSpace
            if(slot.persist){
              timers[slot.id]=setTimeout(function(){connect(slot,{force:true});},1500);
            } else {
              slot._dead=true;
              // Keep slot but show it as stopped; user tap will reconnect
              renderSlots();
            }
          }
        };
        ws.onerror=function(){};
        ws.onclose=function(){
          if(!slot.open) return;
          if(timers[slot.id]) clearTimeout(timers[slot.id]);
          if(slot.persist){ timers[slot.id]=setTimeout(function(){connect(slot,{force:true});},2000); }
        };
        renderSlots();
      }).catch(function(){
        slot._connecting=false;
        timers[slot.id]=setTimeout(function(){connect(slot,opts);},2500);
      });
  }

  function attachSlot(slot){
    // Detach any other slot, move the shared xterm to this slot's buffer.
    // We clear the screen and replay ring buffer so user sees last output.
    if(!stand.termBase || !stand.bodyEl) return;
    if (stand.termBase.element.parentElement !== stand.bodyEl){
      stand.bodyEl.innerHTML='';
      stand.termBase.open(stand.bodyEl);
    }
    try{ stand.termBase.reset(); }catch(e){ stand.termBase.clear(); }
    // Replay ring buffer
    if (slot._ring){
      try{ stand.termBase.write(slot._ring); }catch(e){}
    }
    sendResize(slot);
    requestAnimationFrame(function(){ safeFitTerm(stand.termBase, stand.bodyEl); try{stand.termBase.focus();}catch(e){} });
  }

  // ---------- Extra keys / virtual keyboard ----------
  function releaseSticky(){
    if(stand.ctrl){stand.ctrl=false; document.querySelectorAll('.wb-term-kbd button[data-k="ctrl"]').forEach(function(b){b.classList.remove('on');});}
    if(stand.alt){stand.alt=false; document.querySelectorAll('.wb-term-kbd button[data-k="alt"]').forEach(function(b){b.classList.remove('on');});}
  }
  function sendSpecial(key){
    var slot=activeSlot(); if(!slot||!stand.termBase) return;
    var map={
      esc:'\x1b',tab:'\t',enter:'\r',
      up:'\x1b[A',down:'\x1b[B',left:'\x1b[D',right:'\x1b[C',
      home:'\x1b[H',end:'\x1b[F',pgup:'\x1b[5~',pgdn:'\x1b[6~',
    };
    if(key==='ctrl'){
      stand.ctrl=!stand.ctrl;
      document.querySelectorAll('.wb-term-kbd button[data-k="ctrl"]').forEach(function(b){b.classList.toggle('on',stand.ctrl);});
      if(stand.ctrl) setTimeout(releaseSticky,4000);
      try{stand.termBase.focus();}catch(e){} return;
    }
    if(key==='alt'){
      stand.alt=!stand.alt;
      document.querySelectorAll('.wb-term-kbd button[data-k="alt"]').forEach(function(b){b.classList.toggle('on',stand.alt);});
      if(stand.alt) setTimeout(releaseSticky,4000);
      try{stand.termBase.focus();}catch(e){} return;
    }
    if(key==='drawer'){
      document.body.classList.remove('term-fullscreen');
      document.documentElement.classList.remove('term-lock');
      document.body.classList.remove('term-lock');
      releaseSticky();
      if(typeof window.switchTab==='function') window.switchTab('overview');
      return;
    }
    if(key==='kbd'){
      if(document.activeElement===stand.termBase.textarea) stand.termBase.blur(); else stand.termBase.focus();
      return;
    }
    if(key==='paste'){ doPaste(slot); return; }
    if(key==='copy'){ doCopy(slot, document.querySelector('#standKbd button[data-k="copy"]')); return; }
    if(key==='save'){ sendRaw(slot,'\x0f'); releaseSticky(); return; }
    if(key==='exit'){ sendRaw(slot,'\x18'); releaseSticky(); return; }
    var s=map[key]; if(!s) return;
    var isNav=/^(up|down|left|right|home|end|pgup|pgdn|esc|tab|enter)$/.test(key);
    if(stand.alt&&!isNav){ s='\x1b'+s.replace(/^\x1b/,''); stand.alt=false; document.querySelectorAll('.wb-term-kbd button[data-k="alt"]').forEach(function(b){b.classList.remove('on');}); }
    if(stand.ctrl&&!isNav&&key.length===1){
      var cc=key.charCodeAt(0);
      if(cc>=97&&cc<=122) s=String.fromCharCode(cc-96);
      else if(cc>=65&&cc<=90) s=String.fromCharCode(cc-64);
      releaseSticky();
    } else if(isNav){ releaseSticky(); }
    sendRaw(slot,s);
    try{stand.termBase.focus();}catch(e){}
  }

  function pasteToTerm(slot,text){
    var clean=String(text||'').replace(/\r\n/g,'\n').replace(/\r/g,'\n');
    if(!clean) return;
    if(typeof stand.termBase.paste==='function'){
      var CHUNK=4096, DELAY=10, i=0;
      function chunk(){
        if(i>=clean.length){try{stand.termBase.focus();}catch(e){} return;}
        var piece=clean.slice(i,i+CHUNK); i+=CHUNK;
        try{stand.termBase.paste(piece);}catch(_e){ sendRaw(slot,(i-CHUNK===0?'\x1b[200~':'')+piece); }
        setTimeout(chunk,DELAY);
      } chunk(); return;
    }
    sendRaw(slot,'\x1b[200~'+clean+'\x1b[201~');
  }
  function doPaste(slot){
    var btn=document.querySelector('#standKbd button[data-k="paste"]');
    function sendText(t){ if(!t){try{stand.termBase.focus();}catch(e){}return;} pasteToTerm(slot,t); flashBtn(btn,true); }
    if(navigator.clipboard&&navigator.clipboard.readText) navigator.clipboard.readText().then(sendText).catch(fb); else fb();
    function fb(){ flashBtn(btn,false); }
  }
  function doCopy(slot,btn){
    var txt=''; try{if(stand.termBase.hasSelection()) txt=stand.termBase.getSelection();}catch(e){}
    if(!txt) try{var s=window.getSelection();if(s) txt=s.toString();}catch(e){}
    if(!txt){flashBtn(btn,false);return;}
    function fb(){ try{var ta=document.createElement('textarea'); ta.value=txt; ta.style.position='fixed';ta.style.left='-9999px'; document.body.appendChild(ta); ta.select(); document.execCommand('copy'); document.body.removeChild(ta);}catch(e){} flashBtn(btn,true); try{stand.termBase.focus();}catch(e){} }
    try{ if(navigator.clipboard&&navigator.clipboard.writeText) navigator.clipboard.writeText(txt).then(function(){flashBtn(btn,true);try{stand.termBase.focus();}catch(e){}},fb); else fb(); }catch(e){fb();}
  }
  function flashBtn(btn,ok){ if(!btn) return; btn.classList.add(ok?'kbd-ok':'kbd-err'); setTimeout(function(){btn.classList.remove('kbd-ok','kbd-err');},500); }

  function bindKbd(){
    if(!stand.kbdEl||stand.kbdEl._bound) return;
    stand.kbdEl._bound=true;
    stand.kbdEl.addEventListener('mousedown',function(ev){ev.preventDefault();},{passive:false});
    stand.kbdEl.addEventListener('click',function(ev){
      var b=ev.target.closest('button[data-k]'); if(!b) return;
      ev.preventDefault(); sendSpecial(b.getAttribute('data-k'));
    });
    // Input data → current slot
    stand.termBase.onData(function(d){
      var slot=activeSlot(); if(!slot||!d) return;
      if(d.length>1||d.charCodeAt(0)===0x1b){ sendRaw(slot,d); return; }
      var ch=d.charCodeAt(0);
      if(stand.ctrl){
        if(ch>=97&&ch<=122){d=String.fromCharCode(ch-96); releaseSticky();}
        else if(ch>=65&&ch<=90){d=String.fromCharCode(ch-64); releaseSticky();}
        else if(ch===32){d='\x00'; releaseSticky();} else releaseSticky();
      }
      if(stand.alt&&d>=' '&&d<='~'){ d='\x1b'+d; releaseSticky(); }
      sendRaw(slot,d);
    });
    stand.termBase.onResize(function(){
      var slot=activeSlot(); if(slot) sendResize(slot);
    });
  }

  // ---------- Slot tabs UI ----------
  function renderSlots(){
    if(!stand.slotsBar) return;
    stand.slotsBar.innerHTML='';
    stand.slots.forEach(function(s, i){
      var b=document.createElement('button');
      b.className='slot-tab'+(i===stand.activeIdx?' active':'');
      var label = (s.name||('Shell '+s.slot));
      if (label.length>14) label = label.slice(0,12)+'…';
      b.innerHTML = (s.persist?'<span class="slot-badge">🔥</span>':'') + '<span>'+label+'</span>';
      b.title = s.name + (s.persist?' · 24/7':'') + (s._dead?' · stopped':'');
      b.addEventListener('click',function(ev){
        if (ev.shiftKey || ev.detail===3){
          // shift-click or triple-click: toggle 24/7
          togglePersist(s);
        } else {
          switchSlot(i);
        }
      });
      // Long-press on tab = rename / toggle 24/7 / close (prompt for simplicity)
      var lp=null, fired=false, start=null;
      b.addEventListener('touchstart',function(e){
        var p=e.touches[0]; start={x:p.clientX,y:p.clientY}; fired=false;
        lp=setTimeout(function(){ fired=true; slotMenu(s); if(navigator.vibrate)try{navigator.vibrate(20);}catch(_){} },500);
      },{passive:true});
      b.addEventListener('touchmove',function(e){ if(!start) return; var p=e.touches[0]; if(Math.abs(p.clientX-start.x)>10||Math.abs(p.clientY-start.y)>10){ if(lp){clearTimeout(lp);lp=null;} start=null; } },{passive:true});
      b.addEventListener('touchend',function(){ if(lp){clearTimeout(lp);lp=null;} start=null; },{passive:true});
      b.addEventListener('contextmenu',function(e){ e.preventDefault(); slotMenu(s); });
      stand.slotsBar.appendChild(b);
    });
    // Add "+" button
    var add=document.createElement('button');
    add.className='slot-tab add';
    add.textContent='＋ new';
    add.title='New shell slot';
    add.addEventListener('click',function(){ newSlot(); });
    stand.slotsBar.appendChild(add);
  }
  function slotMenu(slot){
    var actions = [];
    actions.push(slot.persist?'🔕 Stop 24/7':'🔥 Mark 24/7 (auto-restart)');
    actions.push('✏ Rename');
    if(!slot.persist) actions.push('✕ Close slot');
    actions.push('Cancel');
    var choice = prompt(actions.join('\n\n')+'\n\nType first word/number to pick (e.g. "🔥", "✏", "✕"):', slot.persist?'🔕':'🔥');
    if(!choice) return;
    choice=choice.trim();
    if(/🔥|24|persist|mark/i.test(choice)){ togglePersist(slot,true); }
    else if(/🔕|stop|unmark/i.test(choice)){ togglePersist(slot,false); }
    else if(/✏|rename|name/i.test(choice)){
      var nn=prompt('New name for this shell:', slot.name||'');
      if(nn&&nn.trim()){ slot.name=nn.trim().slice(0,30); renderSlots(); }
    }
    else if(/✕|close|delete|remove/i.test(choice)){ closeSlot(slot); }
  }
  function togglePersist(slot, on){
    var want = (typeof on==='boolean')?on:(!slot.persist);
    var tok=token(); if(!tok) return;
    // Build starter command if turning ON and no run.sh exists (best-effort)
    var cmd = '';
    if (want){
      cmd = prompt(
        '🔥 24/7 mode: this shell will stay alive, auto-restart on crash/close,\n'+
        'and relaunch after redeploys (bots run here).\n\n'+
        'Enter command to run on start (leave empty to keep previously saved one).\n'+
        'Example: cd ~/projects && python bot.py',
        ''
      );
      if (cmd===null) return;
    }
    fetch('/api/terminals/'+slot.id,{
      method:'PATCH',
      headers:{'Content-Type':'application/json','Authorization':'Bearer '+tok},
      body: JSON.stringify({persist:!!want, name:slot.name, cmd:cmd||''}),
    }).then(function(r){return r.json();}).then(function(j){
      slot.persist=!!j.persist;
      if (j.name) slot.name=j.name;
      renderSlots();
      // Reconnect so the new mode takes effect (boot command runs)
      if (want) connect(slot,{force:true});
    }).catch(function(){});
  }
  function closeSlot(slot){
    var i=stand.slots.indexOf(slot); if(i<0) return;
    if (stand.slots.length<=1) { newSlot(); }
    disconnect(slot);
    // Tell server
    var tok=token(); if(tok){
      fetch('/api/terminals/'+slot.id,{method:'DELETE',headers:{'Authorization':'Bearer '+tok}}).catch(function(){});
    }
    stand.slots.splice(i,1);
    if(stand.activeIdx>=stand.slots.length) stand.activeIdx=stand.slots.length-1;
    if(stand.activeIdx<0) stand.activeIdx=-1;
    if(stand.activeIdx>=0) switchSlot(stand.activeIdx);
    else {
      // show landing
      try{ stand.termBase.clear(); }catch(e){}
      if(stand.landingEl) stand.landingEl.style.display='grid';
    }
    renderSlots();
  }
  function newSlot(){
    if (stand.slots.length>=4) { alert('Max 4 slots (free tier)'); return; }
    var nextN = 1;
    var used={}; stand.slots.forEach(function(s){used[s.slot]=1;});
    while(used[nextN]) nextN++;
    var slot = {
      id:'s_'+Math.random().toString(36).slice(2,8),
      ticket:null, ws:null, open:true,
      slot: nextN, name: 'Shell '+nextN, persist:false,
      _outBuf:'', _outT:0, _ring:'', _dead:false, _connecting:false,
      _lastCols:0, _lastRows:0,
    };
    stand.slots.push(slot);
    switchSlot(stand.slots.length-1);
    renderSlots();
    if(stand.landingEl) stand.landingEl.style.display='none';
    connect(slot,{force:true});
  }
  function switchSlot(i){
    if(i<0||i>=stand.slots.length) return;
    stand.activeIdx=i; var slot=stand.slots[i]; slot.open=true;
    renderSlots();
    if(stand.landingEl) stand.landingEl.style.display='none';
    stand.bodyEl.parentElement.classList.add('wb-term-has-term');
    attachSlot(slot);
    if(!slot.ws && !slot._connecting) connect(slot,{force:true});
  }

  // ---------- Viewport / view lock ----------
  function fitAll(){
    var fs=fontSz();
    try{if(stand.termBase&&stand.termBase.options.fontSize!==fs) stand.termBase.options.fontSize=fs;}catch(e){}
    if(stand.termBase&&stand.bodyEl) safeFitTerm(stand.termBase, stand.bodyEl);
  }
  var _vpRaf=0,_vpLastKey='';
  function applyViewport(){
    _vpRaf=0;
    var standPage=_termPage||$('tab-term'), standWrap=_termStandalone||$('termStandalone');
    var vv=window.visualViewport;
    var isActive=!!(standPage&&standPage.classList.contains('active'));
    var kbdOpen=false, key='';
    if(isActive){
      var ih=window.innerHeight, topPx=0,leftPx=0,hPx=ih,wPx=window.innerWidth;
      if(vv){var vh=vv.height|0, vo=vv.offsetTop|0; topPx=vo; leftPx=vv.offsetLeft|0; hPx=Math.round(vh); wPx=Math.round(vv.width); kbdOpen=(ih-vh-vo)>120;}
      key=topPx+','+leftPx+','+wPx+','+hPx+','+(kbdOpen?1:0);
      if(key!==_vpLastKey||!standPage.dataset.vpInit){
        standPage.dataset.vpInit='1'; _vpLastKey=key;
        standPage.style.cssText='position:fixed;top:'+topPx+'px;left:'+leftPx+'px;right:0;width:'+wPx+'px;height:'+hPx+'px;min-height:'+hPx+'px;max-height:'+hPx+'px;overflow:hidden;';
        if(standWrap) standWrap.style.cssText='height:100%;min-height:0;max-height:100%;display:flex;flex-direction:column;overflow:hidden;';
        if(kbdOpen) document.body.classList.add('term-kbd-up'); else document.body.classList.remove('term-kbd-up');
      }
    } else {
      if(standPage&&standPage.dataset.vpInit){standPage.dataset.vpInit=''; _vpLastKey=''; standPage.style.cssText=''; if(standWrap) standWrap.style.cssText=''; document.body.classList.remove('term-kbd-up');}
    }
    fitAll();
    if(stand.termBase){try{stand.termBase.scrollToBottom&&stand.termBase.scrollToBottom();}catch(e){} }
  }
  function scheduleFit(){ if(!_vpRaf) _vpRaf=requestAnimationFrame(applyViewport); }

  window.addEventListener('resize',scheduleFit,{passive:true});
  window.addEventListener('orientationchange',scheduleFit);
  if(window.visualViewport){
    window.visualViewport.addEventListener('resize',scheduleFit);
    window.visualViewport.addEventListener('scroll',scheduleFit);
  }
  document.addEventListener('focusin',function(ev){
    if(stand.termBase&&(ev.target===stand.termBase.textarea||(stand.bodyEl&&stand.bodyEl.contains&&stand.bodyEl.contains(ev.target)))){
      scheduleFit(); setTimeout(scheduleFit,150); setTimeout(scheduleFit,400);
    }
  },true);
  document.addEventListener('focusout',function(){setTimeout(scheduleFit,150);});

  function hookTab(){
    if(typeof window.switchTab!=='function'){setTimeout(hookTab,50);return;}
    var orig=window.switchTab;
    window.switchTab=function(tabId){
      var isTerm=(tabId==='term');
      var wasTerm=(document.body.classList.contains('term-fullscreen'));
      var r=orig.apply(this,arguments);
      document.documentElement.classList.toggle('term-lock',isTerm);
      document.body.classList.toggle('term-lock',isTerm);
      document.body.classList.toggle('term-fullscreen',isTerm);
      // When entering the term tab (e.g. /terminal URL): auto-connect first slot
      if(isTerm && !wasTerm){
        setTimeout(function(){
          if(stand.hostEl) stand.hostEl.classList.add('wb-term-has-term');
          if(stand.slots.length===0){
            if(typeof newSlot==='function') newSlot();
          } else if(stand.activeIdx<0){
            if(typeof switchSlot==='function') switchSlot(0);
            else scheduleFit();
          } else { scheduleFit(); }
        },80);
      }
      // When leaving term tab, release locks
      if(!isTerm){
        document.documentElement.classList.remove('term-lock');
        document.body.classList.remove('term-lock');
        document.body.classList.remove('term-fullscreen');
      }
      scheduleFit(); setTimeout(scheduleFit,80); setTimeout(scheduleFit,350);
      return r;
    };
  }
  hookTab();

  function _cacheDom(){
    _termPage=$('tab-term'); _termStandalone=$('termStandalone'); _termCtx=$('termCtxMenu');
  }
  if(document.readyState==='loading'){
    document.addEventListener('DOMContentLoaded',function(){ _cacheDom(); scheduleFit(); setTimeout(scheduleFit,500); });
  } else { _cacheDom(); scheduleFit(); setTimeout(scheduleFit,500); }

  function boot(){
    initCtxMenu();
    if(!$('termStandalone')) return;
    stand.hostEl = $('termStandalone');
    stand.bodyEl = $('standBody');
    stand.kbdEl  = $('standKbd');
    stand.landingEl = $('standLanding');
    stand.slotsBar = $('standSlots');

    // Build the ONE shared xterm instance. The library is fetched on demand,
    // so this waits for it rather than assuming a global is already there.
    return _ensureXterm().then(function(ok){
      if(!ok){
        if (stand.landingEl) stand.landingEl.textContent =
          'Terminal could not load — check your connection and reopen.';
        return;
      }
      stand.termBase = makeXterm();
      if(!stand.termBase) return;
      bindLongPress(stand.hostEl);
      bindKbd();
      _finishStandInit();
    });
  }

  function _finishStandInit(){

    // Connect button on landing
    var cbtn=$('standConnect');
    if(cbtn) cbtn.addEventListener('click',function(){
      if(stand.slots.length===0) newSlot();
      else switchSlot(stand.activeIdx>=0?stand.activeIdx:0);
    });

    // Exit FAB
    var eb=$('termExit');
    if(eb) eb.addEventListener('click',function(e){
      e.preventDefault();
      document.body.classList.remove('term-fullscreen');
      document.documentElement.classList.remove('term-lock');
      document.body.classList.remove('term-lock');
      if(typeof window.switchTab==='function') window.switchTab('overview');
    });

    // Tab activation
    document.querySelectorAll('.dash-tab[data-tab="term"], .bn-item[data-tab="term"]').forEach(function(b){
      b.addEventListener('click',function(){
        document.body.classList.add('term-fullscreen');
        setTimeout(function(){
          stand.hostEl.classList.add('wb-term-has-term');
          if(stand.slots.length===0) newSlot();
          else if(stand.activeIdx<0) switchSlot(0);
          else { scheduleFit(); }
        },120);
      });
    });
    document.querySelectorAll('.dash-tab, .bn-item').forEach(function(b){
      if(b.getAttribute('data-tab')==='term') return;
      b.addEventListener('click',function(){
        document.body.classList.remove('term-fullscreen');
        document.documentElement.classList.remove('term-lock');
        document.body.classList.remove('term-lock');
      });
    });

    // Load existing sessions list from server (so 24/7 slots reappear)
    var tok=token();
    if(tok){
      fetch('/api/terminals',{headers:{'Authorization':'Bearer '+tok}}).then(function(r){return r.json();}).then(function(j){
        var ts=(j&&j.terminals)||[];
        // On boot start empty; if server reports alive sessions, offer them via "reconnect" slot
        // (we'll just open slot 1; server will reuse the existing PTY for slot=1).
        if(ts.length===0) return;
        // First slot: reuse whatever the server has for slot 1 (legacy)
      }).catch(function(){});
    }
  }

  if(document.readyState==='loading') document.addEventListener('DOMContentLoaded',boot);
  else setTimeout(boot,0);
  window._wbTerm={instances:instances,scheduleFit:scheduleFit};
})();
