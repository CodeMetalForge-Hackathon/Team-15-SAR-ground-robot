'use strict';
const byId=id=>document.getElementById(id),ns='http://www.w3.org/2000/svg';
let viewerToken='',feed=null,selected='',knownTarget=null,optionSignature='',pollBusy=false,targetChosen=false;
let cameraMode=false,cameraSource='host',stream=null,frameURL='',cameraReady=false,frameBusy=false;
let originPin=null,phonePin=null,pinMode='origin',lastCount=null,noticeTimer,cameraRevision=0;
const cameraPublisher=Array.from(crypto.getRandomValues(new Uint8Array(16)),b=>b.toString(16).padStart(2,'0')).join(''),shareCanvas=document.createElement('canvas');
let publishBusy=false;
const statusCache=new Map();
const html=(tag,text='',cls='')=>{const e=document.createElement(tag);e.textContent=text;if(cls)e.className=cls;return e;};
const svg=(tag,attrs={})=>{const e=document.createElementNS(ns,tag);for(const [key,value]of Object.entries(attrs))e.setAttribute(key,String(value));return e;};
function message(text){clearTimeout(noticeTimer);byId('trace-notice').textContent=text;byId('trace-notice').hidden=!text;if(text)noticeTimer=setTimeout(()=>byId('trace-notice').hidden=true,7000);}
function signals(){const enrolled=Array.isArray(feed?.trace_signals)?feed.trace_signals:[],nearby=Array.isArray(feed?.discovery?.signals)?feed.discovery.signals:[];return [...enrolled,...nearby].filter(s=>s&&typeof s==='object');}
function currentTarget(){return signals().find(s=>s.id===selected)||null;}
function scanning(){return feed?.connected&&feed.discovery?.status==='scanning';}
function targetFresh(){const target=currentTarget();return !!target&&(!target.alias||(target.protocol_version===2?feed?.sos?.status:feed?.beacons?.status)==='verifying')&&scanning()&&Number.isFinite(target.age_s)&&target.age_s<=5&&!target.stale;}
async function request(path){const r=await fetch('/api/'+path,{headers:{Authorization:'Bearer '+viewerToken},cache:'no-store',signal:AbortSignal.timeout(1500)});if(!r.ok){const error=new Error('HTTP '+r.status);error.status=r.status;throw error;}return r;}
function targetOptions(){
  if(document.activeElement===byId('trace-target'))return;
  const enrolled=Array.isArray(feed?.trace_signals)?feed.trace_signals:[];if(!targetChosen&&!selected&&enrolled.length===1){selected=enrolled[0].id;lastCount=null;}
  const available=enrolled.length?[...enrolled,...signals().filter(s=>s.id===selected&&!s.alias)]:signals();
  const list=available.sort((a,b)=>String(a.label).localeCompare(String(b.label),undefined,{numeric:true})),signature=JSON.stringify(list.map(s=>[s.id,s.label,s.name]));
  if(signature===optionSignature)return;optionSignature=signature;
  const options=[html('option','Select a signal')];options[0].value='';
  for(const signal of list){const option=html('option',String(signal.label||'Signal')+(signal.name?' · '+signal.name:''));option.value=signal.id;options.push(option);}
  if(selected&&!list.some(s=>s.id===selected)){const option=html('option',(knownTarget?.label||'Selected signal')+' · lost');option.value=selected;options.push(option);}
  byId('trace-target').replaceChildren(...options);byId('trace-target').value=selected;
}
function chart(target){
  const history=Array.isArray(target?.history)?target.history.filter(p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite)&&p[0]>=0&&p[0]<=30):[];
  const values=history.map(p=>p[1]),full=byId('trace-scale').value==='full';
  let low=-110,high=-20;
  if(!full&&values.length){low=Math.floor((Math.min(...values)-3)/5)*5;high=Math.ceil((Math.max(...values)+3)/5)*5;if(high-low<10){low-=5;high+=5;}}
  const box=byId('trace-history'),width=Math.max(320,box.clientWidth),height=Math.max(155,box.clientHeight),left=38,right=width-12,top=14,bottom=height-24;
  const graph=svg('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':`Selected beacon RSSI over 30 seconds, ${low} to ${high} dBm`});
  const step=full?15:Math.max(5,Math.ceil((high-low)/30)*5);
  for(let value=low;value<=high;value+=step){const y=bottom-(value-low)/(high-low)*(bottom-top);graph.append(svg('line',{x1:left,y1:y,x2:right,y2:y,stroke:'var(--border-tactical)','stroke-width':.7}));const label=svg('text',{x:left-9,y:y+3,'text-anchor':'end',fill:'var(--surface-olive)','font-size':10});label.textContent=value;graph.append(label);}
  for(const age of [30,20,10,0]){const x=left+(1-age/30)*(right-left);graph.append(svg('line',{x1:x,y1:top,x2:x,y2:bottom,stroke:'var(--border-tactical)','stroke-width':.5,'stroke-dasharray':'2 5'}));const label=svg('text',{x,y:height-5,'text-anchor':age===0?'end':age===30?'start':'middle',fill:'var(--surface-olive)','font-size':9});label.textContent=age?`−${age}s`:'now';graph.append(label);}
  const project=([age,rssi])=>[left+(1-age/30)*(right-left),bottom-(Math.max(low,Math.min(high,rssi))-low)/(high-low)*(bottom-top)];
  for(let i=1;i<history.length;i++){if(Math.abs(history[i-1][0]-history[i][0])>3)continue;const [x1,y1]=project(history[i-1]),[x2,y2]=project(history[i]);graph.append(svg('line',{x1,y1,x2,y2,stroke:'var(--phone-blue)','stroke-width':2,'stroke-linecap':'round'}));}
  for(const point of history){const [cx,cy]=project(point);graph.append(svg('circle',{cx,cy,r:1.6,fill:'var(--phone-blue)'}));}
  graph.style.opacity=targetFresh()?'1':'.4';box.replaceChildren(graph);
  byId('chart-empty').hidden=!!history.length;
  byId('chart-empty').textContent=!selected?'Connect and select a beacon to see live RSSI.':!targetFresh()?'Waiting for fresh advertisements…':'Collecting signal history…';
  byId('chart-rssi').replaceChildren(document.createTextNode(Number.isFinite(target?.rssi)?String(target.rssi):'—'),html('small',' dBm'));
  byId('chart-range').textContent=values.length?`Low ${Math.min(...values)} · High ${Math.max(...values)} · Variation ${Math.max(...values)-Math.min(...values)} dB`:'Select a beacon to see signal variation';
  byId('chart-scale-note').textContent=`${full?'Full':'Auto'} scale · ${step} dB grid · ${low} to ${high} dBm`;
}
byId('trace-scale').addEventListener('change',()=>chart(currentTarget()));

