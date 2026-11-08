'use strict';
(() => {
  if(new URLSearchParams(location.search).has('embedded'))document.body.classList.add('embedded');
  if(new URLSearchParams(location.search).has('mission')){document.body.classList.add('mission-only');const toggle=document.getElementById('mission-graph-toggle');if(toggle){toggle.hidden=false;toggle.addEventListener('click',()=>{const shown=document.body.classList.toggle('show-mission-graph');toggle.textContent=shown?'Hide graph':'Show graph';toggle.setAttribute('aria-pressed',String(shown));});}}
  if(new URLSearchParams(location.search).has('decisions')){document.body.classList.add('decisions-mode');const safety=document.createElement('section');safety.className='panel decision-safety';const title=document.createElement('h2');title.textContent='Safety controls';safety.append(title,document.getElementById('pause'),document.getElementById('stop'));document.querySelector('.left-rail').prepend(safety);}
  window.addEventListener('message',event=>{
    if(event.origin!==location.origin||event.source!==parent||event.data?.type!=='workspace-auth'||typeof event.data.token!=='string')return;
    const field=document.getElementById('trace-token')||document.getElementById('token');
    if(field){field.value=event.data.token;field.form.requestSubmit();}
  });
  if(parent!==window)parent.postMessage({type:'workspace-ready'},location.origin);
})();

// Pane preferences contain layout percentages only, never credentials or feed data.
(() => {
  const storageKey='team15.pane-layout.v1:'+location.pathname+(new URLSearchParams(location.search).has('mission')?':mission':''),handles=[...document.querySelectorAll('[data-resize-property]')];
  let saved={};try{const value=JSON.parse(localStorage.getItem(storageKey)||'{}');if(value&&typeof value==='object'&&!Array.isArray(value))saved=value;}catch{}
  const resets=[];
  for(const handle of handles){
    const target=document.getElementById(handle.dataset.resizeTarget);if(!target)continue;
    const property=handle.dataset.resizeProperty,axis=handle.dataset.resizeAxis,min=Number(handle.dataset.resizeMin||15),max=Number(handle.dataset.resizeMax||85),fallback=Number(handle.dataset.resizeDefault||50);
    handle.setAttribute('aria-controls',target.id);
    let value=fallback,drag=null;
    function apply(next,persist=false){value=Math.max(min,Math.min(max,Number.isFinite(next)?next:fallback));target.style.setProperty(property,value+'%');handle.setAttribute('aria-valuemin',min);handle.setAttribute('aria-valuemax',max);handle.setAttribute('aria-valuenow',Math.round(value));handle.setAttribute('aria-valuetext',Math.round(value)+' percent');if(persist){saved[property]=value;try{localStorage.setItem(storageKey,JSON.stringify(saved));}catch{}}}
    function finish(event){if(!drag||event&&event.pointerId!==drag.id)return;drag=null;document.body.classList.remove('pane-resizing');apply(value,true);}
    apply(typeof saved[property]==='number'?saved[property]:fallback);
    handle.title='Drag to resize · arrow keys adjust · double-click resets';
    handle.addEventListener('pointerdown',event=>{if(event.button!==0)return;const box=target.getBoundingClientRect();drag={id:event.pointerId,start:axis==='x'?event.clientX:event.clientY,value,size:axis==='x'?box.width:box.height};if(!drag.size){drag=null;return;}handle.setPointerCapture(event.pointerId);document.body.classList.add('pane-resizing');handle.focus();event.preventDefault();});
    handle.addEventListener('pointermove',event=>{if(!drag||drag.id!==event.pointerId)return;apply(drag.value+((axis==='x'?event.clientX:event.clientY)-drag.start)/drag.size*100);});
    handle.addEventListener('pointerup',finish);handle.addEventListener('pointercancel',finish);handle.addEventListener('lostpointercapture',finish);
    handle.addEventListener('keydown',event=>{const negative=axis==='x'?'ArrowLeft':'ArrowUp',positive=axis==='x'?'ArrowRight':'ArrowDown';if(![negative,positive,'Home','End'].includes(event.key))return;event.preventDefault();apply(event.key==='Home'?min:event.key==='End'?max:value+(event.key===positive?1:-1)*(event.shiftKey?10:2),true);});
    const reset=()=>apply(fallback,true);handle.addEventListener('dblclick',reset);resets.push(reset);
  }
  function resetAll(){resets.forEach(reset=>reset());for(const panel of document.querySelectorAll('.trace-sidebar,.vision-sidebar,.side,.left-rail>.panel,.right-rail>.panel,.view-card,.animation-script')){panel.style.removeProperty('width');panel.style.removeProperty('height');}}
  window.addEventListener('reset-pane-layout',resetAll);
  window.addEventListener('message',event=>{if(event.origin===location.origin&&event.source===parent&&event.data?.type==='workspace-reset-layout')resetAll();});
})();
