'use strict';
const $ = id => document.getElementById(id);
let token='', session='', state=null, connected=false, busy=false, heartbeating=false, noticeTimer;
const names={rover:'RoverC',crazyflie:'Crazyflie',jetson:'Jetson'};
function element(tag,text='',cls='') {const node=document.createElement(tag);node.textContent=text;if(cls)node.className=cls;return node;}
function notice(message) {
  clearTimeout(noticeTimer); $('notice').textContent=message; $('notice').hidden=!message;
  if(message) noticeTimer=setTimeout(()=>{$('notice').hidden=true;},6000);
}
async function api(path,body) {
  const response=await fetch('/api/'+path,{
    method:body===undefined?'GET':'POST',cache:'no-store',
    headers:{Authorization:'Bearer '+token,'Content-Type':'application/json'},
    body:body===undefined?undefined:JSON.stringify({...body,session}),signal:AbortSignal.timeout(1200)
  });
  const result=await response.json();
  if(!response.ok){const error=new Error(result.error||'Connection failed');error.status=response.status;throw error;}
  return result;
}
function actionText(command) {
  const p=command.params;
  if(command.action==='pulse')return ({w:'Forward',s:'Backward',a:'Left',d:'Right',z:'Rotate left',c:'Rotate right'})[p.direction]+' · power '+p.power+' · 250 ms';
  if(command.action==='takeoff')return 'Take off · '+p.height+' m';
  return 'Move · '+[p.x,p.y,p.z].join(', ')+' m';
}
function render() {
  const focus=document.activeElement?.dataset, focusedCommand=focus?.command, focusedOperation=focus?.operation;
  const owns=connected&&!!session,enabled=owns&&!state?.paused;
  $('connection').textContent=connected?'Connected':'Offline';$('connection').classList.toggle('online',connected);
  $('claim').disabled=!connected||!!session||!!state?.operator_active;
  $('resume').disabled=!owns||!state?.paused;$('pause').disabled=!connected;$('stop').disabled=!token;$('propose').disabled=!enabled;
  $('ownership').textContent=!connected?'—':owns?'You':state?.operator_active?'In use':'No operator';
  $('mission-state').textContent=!connected?'Disconnected':state.paused?'Paused':'Active';
  $('mission-state').title=connected?state.reason:'Coordinator offline';
  if(!state)return;
  const modes=[...new Set(Object.values(state.nodes).filter(n=>n.online).map(n=>n.mode))];
  $('mode').textContent=!modes.length?'NO DEVICES':modes.length>1?'MIXED':modes[0];
  $('nodes').replaceChildren();
  for(const [id,n] of Object.entries(state.nodes)){
    const card=element('article','','node'),t=n.telemetry,ready=connected&&n.online&&t.ready;
    const top=element('div','','node-top');top.append(element('span','','dot'+(ready?' live':'')),element('span',names[id],'node-name'),element('span',!connected||!n.online?'Offline':t.ready?'Ready':'Not ready','node-health'+(ready?' ready':'')));
    const meta=element('div','','node-meta');meta.append(element('span',n.mode||'—','node-mode'));
    if(t.battery_v!=null)meta.append(element('span',Number(t.battery_v).toFixed(2)+' V'));
    if(id==='crazyflie'&&Array.isArray(t.position_m))meta.append(element('span',t.position_m.map(v=>Number(v).toFixed(1)).join(' / ')+' m'));
    card.append(top,meta);if(t.agent_error)card.append(element('p',t.agent_error,'node-error'));$('nodes').append(card);
  }
  const commands=state.commands.filter(c=>['pending','approved','dispatched','unconfirmed','failed'].includes(c.status)).slice(0,5);
  $('commands').replaceChildren();
  if(!commands.length)$('commands').append(element('p','No pending actions','empty'));
  for(const command of commands){
    const card=element('article','','command');card.append(element('h3',names[command.node]),element('p',actionText(command)),element('span',command.status+(command.status==='pending'?' · '+Math.ceil(command.remaining_s)+'s':''),'status'));
    if(command.result){const detail=element('p',command.result);card.append(detail);}
    if(command.status==='pending'){
      const buttons=element('div','','buttons');
      for(const operation of ['approve','reject']){
        const button=element('button',operation==='approve'?'Approve':'Reject',operation==='approve'?'primary':'');button.disabled=!enabled;
        button.dataset.command=command.id;button.dataset.operation=operation;
        button.addEventListener('click',()=>perform(operation,{id:command.id}));buttons.append(button);
      }card.append(buttons);
    }$('commands').append(card);
  }
  if(focusedCommand){const target=[...$('commands').querySelectorAll('button')].find(b=>b.dataset.command===focusedCommand&&b.dataset.operation===focusedOperation);if(target&&!target.disabled)target.focus({preventScroll:true});}
  $('events').replaceChildren();
  for(const event of state.events.slice(0,8)){const item=element('li');item.append(element('time',event.time+' UTC'),element('span',event.message));$('events').append(item);}
  const jetson=state.nodes.jetson, detections=connected&&jetson.online&&jetson.telemetry.ready?(jetson.telemetry.observation?.detections||[]):[];
  $('detections').replaceChildren();
  if(Array.isArray(detections))for(const detection of detections.slice(0,4)){
    if(typeof detection?.label!=='string')continue;
    const confidence=typeof detection.confidence==='number'&&Number.isFinite(detection.confidence)?' '+Math.round(Math.max(0,Math.min(1,detection.confidence))*100)+'%':'';
    $('detections').append(element('span',detection.label.slice(0,40)+confidence));
  }
}
async function poll(){
  if(!token||busy)return;busy=true;
  try{const next=await api('state');if(state&&state.instance!==next.instance){session='';notice('Coordinator restarted');}state=next;connected=true;}
  catch(error){connected=false;if(error.status===401){token='';session='';$('login').hidden=false;}notice(error.message);}
  finally{busy=false;render();}
}
async function heartbeat(){
  if(!token||!session||heartbeating||document.hidden)return;heartbeating=true;
  try{await api('heartbeat',{});}catch(error){session='';notice('Control lost');render();}finally{heartbeating=false;}
}
async function perform(operation,body={}){
  try{const result=await api(operation,body);if(operation==='claim'){session=result.session;await heartbeat();}if(operation==='stop')notice('Stop + land requested');await poll();}
  catch(error){notice(error.message);}
}
$('login-form').addEventListener('submit',async event=>{event.preventDefault();token=$('token').value.trim();session='';await poll();if(connected){$('token').value='';$('login').hidden=true;notice('');}});
for(const operation of ['claim','resume','pause','stop'])$(operation).addEventListener('click',()=>perform(operation));
function actionFields(){
  const drone=$('device').value==='crazyflie',move=$('action').value==='move';$('rover-fields').hidden=drone;$('flight-fields').hidden=!drone;$('x-label').hidden=!move;$('y-label').hidden=!move;
  for(const input of $('rover-fields').querySelectorAll('input,select'))input.disabled=drone;
  $('z').disabled=!drone;$('x').disabled=!drone||!move;$('y').disabled=!drone||!move;
}
$('device').addEventListener('change',()=>{const options=$('device').value==='rover'?[['pulse','Pulse · 250 ms']]:[['takeoff','Take off'],['move','Move']];$('action').replaceChildren(...options.map(([value,label])=>{const option=element('option',label);option.value=value;return option;}));actionFields();});
$('action').addEventListener('change',actionFields);actionFields();
$('action-form').addEventListener('submit',event=>{event.preventDefault();const node=$('device').value,action=$('action').value;const params=node==='rover'?{direction:$('direction').value,power:Number($('power').value)}:action==='takeoff'?{height:Number($('z').value)}:{x:Number($('x').value),y:Number($('y').value),z:Number($('z').value)};perform('propose',{node,action,params});});
$('focus-toggle').addEventListener('click',()=>{const focus=document.body.classList.toggle('focus-mode');$('focus-toggle').textContent=focus?'Show panels':'Hide panels';$('focus-toggle').setAttribute('aria-pressed',String(focus));});
$('fullscreen').addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{notice('Fullscreen unavailable');}});
 document.addEventListener('fullscreenchange',()=>{$('fullscreen').textContent=document.fullscreenElement?'Exit fullscreen':'Fullscreen';});
document.addEventListener('visibilitychange',()=>{if(document.hidden&&session)perform('pause');});
setInterval(poll,700);setInterval(heartbeat,650);