function contentRect(){
  const stage=byId('trace-stage'),width=stage.clientWidth,height=stage.clientHeight;
  const media=cameraSource==='device'?byId('trace-device-camera'):byId('trace-camera-frame');
  const iw=media.videoWidth||media.naturalWidth||width,ih=media.videoHeight||media.naturalHeight||height,scale=Math.min(width/iw,height/ih);
  return {width,height,x:(width-iw*scale)/2,y:(height-ih*scale)/2,w:iw*scale,h:ih*scale};
}
function draw(pulse=false){
  const stage=byId('trace-stage'),overlay=byId('trace-overlay'),rect=contentRect();
  if(!rect.width||!rect.height)return;overlay.setAttribute('viewBox',`0 0 ${rect.width} ${rect.height}`);overlay.replaceChildren();stage.querySelectorAll('.trace-marker-label').forEach(n=>n.remove());
  if(!cameraMode)return;
  const project=pin=>cameraMode?[rect.x+pin.x*rect.w,rect.y+pin.y*rect.h]:[pin.x*rect.width,pin.y*rect.height];
  const origin=cameraMode?originPin:{x:.22,y:.56},phone=cameraMode?phonePin:{x:.78,y:.56};
  const target=currentTarget(),fresh=targetFresh(),showPhone=!!selected&&!!phone;
  if(origin&&showPhone){
    const [x1,y1]=project(phone),[x2,y2]=project(origin);overlay.append(svg('line',{x1,y1,x2,y2,stroke:'var(--phone-blue)','stroke-width':2,'stroke-dasharray':'5 6',opacity:fresh?.65:.25}));
    if(pulse&&fresh){const dot=svg('circle',{r:4,fill:'var(--phone-blue)'});dot.append(svg('animate',{attributeName:'cx',from:x1,to:x2,dur:'.6s',fill:'freeze'}),svg('animate',{attributeName:'cy',from:y1,to:y2,dur:'.6s',fill:'freeze'}),svg('animate',{attributeName:'opacity',from:1,to:0,dur:'.6s',fill:'freeze'}));overlay.append(dot);}
  }
  function marker(pin,color,label,filled){
    const [x,y]=project(pin);overlay.append(svg('circle',{cx:x,cy:y,r:20,fill:'none',stroke:color,'stroke-width':1,opacity:.25}),svg('circle',{cx:x,cy:y,r:9,fill:filled?color:'var(--bg-canvas)',stroke:color,'stroke-width':3}));
    const text=html('div',label,'trace-marker-label');text.style.left=x+'px';text.style.top=Math.max(20,y-42)+'px';text.style.color=color;stage.append(text);
  }
  if(origin)marker(origin,'var(--origin-red)',cameraMode?'ESP32 origin · manual':'ESP32 · origin',scanning());
  if(showPhone)marker(phone,'var(--phone-blue)',(cameraMode?'Phone mark · manual':knownTarget?.label||'Selected beacon')+(Number.isFinite(target?.rssi)?' · '+target.rssi+' dBm':''),fresh);
  byId('trace-stage-empty').hidden=!!selected&&(!cameraMode||!!phonePin)||cameraMode&&!cameraReady;
  byId('trace-stage-empty').textContent=!selected?'Choose your phone’s beacon':'Tap the phone to place its marker';
}
function render(pulse=false){
  byId('trace-copy-token').disabled=!viewerToken;const data=feed?.discovery;targetOptions();const target=currentTarget();if(target)knownTarget=target;
  byId('trace-source').textContent=data?.source||'OFFLINE';
  byId('trace-receiver-status').textContent=scanning()?'Scanning':'Offline';
  byId('trace-receiver-detail').textContent=scanning()?'Passive BLE receiver':data?.detail||'Receiver unavailable';
  byId('trace-active').textContent=scanning()?data.active:'—';byId('trace-packets').textContent=data?Number(data.packets||0).toLocaleString():'—';
  byId('trace-target-label').textContent=knownTarget?.label||'No target';
  byId('trace-target-status').textContent=!selected?'—':targetFresh()?'Detected':'Not heard';
  byId('trace-rssi').replaceChildren(document.createTextNode(Number.isFinite(target?.rssi)?String(target.rssi):'—'),html('small',' dBm'));
  byId('trace-age').textContent=target?'Last advertisement '+Number(target.age_s).toFixed(1)+'s ago · '+Number(target.count||0).toLocaleString()+' total':selected?'Selected beacon unavailable':'No selected beacon';
  const identity=target||knownTarget;byId('trace-identity').textContent=identity?.alias?identity.mode_label+' · ALIAS '+identity.alias+' · RF ACTIVITY': 'UNVERIFIED · OPERATOR-SELECTED SIGNAL';
  byId('trace-note').textContent=cameraMode?'Markers are placed by you. No object detection or Bluetooth-to-camera localization.':knownTarget?.alias?'RSSI follows repeated packets. Fresh authentication is tracked separately; no distance or bearing.':'Live RSSI only · no position or bearing.';
  byId('trace-mode').textContent=cameraMode?'Manual overlay · no vision or localization':'Schematic link · no position or bearing';
  const verified=(knownTarget?.protocol_version===2?feed?.sos:feed?.beacons)?.sightings?.find(s=>s.alias===knownTarget?.alias);byId('trace-auth-age').hidden=!verified;byId('trace-auth-age').textContent=verified?'Fresh token '+verified.last_verified_age_s+'s ago · '+verified.verified_tokens+' verified tokens':'';
  for(const [id,online,text]of [
    ['link-session',!!feed,feed?'Dashboard · connected':'Dashboard · disconnected'],
    ['link-receiver',scanning(),scanning()?'ESP32 · scanning':'ESP32 · offline'],
    ['link-beacon',targetFresh(),targetFresh()?(target?.label||'Beacon')+' · heard':selected?'Beacon · not heard':'Beacon · waiting']]){byId(id).textContent=text;byId(id).classList.toggle('online',!!online);}
  renderSOS();chart(target);draw(pulse);
}
function renderSOS(){
  const banner=byId('trace-sos'),alias=knownTarget?.alias;
  banner.hidden=!alias;banner.className='sos-banner';if(!alias)return;
  const latest=feed?.sos?.sightings?.find(s=>s.alias===alias);
  if(latest)statusCache.set(alias,{...latest,received:performance.now()});
  const status=statusCache.get(alias);
  if(!status){banner.textContent=feed?.sos?.status==='off'?'SOS verification off':'SOS status unavailable · legacy tag';return;}
  const fresh=!!latest?.status_fresh&&scanning()&&feed?.sos?.status==='verifying';
  const age=Math.max(0,status.last_verified_age_s+(performance.now()-status.received)/1000);
  if(status.sos){banner.classList.add('sos-active');banner.textContent=(fresh?'SOS ACTIVE':'SOS · LAST KNOWN')+' · '+age.toFixed(0)+'s';}
  else{if(fresh)banner.classList.add('sos-normal');banner.textContent=fresh?'Normal · signed status':'Status unknown · last Normal';}
}
async function poll(){
  if(!viewerToken||pollBusy)return;pollBusy=true;
  try{const response=await request('bluetooth');feed=await response.json();const count=currentTarget()?.count,pulse=selected&&lastCount!==null&&count!==undefined&&count>lastCount;lastCount=count??null;render(pulse);}
  catch(error){feed=null;render();if(error.status===401){viewerToken='';byId('trace-login').hidden=false;message('Viewer token required');}}
  finally{pollBusy=false;}
}
byId('trace-login-form').addEventListener('submit',async event=>{event.preventDefault();viewerToken=byId('trace-token').value.trim();await poll();if(feed){byId('trace-token').value='';byId('trace-login').hidden=true;window.scrollTo(0,0);}});
byId('trace-target').addEventListener('change',()=>{selected=byId('trace-target').value;targetChosen=true;knownTarget=null;lastCount=null;render();});
function pinButtons(){byId('pin-origin').classList.toggle('active',pinMode==='origin');byId('pin-phone').classList.toggle('active',pinMode==='phone');}
function stopDevice(){if(stream)stream.getTracks().forEach(t=>t.stop());stream=null;byId('trace-device-camera').srcObject=null;byId('trace-device-camera').hidden=true;byId('device-camera').textContent='Share this device’s camera';}
function setView(camera){
  cameraRevision++;cameraMode=camera;byId('trace-stage').classList.toggle('camera-mode',camera);byId('trace-placement').hidden=!camera;
  byId('signal-view').setAttribute('aria-pressed',String(!camera));byId('overlay-view').setAttribute('aria-pressed',String(camera));
  if(!camera){stopDevice();cameraSource='host';originPin=phonePin=null;cameraReady=false;byId('trace-camera-frame').hidden=true;byId('trace-camera-empty').hidden=true;byId('trace-camera-status').textContent='Camera off · no vision';}
  else if(cameraSource==='host')byId('trace-camera-empty').hidden=cameraReady;
  pinButtons();render();
}
byId('signal-view').addEventListener('click',()=>setView(false));byId('overlay-view').addEventListener('click',()=>setView(true));
byId('pin-origin').addEventListener('click',()=>{pinMode='origin';pinButtons();});byId('pin-phone').addEventListener('click',()=>{pinMode='phone';pinButtons();});
byId('trace-stage').addEventListener('pointerdown',event=>{
  if(!cameraMode||!cameraReady||event.target.closest('button'))return;
  const bounds=byId('trace-stage').getBoundingClientRect(),r=contentRect();const x=(event.clientX-bounds.left-r.x)/r.w,y=(event.clientY-bounds.top-r.y)/r.h;
  if(x<0||x>1||y<0||y>1)return;
  if(pinMode==='origin'){originPin={x,y};pinMode='phone';}else{if(!selected){message('Select your beacon first');return;}phonePin={x,y};}
  pinButtons();draw();
});
byId('device-camera').addEventListener('click',async()=>{
  if(stream){stopDevice();cameraSource='host';cameraReady=false;return;}
  if(!navigator.mediaDevices?.getUserMedia){message('Device camera needs HTTPS or localhost. Use the host camera on a LAN viewer.');return;}
  const revision=++cameraRevision;
  try{const captured=await navigator.mediaDevices.getUserMedia({video:{facingMode:{ideal:'environment'}},audio:false});if(revision!==cameraRevision||!cameraMode){captured.getTracks().forEach(t=>t.stop());return;}stream=captured;cameraSource='device';originPin=phonePin=null;
    const video=byId('trace-device-camera');video.srcObject=stream;video.hidden=false;byId('trace-camera-frame').hidden=true;byId('trace-camera-empty').hidden=true;byId('device-camera').textContent='Stop device camera';
    video.onloadedmetadata=()=>{cameraReady=true;draw();};byId('trace-camera-status').textContent='Sharing device camera · no vision';
    stream.getVideoTracks()[0].addEventListener('ended',()=>{stopDevice();cameraReady=false;cameraSource='host';});
  }catch(error){message('Camera unavailable: '+error.message);}
});
byId('host-camera').addEventListener('click',()=>{cameraRevision++;stopDevice();cameraSource='host';cameraReady=false;originPin=phonePin=null;});
async function pollCamera(){
  if(!cameraMode||cameraSource!=='host'||!viewerToken||frameBusy)return;frameBusy=true;
  try{const response=await request('camera/frame'),blob=await response.blob();if(!cameraMode||cameraSource!=='host')return;const next=URL.createObjectURL(blob);byId('trace-camera-frame').src=next;if(frameURL)URL.revokeObjectURL(frameURL);frameURL=next;
    byId('trace-camera-frame').hidden=false;byId('trace-camera-empty').hidden=true;cameraReady=true;byId('trace-camera-status').textContent=(response.headers.get('X-Camera-Source')||'Host camera')+' · no vision';draw();
  }catch{if(!cameraMode||cameraSource!=='host')return;byId('trace-camera-frame').hidden=true;byId('trace-camera-empty').hidden=false;byId('trace-camera-empty').textContent='Host camera offline';byId('trace-camera-status').textContent='Host camera offline · no vision';cameraReady=false;draw();}
  finally{frameBusy=false;}
}
byId('trace-camera-frame').addEventListener('load',()=>{if(cameraMode&&cameraSource==='host')draw();});
async function publishCamera(){
  const video=byId('trace-device-camera');
  if(publishBusy||!viewerToken||!stream||cameraSource!=='device'||!cameraMode||!video.videoWidth)return;
  publishBusy=true;
  try{
    shareCanvas.width=Math.min(960,video.videoWidth);shareCanvas.height=Math.round(shareCanvas.width*video.videoHeight/video.videoWidth);
    shareCanvas.getContext('2d').drawImage(video,0,0,shareCanvas.width,shareCanvas.height);
    const frame=await new Promise(resolve=>shareCanvas.toBlob(resolve,'image/jpeg',.75));
    if(!frame||!stream||!cameraMode)return;
    const response=await fetch('/api/camera/publish',{method:'POST',headers:{Authorization:'Bearer '+viewerToken,'Content-Type':'image/jpeg','X-Camera-Publisher':cameraPublisher},body:frame,signal:AbortSignal.timeout(1500)});
    if(!response.ok){const error=await response.json();throw new Error(error.error||'Camera sharing failed');}
    byId('trace-camera-status').textContent='Sharing camera to this local server · no vision';
  }catch(error){byId('trace-camera-status').textContent='Camera sharing failed: '+error.message;}
  finally{publishBusy=false;}
}
byId('trace-copy-token').addEventListener('click',async()=>{try{await navigator.clipboard.writeText(viewerToken);message('Viewer token copied. Paste it into the other device’s viewer.');}catch{message('Copy the viewer token from the receiver terminal.');}});
byId('trace-fullscreen').addEventListener('click',async()=>{try{if(document.fullscreenElement)await document.exitFullscreen();else await document.documentElement.requestFullscreen();}catch{message('Fullscreen unavailable');}});
const traceResizeObserver=new ResizeObserver(()=>{draw();chart(currentTarget());});
traceResizeObserver.observe(byId('trace-stage'));traceResizeObserver.observe(byId('trace-history'));
window.addEventListener('pagehide',()=>{stopDevice();if(frameURL)URL.revokeObjectURL(frameURL);});
setInterval(poll,500);setInterval(pollCamera,200);setInterval(publishCamera,200);render();

// Scripted presentation only. No robot, vision, phone or report API is called.
(() => {
  const stages=[0,15,30,85,100,120,165,195,220],duration=240;
  const cases={
    injured:{human:true,phone:true,result:'Injured',tone:'injured',release:null},
    safe:{human:true,phone:true,result:'Safe',tone:'safe',release:null},
    phone:{human:false,phone:true,result:'No human · phone visible',tone:'unknown',release:'both'},
    'no-phone':{human:false,phone:false,result:'Not found · spot cleared',tone:'unknown',release:'drone'},
    occluded:{human:false,phone:false,occluded:true,result:'Not found · spot cleared',tone:'unknown',release:null},
    battery:{human:false,phone:true,abort:true,result:'Low battery · drone returned',tone:'unknown',release:null}
  };
  let elapsed=0,playing=!matchMedia('(prefers-reduced-motion: reduce)').matches,previous=0,lastText=null,spot=0,decision='',droneOnly=false,panelVisible=parent===window;
  window.addEventListener('message',event=>{if(event.origin===location.origin&&event.source===parent&&event.data?.type==='workspace-visibility')panelVisible=event.data.visible===true;});
  const setText=(id,value)=>{const node=byId(id);if(node.textContent!==value)node.textContent=value;};
  const fmt=t=>`${Math.floor(t/60)}:${String(Math.floor(t%60)).padStart(2,'0')}`;
  const clamp=t=>Math.max(0,Math.min(1,t));
  function lerp(a,b,t){return [a[0]+(b[0]-a[0])*t,a[1]+(b[1]-a[1])*t];}
  function along(points,t){const at=clamp(t)*(points.length-1),i=Math.min(points.length-2,Math.floor(at));return lerp(points[i],points[i+1],at-i);}
  function ground(t,end){const p=clamp(t),q=1-p;return [q*q*180+2*q*p*440+p*p*end[0],q*q*325+2*q*p*345+p*p*end[1]];}
  function stageAt(t){let i=0;while(i<stages.length-1&&t>=stages[i+1])i++;return i;}
  function controls(){setText('animation-toggle',playing?'Pause':'Play');byId('animation-toggle').setAttribute('aria-label',(playing?'Pause':'Play')+' mission animation');}
  function paint(){
    const scenario=cases[byId('mission-case').value],t=elapsed,step=stageAt(t),dx=spot%2?-90:0,dy=spot%2?85:0,target=[700+dx,135+dy],home=[230,300],end=[target[0]-38,target[1]+42];
    const route=[home,[230,235],[370,235],[370,100],[500,100],[500,220],[610,220],target];
    const returnAt=scenario.abort?55:100,landAt=scenario.abort?80:120;
    let drone=home,z=0;
    if(t>=15&&t<30)z=5*clamp((t-15)/15);
    else if(t>=30&&t<returnAt){drone=along(route,(t-30)/55);z=5;}
    else if(t>=returnAt&&t<landAt){const from=scenario.abort?along(route,(55-30)/55):target;drone=lerp(from,home,clamp((t-returnAt)/(landAt-returnAt-5)));z=t>landAt-5?5*(landAt-t)/5:5;}
    let rover=[180,325];
    if(!scenario.abort&&!droneOnly){if(t>=120&&t<165)rover=ground((t-120)/45,end);else if(t>=165&&t<195)rover=end;else if(t>=195&&t<220)rover=ground(1-(t-195)/25,end);}
    byId('mission-drone').setAttribute('transform',`translate(${drone[0]} ${drone[1]})`);
    byId('mission-drone-body').setAttribute('transform',`translate(0 ${-z*2})`);
    byId('mission-rover').setAttribute('transform',`translate(${rover[0]} ${rover[1]})`);
    const inspecting=t>=165&&t<195&&!scenario.abort&&!droneOnly,scanAngle=inspecting?-55+((t-165)/30)*360:t>=195?125:-55;
    byId('mission-rover-body').setAttribute('transform',`rotate(${scanAngle})`);
    byId('mission-camera-sweep').setAttribute('transform',`rotate(${scanAngle})`);
    byId('mission-camera-sweep').setAttribute('opacity',t>=120&&t<220&&!scenario.abort&&!droneOnly?'1':'0');
    byId('mission-target').setAttribute('transform',`translate(${dx} ${dy})`);
    byId('mission-radio-rings').setAttribute('transform',`translate(${dx} ${dy})`);
    byId('mission-person').setAttribute('transform',`translate(${745+dx} ${168+dy})`);
    byId('mission-occlusion').setAttribute('transform',`translate(${dx} ${dy})`);
    byId('mission-phone').setAttribute('opacity',scenario.phone?'1':'0');
    byId('mission-person').setAttribute('opacity',scenario.human&&t>=165?'1':'0');
    byId('mission-occlusion').setAttribute('opacity',scenario.occluded?'1':'0');
    byId('mission-condition-ring').setAttribute('stroke',scenario.tone==='safe'?'#4ade80':'#ff4d66');
    byId('mission-condition-ring').setAttribute('opacity',t>=180?'1':'.15');
    byId('mission-target-label').textContent=spot?'NEXT SPOT · SCRIPTED':scenario.phone?'PHONE (5,5,5)':'SIGNAL CUE · NO PHONE VISIBLE';
    byId('mission-search-trail').setAttribute('d','M'+route.map(p=>p.join(' ')).join('L'));
    byId('mission-return-trail').setAttribute('d',`M${target.join(' ')}L230 300`);
    byId('mission-ground-trail').setAttribute('d',`M180 325Q440 345 ${end.join(' ')}`);
    byId('mission-ground-trail').setAttribute('opacity',scenario.abort?'.15':'1');
    const handoff=t>=landAt-5&&t<125;
    byId('mission-handoff').setAttribute('opacity',handoff?'1':'0');
    const packet=along([[230,300],[180,325],[115,325]],((t%2)/2));
    byId('mission-data-packet').setAttribute('cx',packet[0]);byId('mission-data-packet').setAttribute('cy',packet[1]);
    byId('mission-altitude-dot').setAttribute('cy',70-z/5*70);setText('mission-altitude',`${z.toFixed(1)} in`);
    setText('mission-drone-label',z>0?`DRONE · Z ${z.toFixed(1)} in`:'DRONE · HOME');
    setText('mission-rover-label',inspecting?'ROVER · CAMERA 360°':t>=120&&t<220&&!scenario.abort&&!droneOnly?'ROVER · CAMERA ON':'ROVER · HOME');
    const airborne=t>=15&&t<landAt,flightUsed=Math.max(0,Math.min(t,landAt)-15);
    setText('mission-battery',scenario.abort&&t>=55?'LOW BATTERY · RETURNED':`Flight ${fmt(flightUsed)} / 2:00 · hard return 2:30`);
    byId('mission-battery').classList.toggle('battery-alert',!!scenario.abort&&t>=55);
    const near=clamp((drone[0]-230)/(target[0]-230));
    setText('mission-signal',t>=30&&t<landAt?`DEMO RSSI ${Math.round(-82+near*36+Math.sin(t*1.9)*3)} dBm · ${near>.7?'hotter':'colder'}`:'DEMO RSSI · illustrative');
    const descriptions=[['BLE cue','Jetson receives the scripted BLE cue; drone starts to the right of the rover.'],['Takeoff','Drone rises to (0,0,5) inches in the script.'],['Search','Drone follows a hot / cold signal sweep. RSSI here is illustrative, not a distance estimate.'],['Identity logged','Drone hovers at (5,5,5), logging the example phone identity.'],['Drone returns','Drone returns to (0,0,5), lands and hands the observation to the rover.'],['Rover approach','Pi 5 camera turns on; rover approaches the suggested inspection point.'],['Inspect 360°',scenario.human?'Camera confirms a human and phone. A simulated phone check-in determines the condition.':'Rover turns through 360° with its camera on; checks for a human and a phone.'],['Rover returns','Rover returns home to the Jetson before the operator report.'],['Report / choice','Review the scripted outcome, then choose what happens next.']];
    let [phase,caption]=descriptions[step];
    if(scenario.abort&&t>=55&&t<120){phase='Early return';caption='Low battery interrupts the search. Drone returns and lands before the flight limit.';}
    if((scenario.abort||droneOnly)&&step>=5&&step<8){phase='Rover holds';caption=scenario.abort?'Search aborted before handoff; rover stays home. Swap the battery before another flight.':'Drone-only release: rover stays home while the next search is reviewed.';}
    setText('mission-phase',phase);setText('mission-caption',decision||caption);
    for(const [index,label]of [[3,scenario.abort?'Early return':'Log identity'],[4,scenario.abort?'Drone home':'Drone home'],[5,(scenario.abort||droneOnly)?'Rover holds':'Rover approach'],[6,(scenario.abort||droneOnly)?'Inspection skipped':'Inspect 360°'],[7,(scenario.abort||droneOnly)?'Both home':'Rover home']]){const node=byId('mission-step-'+index).querySelector('button');if(node.textContent!==label)node.textContent=label;}
    setText('mission-clock',`${fmt(t)} / 4:00`);byId('mission-seek').value=t;
    for(let i=0;i<stages.length;i++){byId('mission-step-'+i).classList.toggle('active',i===step);byId('mission-step-'+i).classList.toggle('done',i<step);byId('mission-step-'+i).querySelector('button').setAttribute('aria-current',i===step?'step':'false');}
    let report='';
    if(step===3&&!scenario.abort)report='DEMO LOG / Phone beacon 001\nIdentity cue saved · handoff pending';
    if(step===6&&!scenario.abort&&!droneOnly)report=t<180?'DEMO VISION / inspection in progress':`DEMO VISION / human ${scenario.human?'confirmed':'not visible'} · phone ${scenario.phone?'visible':'not visible'}\n${scenario.human?'Simulated check-in: '+scenario.result:'360° scan · strong example signal'}`;
    if(step===8)report=`DEMO REPORT / ${scenario.result}\nDrone home · rover home\n${scenario.release==='both'?'Both vehicles available for release':scenario.release==='drone'?'Only drone available for release':'Awaiting operator choice'}`;
    if(report!==lastText){byId('mission-report').textContent=report;lastText=report;}
    byId('mission-report').className=step===8?'report-'+scenario.tone:'';
    byId('mission-actions').hidden=step!==8;
    byId('mission-release').hidden=!scenario.release;
    setText('mission-release',scenario.release==='drone'?'Release drone only':'Release both');
    if(t>=duration){playing=false;controls();}
    byId('mission-prev').disabled=t===0;byId('mission-next').disabled=step===8;
    byId('mission-drone-shadow').setAttribute('opacity',airborne?'.7':'.3');
  }
  function seek(t){elapsed=Math.max(0,Math.min(duration,t));playing=false;decision='';controls();paint();}
  function replay(){elapsed=0;decision='';previous=0;playing=true;controls();paint();}
  byId('mission-case').addEventListener('change',()=>{spot=0;droneOnly=false;replay();});
  byId('animation-toggle').addEventListener('click',()=>{if(elapsed>=duration)elapsed=0;playing=!playing;controls();paint();});
  byId('animation-replay').addEventListener('click',()=>{spot=0;droneOnly=false;replay();});
  byId('mission-seek').addEventListener('input',()=>seek(Number(byId('mission-seek').value)));
  for(const button of document.querySelectorAll('[data-stage]'))button.addEventListener('click',()=>seek(stages[Number(button.dataset.stage)]));
  byId('mission-prev').addEventListener('click',()=>seek(stages[Math.max(0,stageAt(elapsed)-1)]));
  byId('mission-next').addEventListener('click',()=>seek(stages[Math.min(8,stageAt(elapsed)+1)]));
  for(const button of document.querySelectorAll('[data-next-mission]'))button.addEventListener('click',()=>{
    const action=button.dataset.nextMission;
    if(action==='end'){playing=false;decision='Demo ended. Both vehicles remain home.';controls();paint();return;}
    if(action==='battery'){if(cases[byId('mission-case').value].abort)byId('mission-case').value='injured';spot=0;droneOnly=false;replay();decision='Battery swapped in the animation; new flight budget.';paint();return;}
    droneOnly=action==='release'&&cases[byId('mission-case').value].release==='drone';spot++;replay();decision=action==='release'&&cases[byId('mission-case').value].release==='drone'?'Drone released for the next search; rover stays home.':'Next search spot selected in the animation.';paint();
  });
  function tick(now){if(previous&&playing&&panelVisible&&!document.hidden){elapsed=Math.min(duration,elapsed+Math.min(.1,(now-previous)/1000)*Number(byId('animation-speed').value));if(decision&&elapsed>15)decision='';paint();}previous=now;requestAnimationFrame(tick);}
  window.addEventListener('mission-scene',event=>{const detail=event.detail||{};if(!cases[detail.case])return;byId('mission-case').value=detail.case;spot=0;droneOnly=false;decision='';seek(Number.isFinite(detail.time)?detail.time:185);});
  byId('mission-practice').addEventListener('click',()=>{if(parent!==window)parent.postMessage({type:'mission-practice',case:byId('mission-case').value},location.origin);else location.href='/#decisions';});
  controls();paint();requestAnimationFrame(tick);
})();

byId('trace-details').addEventListener('click',()=>{const open=document.body.classList.toggle('show-details');byId('trace-details').setAttribute('aria-expanded',String(open));chart(currentTarget());});

// Scenario exercises use fixed synthetic evidence and never submit a live action.
(() => {
  if(!new URLSearchParams(location.search).has('quiz'))return;
  document.body.classList.add('quiz-mode');document.title='T15 · Operator exercises';
  for(const id of ['quiz-toolbar','quiz-divider','quiz-console'])byId(id).hidden=false;
  const option=(text,why,correct=false)=>({text,why,correct});
  const question=(prompt,choices)=>({prompt,choices});
  const scenarios=[
    {id:'injured',name:'01 · Courtyard contact',scene:'injured',time:185,
      context:'A collapsed-building search reaches a courtyard. The rover has completed its camera sweep.',
      facts:['A human and phone are visible together.','The exercise check-in returns Injured; the visual uses a red condition ring.','Drone is home. Rover is still at the inspection point.'],
      questions:[question('What should you do next?',[
        option('Return the rover and prepare an Injured report.','The supplied script returns both vehicles and preserves the Injured condition in the report.',true),
        option('Mark the person Safe because the phone is responding.','A phone response does not change the stated Injured condition. This would put the wrong condition in the report.'),
        option('Release both vehicles to search a new spot immediately.','That skips the return and report step for the confirmed person in this script.')]),
        question('What belongs in the report?',[
          option('Human and phone visually confirmed; exercise check-in Injured; both vehicles returned.','This distinguishes the camera observation, the scripted condition response and the completed vehicle return.',true),
          option('The camera measured the person’s vital signs.','No vital-sign measurement is supplied. Camera visibility and a scripted check-in cannot support this claim.'),
          option('BLE alone confirmed an injured person.','The human was confirmed visually and the condition came from the exercise check-in, not BLE.')])]},
    {id:'safe',name:'02 · School entrance',scene:'safe',time:185,
      context:'The rover reaches a school entrance after the drone hands off its phone observation.',
      facts:['Camera confirms a human and phone.','The exercise check-in returns Safe; the visual uses a green condition ring.','Drone is home; rover has not returned yet.'],
      questions:[question('Which response follows the script?',[
        option('Return the rover and report Safe, retaining the observation evidence.','The Safe branch returns both vehicles and records the supplied condition.',true),
        option('Report Injured because the beacon was initially urgent.','An initial beacon cue does not override the later Safe check-in supplied by this exercise.'),
        option('Close the mission now without recording the rover’s return.','The return and report steps are still incomplete.')]),
        question('What can you accurately claim?',[
          option('A person was seen; the supplied check-in said Safe.','That is the evidence given. The exercise does not provide a medical examination.',true),
          option('No person is present because RSSI fluctuates.','Signal variation does not cancel a camera-confirmed observation.'),
          option('A green ring proves the person is medically cleared.','The green ring represents this demo’s supplied Safe response, not medical clearance.')])]},
    {id:'phone',name:'03 · Parked vehicle',scene:'phone',time:185,
      context:'A phone is visible beside a parked vehicle. A complete rover sweep finds no human in view.',
      facts:['Phone is visible; no human is visible in the sweep.','A strong example BLE signal remains.','Both vehicles return before the next release choice.'],
      questions:[question('Which report best matches the evidence?',[
        option('No human observed; phone visible. Return and record that outcome.','This reports what was actually seen, without turning a phone observation into a person confirmation.',true),
        option('Person confirmed because the phone and signal are present.','A phone and radio activity do not establish that a person is present.'),
        option('Human absent everywhere in the search area.','The visual only covers the completed inspection. It cannot establish absence throughout the area.')]),
        question('After both vehicles return, which release does your demo script allow?',[
          option('Release both the drone and rover for the next search.','The supplied “no human, phone visible” branch permits both vehicles to be released.',true),
          option('Only the rover may be released.','That is not the release rule in the supplied script.'),
          option('Always end the mission because the phone was found.','The script allows a further search; finding a phone does not complete a person search.')])]},
    {id:'no-phone',name:'04 · Empty loading bay',scene:'no-phone',time:185,
      context:'The rover inspects a loading bay where the drone had marked a radio cue.',
      facts:['The camera sweep shows neither a human nor a phone.','Rover completes the 360° check and returns.','The finding applies to this inspected spot, not the whole search region.'],
      questions:[question('What should the operator record?',[
        option('Not found at this spot; inspection complete; rover returned.','This follows the demo’s “not found, spot cleared” report while keeping its scope limited to the inspected spot.',true),
        option('Human confirmed from the earlier radio cue.','The radio cue did not establish a human, and the inspection supplies no visual confirmation.'),
        option('Person Safe because no one appears injured in the frame.','An empty frame cannot establish a person’s condition.')]),
        question('Which next release matches the no-human, no-phone branch?',[
          option('Release only the drone for another search; rover stays home.','This is the explicit release rule in the supplied script.',true),
          option('Release both vehicles automatically.','Both-vehicle release belongs to the phone-visible branch, not this branch.'),
          option('Send the rover directly to another radio cue without a drone handoff.','That skips the next drone search and handoff described in the script.')])]},
    {id:'occluded',name:'05 · Obstructed passage',scene:'occluded',time:175,
      context:'An obstruction blocks the initial camera view. The example signal is strong, but no person is immediately visible.',
      facts:['The first camera angle is obstructed.','The 360° inspection is still in progress.','Signal strength is a radio observation, not proof of a person.'],
      questions:[question('What is the next step in this demo?',[
        option('Complete the rover’s 360° camera sweep before making the visual finding.','The supplied script calls for a full sweep when a human is not immediately visible.',true),
        option('Declare the whole spot clear from the first obstructed view.','That treats incomplete visibility as a completed inspection.'),
        option('Report an injured human because the signal is strong.','Neither presence nor condition follows from RSSI.')]),
        question('The completed sweep still shows no human or phone. What next?',[
          option('Return the rover; report Not found at this spot; choose another search, battery swap, or end.','This follows the return, report and next-choice sequence while preserving the limits of the observation.',true),
          option('Report that no human could be anywhere behind the obstruction.','The exercise does not provide that visibility.'),
          option('Leave the rover deployed and mark the mission complete.','That omits the rover’s return and the operator’s next-action choice.')])]},
    {id:'battery',name:'06 · Battery interruption',scene:'battery',time:65,
      context:'The drone receives a low-battery warning during its example search. It has not completed the identity handoff.',
      facts:['Low-battery warning is active.','The drone is already taking its early-return path.','The demo allows at most two minutes of flight, with a hard return at 2:30 or on low battery.'],
      questions:[question('Which decision fits the current evidence and script?',[
        option('Continue the early return and landing; keep the rover at home.','Low battery takes priority in this script. The incomplete search must not be treated as a completed handoff.',true),
        option('Continue searching until 2:30 because the timer has not expired.','The low-battery warning triggers return earlier; 2:30 is not permission to ignore it.'),
        option('Deploy the rover as though the identity handoff is complete.','The scenario explicitly says the handoff is incomplete.')]),
        question('The drone has landed. What should happen before another attempt?',[
          option('Record the interrupted search; swap the battery and explicitly relaunch if continuing.','The report should retain the interruption. The script provides a battery-swap and relaunch choice.',true),
          option('Report Not found because the flight ended without a person.','An interrupted search is not a completed visual inspection.'),
          option('Automatically relaunch with the same low battery.','That ignores the reason the search was interrupted.')])]},
    {id:'radio',name:'07 · Radio-only cue',scene:'occluded',time:45,
      context:'The example receiver shows a stronger BLE trend during the drone sweep. No camera inspection or accepted identity is available yet.',
      facts:['Illustrative RSSI rises from −76 to −45 dBm.','There is no visual confirmation of a human or phone.','No accepted identity or signed condition is provided in this case.'],
      questions:[question('What can the operator infer at this point?',[
        option('The radio cue became stronger; identity, position and human presence remain unconfirmed.','RSSI variation alone does not establish distance, bearing, identity or a person’s presence.',true),
        option('The phone is exactly five inches from the receiver.','The diagram uses scripted coordinates. RSSI is not an exact distance measurement.'),
        option('A person is confirmed and must be Injured.','The case provides neither a visual person observation nor a signed condition.')]),
        question('Which report preserves the uncertainty?',[
          option('Radio cue only; visual inspection and identity confirmation pending.','This states the observation and the checks still missing.',true),
          option('Safe person located at the map marker.','The marker is illustrative and no person or condition has been confirmed.'),
          option('The camera found a phone because the signal was strong.','No camera inspection is supplied in this case.')])]}
  ];
  const records=new Map(),total=scenarios.reduce((n,s)=>n+s.questions.length,0);
  let caseIndex=0,questionIndex=0;
  const select=byId('quiz-case');for(const scenario of scenarios){const item=html('option',scenario.name);item.value=scenario.id;select.append(item);}
  function entry(){const key=scenarios[caseIndex].id+':'+questionIndex;if(!records.has(key)){const order=scenarios[caseIndex].questions[questionIndex].choices.map((_,i)=>i);for(let i=order.length-1;i>0;i--){const random=new Uint32Array(1);crypto.getRandomValues(random);const j=random[0]%(i+1);[order[i],order[j]]=[order[j],order[i]];}records.set(key,{order,selected:null,tries:0,correct:false,first:false,feedback:null});}return records.get(key);}
  function showScene(time){const scenario=scenarios[caseIndex];window.dispatchEvent(new CustomEvent('mission-scene',{detail:{case:scenario.scene,time:time??(questionIndex===0?scenario.time:scenario.id==='battery'?100:scenario.id==='radio'?45:220)}}));}
  function renderQuizVisual(){
    const scenario=scenarios[caseIndex],scene=document.querySelector('.mission-scene');
    let environment=byId('quiz-environment'),inset=byId('quiz-visual-inset');
    if(!environment){environment=svg('g',{id:'quiz-environment'});scene.insertBefore(environment,byId('mission-radio-rings'));inset=svg('g',{id:'quiz-visual-inset',transform:'translate(685 275)'});scene.append(inset);}
    environment.replaceChildren();inset.replaceChildren();
    const add=(parent,tag,attrs,text)=>{const node=svg(tag,attrs);if(text)node.textContent=text;parent.append(node);return node;};
    const label=(parent,x,y,text,color='#a7a7b0',size=10)=>add(parent,'text',{x,y,fill:color,'font-size':size,'font-family':'system-ui,sans-serif'},text);
    if(scenario.id==='injured'){
      add(environment,'path',{d:'M765 40H940V135H845L800 105H765Z',fill:'#242127',stroke:'#61535c','stroke-dasharray':'5 4'});
      for(const [x,y]of [[785,120],[810,132],[830,148],[860,139],[875,155]])add(environment,'path',{d:`M${x} ${y}l14 -9 8 14-17 7Z`,fill:'#4d434c',stroke:'#786772'});
      label(environment,785,66,'DAMAGED BUILDING');
    }else if(scenario.id==='safe'){
      add(environment,'rect',{x:775,y:30,width:170,height:72,rx:4,fill:'#23272e',stroke:'#4b5563'});
      for(let i=0;i<5;i++)add(environment,'rect',{x:788+i*30,y:45,width:15,height:21,fill:'#3d4a5b'});
      add(environment,'path',{d:'M800 102L730 155',stroke:'#666974','stroke-width':13});label(environment,795,88,'SCHOOL ENTRANCE');
    }else if(scenario.id==='phone'){
      add(environment,'rect',{x:770,y:88,width:127,height:58,rx:10,fill:'#2f3440',stroke:'#778094','stroke-width':2});
      add(environment,'rect',{x:801,y:94,width:50,height:45,rx:5,fill:'#536275'});
      for(const x of [789,865])for(const y of [83,143])add(environment,'rect',{x,y,width:16,height:8,rx:2,fill:'#111116'});
      label(environment,785,169,'PARKED VEHICLE');
    }else if(scenario.id==='no-phone'){
      add(environment,'path',{d:'M580 65H885V220H800M580 65V220H630',fill:'none',stroke:'#52515d','stroke-width':12});
      for(let i=0;i<4;i++)add(environment,'path',{d:`M${610+i*55} 210l20 -18`,stroke:'#bc97514d','stroke-width':6});
      label(environment,603,92,'LOADING BAY');
    }else if(scenario.id==='occluded'){
      add(environment,'rect',{x:615,y:62,width:35,height:170,fill:'#393c44',stroke:'#5e616b'});
      add(environment,'rect',{x:793,y:62,width:35,height:170,fill:'#393c44',stroke:'#5e616b'});
      label(environment,663,84,'NARROW PASSAGE');
    }
    add(inset,'rect',{width:290,height:134,rx:5,fill:'#151519',stroke:'#63636d','stroke-width':1});
    label(inset,12,19,scenario.id==='battery'||scenario.id==='radio'?'EXERCISE / NO CAMERA INSPECTION':'EXERCISE / CAMERA STILL','#aaaab4',9);
    add(inset,'path',{d:'M10 108H280M10 37H280',stroke:'#ffffff10'});
    if(scenario.id==='battery'||scenario.id==='radio'){
      label(inset,16,65,scenario.id==='battery'?'LOW BATTERY → EARLY RETURN':'RADIO CUE ONLY',scenario.id==='battery'?'#ff8a80':'#93c5fd',12);
      label(inset,16,88,'No visual human or phone confirmation.','#a7a7b0',10);
    }else{
      if(scenario.id==='injured'||scenario.id==='safe'){
        add(inset,'circle',{cx:96,cy:55,r:9,fill:'#d879f5'});add(inset,'path',{d:'M88 68H104L111 88H101V103H91V88H82Z',fill:'#d879f5'});
        add(inset,'rect',{x:74,y:41,width:47,height:66,rx:3,fill:'none',stroke:'#d879f580'});label(inset,75,119,'HUMAN','#d879f5',8);
      }
      if(['injured','safe','phone'].includes(scenario.id)){
        add(inset,'rect',{x:172,y:67,width:17,height:32,rx:3,fill:'#18314f',stroke:'#60a5fa','stroke-width':2});label(inset,165,119,'PHONE','#93c5fd',8);
      }
      if(scenario.id==='occluded'&&questionIndex===0){add(inset,'rect',{x:55,y:43,width:170,height:62,fill:'#34373f',stroke:'#616575'});label(inset,81,80,'VIEW OBSTRUCTED','#d1d1d8',10);}
      if(scenario.id==='no-phone'||scenario.id==='occluded'&&questionIndex===1){label(inset,49,78,'NO HUMAN / PHONE OBSERVED','#b5b5bf',10);}
      if(['injured','safe'].includes(scenario.id))label(inset,132,52,'CHECK-IN: '+(scenario.id==='safe'?'SAFE':'INJURED'),scenario.id==='safe'?'#4ade80':'#ff6476',10);
    }
  }
  function render(){
    const scenario=scenarios[caseIndex],q=scenario.questions[questionIndex],record=entry();select.value=scenario.id;
    byId('quiz-context').textContent=scenario.context;
    const facts=scenario.facts.slice();
    if((questionIndex===1||record.correct)&&['injured','safe'].includes(scenario.id))facts[2]='Updated outcome: rover has returned; both vehicles are home.';
    if((questionIndex===1||record.correct)&&scenario.id==='phone')facts[2]='Both vehicles have returned; the operator may now choose the next release.';
    if(questionIndex===1&&scenario.id==='occluded')facts[1]='The completed 360° sweep shows no human or phone.';
    if(questionIndex===1&&scenario.id==='battery')facts[1]='The early return is complete; drone has landed without an identity handoff.';
    if(questionIndex===1&&scenario.id==='occluded')facts.push('New evidence: the completed sweep still shows no human or phone; rover has returned.');
    if(questionIndex===1&&scenario.id==='battery')facts.push('New evidence: landing is confirmed; rover remains home.');
    byId('quiz-facts').replaceChildren(...facts.map(fact=>html('li',fact)));
    byId('quiz-question').textContent=q.prompt;
    const choices=record.order.map((index,position)=>{const label=html('label','','quiz-answer'),input=document.createElement('input');input.type='radio';input.name='quiz-choice';input.value=index;input.checked=record.selected===index;input.disabled=record.correct;const badge=html('span',String.fromCharCode(65+position),'quiz-choice-letter');label.append(input,badge,html('span',q.choices[index].text));if(record.correct&&q.choices[index].correct)label.classList.add('answer-correct');input.addEventListener('change',()=>{record.selected=index;record.feedback=null;byId('quiz-check').disabled=false;byId('quiz-feedback').hidden=true;});return label;});
    byId('quiz-answers').replaceChildren(...choices);
    byId('quiz-check').disabled=record.selected===null||record.correct;byId('quiz-check').textContent=record.correct?'Decision checked':'Check decision';
    const feedback=byId('quiz-feedback');feedback.hidden=!record.feedback;feedback.className=record.correct?'quiz-correct':'quiz-retry';feedback.textContent=record.feedback||'';
    byId('quiz-next').disabled=!record.correct;byId('quiz-next').textContent=questionIndex<scenario.questions.length-1?'Next question →':'Next case →';
    const values=[...records.values()],completed=values.filter(r=>r.correct).length,first=values.filter(r=>r.first).length;
    byId('quiz-score').textContent=`${completed}/${total} completed · ${first} first try`;
    if(completed===total){byId('quiz-next').textContent='Review cases →';if(record.feedback)feedback.textContent+=' All '+total+' decisions completed. Reset exercise to start a new round.';}
    byId('quiz-progress').textContent=`Case ${caseIndex+1}/${scenarios.length} · Decision ${questionIndex+1}/${scenario.questions.length}`;
    byId('quiz-review').textContent=scenario.id==='battery'||scenario.id==='radio'?'Review drone visual':'Review inspection visual';
    showScene();renderQuizVisual();
  }
  byId('quiz-form').addEventListener('submit',event=>{event.preventDefault();const record=entry();if(record.selected===null||record.correct)return;const selected=scenarios[caseIndex].questions[questionIndex].choices[record.selected];record.tries++;record.correct=selected.correct;record.first=selected.correct&&record.tries===1;record.feedback=(selected.correct?'Correct. ':'Review this choice. ')+selected.why;render();if(selected.correct&&questionIndex===0&&scenarios[caseIndex].id!=='radio')showScene(scenarios[caseIndex].id==='battery'?100:220);});
  select.addEventListener('change',()=>{caseIndex=scenarios.findIndex(s=>s.id===select.value);questionIndex=0;render();});
  byId('quiz-next').addEventListener('click',()=>{if(!entry().correct)return;if(questionIndex+1<scenarios[caseIndex].questions.length)questionIndex++;else{caseIndex=(caseIndex+1)%scenarios.length;questionIndex=0;}render();byId('quiz-question').scrollIntoView({block:'nearest'});});
  byId('quiz-random').addEventListener('click',()=>{caseIndex=(caseIndex+1+Math.floor(Math.random()*(scenarios.length-1)))%scenarios.length;questionIndex=0;render();});
  byId('quiz-reset').addEventListener('click',()=>{records.clear();caseIndex=0;questionIndex=0;render();});
  byId('quiz-review').addEventListener('click',()=>showScene(scenarios[caseIndex].time));
  window.addEventListener('message',event=>{if(event.origin!==location.origin||event.source!==parent||event.data?.type!=='mission-quiz-case')return;const index=scenarios.findIndex(s=>s.id===event.data.case);if(index<0)return;caseIndex=index;questionIndex=0;render();});
  let controlFrame=null;
  const authenticateControls=()=>{if(controlFrame&&viewerToken)controlFrame.contentWindow.postMessage({type:'workspace-auth',token:viewerToken},location.origin);};
  byId('quiz-live').addEventListener('click',()=>{document.body.classList.add('quiz-live-open');if(!controlFrame){const shell=html('div','','quiz-live-panel'),back=html('button','← Back to exercise');back.id='quiz-back';back.addEventListener('click',()=>document.body.classList.remove('quiz-live-open'));controlFrame=document.createElement('iframe');controlFrame.title='Live operator controls';controlFrame.src='/control?embedded=1&decisions=1';controlFrame.addEventListener('load',authenticateControls);shell.append(back,controlFrame);byId('trace-stage').append(shell);}authenticateControls();});
  window.addEventListener('message',event=>{if(controlFrame&&event.origin===location.origin&&event.source===controlFrame.contentWindow&&event.data?.type==='workspace-ready')authenticateControls();});
  render();
})();
