'use strict';
// Camera frames, recording and playback stay on the operator's local network/browser.
let cameraLive=false,cameraBusy=false,frameURL='',playbackId='',lastSequence='',recorder=null;
let videoChunks=[],videoBytes=0,videoStarted=0,videoStream=null,videoTimer=null;
let bleFeed=null,bleCapture=null,bleBytes=0,bleBusy=false,blePlayback=null;
const recordings=[],captureCanvas=document.createElement('canvas');
captureCanvas.width=1280;captureCanvas.height=720;
const captureContext=captureCanvas.getContext('2d',{alpha:false});
const MAX_VIDEO=128*1024*1024,MAX_BLE=32*1024*1024;
let dbPromise;
function recordingDB(){
  if(!dbPromise)dbPromise=new Promise((resolve,reject)=>{
    const request=indexedDB.open('team15-recordings',1);
    request.onupgradeneeded=()=>request.result.createObjectStore('recordings',{keyPath:'id'});
    request.onsuccess=()=>resolve(request.result);request.onerror=()=>reject(request.error);
  });return dbPromise;
}
async function storeRecording(entry){
  const db=await recordingDB();
  const {url,...saved}=entry; // Blob URLs belong to this document and cannot survive reload.
  return new Promise((resolve,reject)=>{const tx=db.transaction('recordings','readwrite');tx.objectStore('recordings').put(saved);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);tx.onabort=()=>reject(tx.error);});
}
async function addRecording(kind,blob,name){
  const entry={id:crypto.randomUUID(),kind,blob,name,created:new Date().toISOString()};
  recordings.unshift(entry);renderRecordings();
  try{await storeRecording(entry);}catch{notice('Browser storage unavailable. Download this recording before closing.');}
  return entry;
}
function recordingURL(entry){if(!entry.url)entry.url=URL.createObjectURL(entry.blob);return entry.url;}
async function removeRecording(entry){
  try{const db=await recordingDB();await new Promise((resolve,reject)=>{const tx=db.transaction('recordings','readwrite');tx.objectStore('recordings').delete(entry.id);tx.oncomplete=resolve;tx.onerror=()=>reject(tx.error);});}
  catch{notice('Could not remove saved recording');return;}
  if(playbackId===entry.id)showLive();
  if(blePlayback?.id===entry.id)closeBLEPlayback();
  if(entry.url)URL.revokeObjectURL(entry.url);
  recordings.splice(recordings.indexOf(entry),1);renderRecordings();
}
function renderRecordings(){
  $('recordings').replaceChildren();
  if(!recordings.length)$('recordings').append(element('p','No recordings','empty'));
  for(const entry of recordings){
    const item=element('article','','recording-item'),label=element('div'),actions=element('div','','recording-actions');
    label.append(element('strong',entry.kind==='video'?'Camera':'Bluetooth'),element('small',new Date(entry.created).toLocaleTimeString([], {hour:'2-digit',minute:'2-digit'})+' · '+(entry.blob.size/1048576).toFixed(1)+' MB'));
    label.title=entry.name;
    const play=element('button',entry.kind==='video'?'Play':'View');play.addEventListener('click',()=>entry.kind==='video'?playVideo(entry):openBLEPlayback(entry));
    const download=element('a','Save');download.href=recordingURL(entry);download.download=entry.name;download.setAttribute('aria-label','Download '+entry.name);
    const remove=element('button','×','quiet');remove.setAttribute('aria-label','Delete '+entry.name);remove.addEventListener('click',()=>removeRecording(entry));
    actions.append(play,download,remove);item.append(label,actions);$('recordings').append(item);
  }
}
async function loadRecordings(){
  try{const db=await recordingDB();const entries=await new Promise((resolve,reject)=>{const r=db.transaction('recordings').objectStore('recordings').getAll();r.onsuccess=()=>resolve(r.result);r.onerror=()=>reject(r.error);});
    for(const entry of entries)delete entry.url;
    recordings.push(...entries.filter(e=>e.blob instanceof Blob&&['video','bluetooth'].includes(e.kind)).sort((a,b)=>b.created.localeCompare(a.created)));renderRecordings();
  }catch{/* Recording can still be downloaded when browser storage is unavailable. */}
}
function cameraControls(){
  $('camera-record').disabled=(!cameraLive&&!recorder)||!!playbackId||!window.MediaRecorder||!captureCanvas.captureStream;
  $('camera-record').textContent=recorder?'Stop recording':'Record camera';$('camera-record').classList.toggle('recording',!!recorder);
  $('recording-indicator').hidden=!recorder;
}
function cameraOffline(message){
  cameraLive=false;lastSequence='';$('camera-indicator').classList.remove('live');
  $('camera-status').textContent=message;$('camera-empty').hidden=!!playbackId;$('camera-frame').hidden=true;
  if(recorder&&recorder.state!=='inactive'){recorder.stop();notice('Camera lost. Recording stopped.');}
  cameraControls();
}
async function cameraPoll(){
  if(cameraBusy)return;cameraBusy=true;
  try{
    if(!token){cameraOffline('Pi camera offline');return;}
    const response=await fetch('/api/camera/frame',{headers:{Authorization:'Bearer '+token},cache:'no-store',signal:AbortSignal.timeout(1200)});
    if(!response.ok){cameraOffline(response.status===503?'Pi camera offline':'Camera disconnected');return;}
    const sequence=response.headers.get('X-Camera-Sequence');
    if(sequence!==lastSequence){
      const blob=await response.blob();const bitmap=await createImageBitmap(blob);
      captureContext.drawImage(bitmap,0,0,captureCanvas.width,captureCanvas.height);bitmap.close();
      const next=URL.createObjectURL(blob);$('camera-frame').src=next;if(frameURL)URL.revokeObjectURL(frameURL);frameURL=next;lastSequence=sequence;
    }
    cameraLive=true;$('camera-frame').hidden=!!playbackId;$('camera-empty').hidden=true;$('camera-indicator').classList.add('live');
    if(!playbackId)$('camera-source').textContent='ROVER / '+(response.headers.get('X-Camera-Source')||'PI CAMERA');
    cameraControls();
  }catch{cameraOffline('Camera disconnected');}
  finally{cameraBusy=false;setTimeout(cameraPoll,token?100:500);}
}
function startVideoRecording(){
  if(!cameraLive||playbackId||recorder)return;
  const mime=['video/webm;codecs=vp8','video/webm','video/mp4'].find(type=>MediaRecorder.isTypeSupported(type));
  if(!mime){notice('Camera recording unavailable in this browser');return;}
  try{
    videoStream=captureCanvas.captureStream(10);recorder=new MediaRecorder(videoStream,{mimeType:mime,videoBitsPerSecond:2500000});
    videoChunks=[];videoBytes=0;videoStarted=Date.now();
    recorder.ondataavailable=event=>{if(event.data.size){videoChunks.push(event.data);videoBytes+=event.data.size;}if(videoBytes>=MAX_VIDEO&&recorder?.state==='recording'){recorder.stop();notice('Recording limit reached');}};
    recorder.onstop=()=>{
      clearTimeout(videoTimer);videoStream?.getTracks().forEach(track=>track.stop());
      const blob=new Blob(videoChunks,{type:mime});recorder=null;videoChunks=[];cameraControls();
      if(blob.size)addRecording('video',blob,'camera-'+new Date(videoStarted).toISOString().replace(/[:.]/g,'-')+(mime.startsWith('video/mp4')?'.mp4':'.webm'));
    };
    recorder.onerror=()=>{notice('Camera recording failed');if(recorder&&recorder.state!=='inactive')recorder.stop();};
    recorder.start(1000);videoTimer=setTimeout(()=>{if(recorder?.state==='recording'){recorder.stop();notice('10 minute recording limit reached');}},600000);cameraControls();
  }catch{videoStream?.getTracks().forEach(track=>track.stop());recorder=null;notice('Could not start camera recording');cameraControls();}
}
$('camera-record').addEventListener('click',()=>{if(recorder?.state==='recording')recorder.stop();else startVideoRecording();});
function showLive(){
  $('playback').pause();$('playback').removeAttribute('src');$('playback').load();$('playback').hidden=true;playbackId='';$('live-view').hidden=true;
  $('camera-source').textContent='ROVER / PI CAMERA';$('camera-frame').hidden=!cameraLive;$('camera-empty').hidden=cameraLive;cameraControls();
}
function playVideo(entry){
  if(recorder?.state==='recording')recorder.stop();playbackId=entry.id;$('camera-frame').hidden=true;$('camera-empty').hidden=true;
  $('playback').src=recordingURL(entry);$('playback').hidden=false;$('live-view').hidden=false;$('camera-source').textContent='RECORDING';
  $('playback').play().catch(()=>notice('Use the video play button'));cameraControls();
}
$('live-view').addEventListener('click',showLive);
$('open-video').addEventListener('click',()=>$('video-file').click());
$('video-file').addEventListener('change',async()=>{
  const file=$('video-file').files[0];$('video-file').value='';if(!file)return;
  if(file.size>MAX_VIDEO||(!file.type.startsWith('video/')&&!/\.(mp4|webm|mov)$/i.test(file.name))){notice('Choose a video under 128 MB');return;}
  const entry=await addRecording('video',file,file.name);playVideo(entry);
});
function sparkline(history){
  const ns='http://www.w3.org/2000/svg',svg=document.createElementNS(ns,'svg');svg.setAttribute('viewBox','0 0 240 24');svg.setAttribute('aria-hidden','true');
  const samples=Array.isArray(history)?history.filter(p=>Array.isArray(p)&&p.length===2&&p.every(Number.isFinite)).slice(-61):[];
  const position=([age,rssi])=>[240*(1-Math.max(0,Math.min(30,age))/30),22-(Math.max(-110,Math.min(-20,rssi))+110)/90*20];
  for(let i=1;i<samples.length;i++){
    if(samples[i-1][0]-samples[i][0]>3)continue;
    const [x1,y1]=position(samples[i-1]),[x2,y2]=position(samples[i]);const line=document.createElementNS(ns,'line');
    for(const [key,value]of Object.entries({x1,y1,x2,y2,stroke:'var(--surface-olive)','stroke-width':1.5}))line.setAttribute(key,String(value));svg.append(line);
  }return svg;
}
function renderSignals(container,discovery){
  container.replaceChildren();const signals=Array.isArray(discovery?.signals)?discovery.signals.filter(s=>s&&typeof s==='object'&&!Array.isArray(s)):[];
  if(!signals.length){container.append(element('p',discovery?.status==='scanning'?'No signals':'Receiver offline','empty'));return;}
  for(const signal of signals.slice(0,12)){
    const card=element('article','','signal'+(signal.stale?' stale':'')),top=element('div','','signal-top');
    top.append(element('span',String(signal.label||'Signal')),element('strong',Number.isFinite(signal.rssi)?signal.rssi+' dBm':'—'));
    card.append(top,element('small',[signal.name,Number.isFinite(signal.age_s)?Math.round(signal.age_s)+'s ago':null].filter(Boolean).join(' · ')),sparkline(signal.history));container.append(card);
  }
}
function renderBluetooth(feed){
  const discovery=feed?.discovery,scanning=feed?.connected&&discovery?.status==='scanning';
  $('bluetooth-status').textContent=scanning?'Scanning':'Offline';document.querySelector('.bluetooth-panel').classList.toggle('feed-stale',!scanning);
  $('ble-count').textContent=scanning?(discovery.active??0):'—';$('ble-packets').textContent=feed?.connected?Number(discovery?.packets||0).toLocaleString():'—';
  $('ble-source').textContent=discovery?.source==='LIVE-HW'?'LIVE':discovery?.source||'';
  $('ble-record').disabled=!scanning&&!bleCapture;$('ble-record').textContent=bleCapture?'Stop':'Record';$('ble-record').classList.toggle('recording',!!bleCapture);
  renderSignals($('signals'),discovery);$('beacons').replaceChildren();
  const beacons=feed?.beacons;
  if(Array.isArray(beacons?.sightings)&&beacons.status!=='off')for(const beacon of beacons.sightings.filter(b=>b&&typeof b==='object').slice(0,6)){
    const historical=beacon.stale||beacons.status!=='verifying'||!scanning;
    const card=element('div',(historical?'Previously verified · ':'Verified · ')+String(beacon.alias??beacon.label??'beacon'),'verified');
    card.append(element('small',[beacons.source,beacons.mode_label||beacons.mode,historical?'stale':null,
      Number.isFinite(beacon.last_verified_age_s)?Math.round(beacon.last_verified_age_s)+'s ago':null].filter(Boolean).join(' · ')));$('beacons').append(card);
  }
}
function stopBLECapture(){
  if(!bleCapture)return;const capture=bleCapture;bleCapture=null;capture.ended_at=new Date().toISOString();
  if(capture.samples.length)addRecording('bluetooth',new Blob([JSON.stringify(capture)],{type:'application/json'}),'bluetooth-'+capture.started_at.replace(/[:.]/g,'-')+'.json');
  else notice('No Bluetooth samples recorded');renderBluetooth(bleFeed);
}
async function bluetoothPoll(){
  if(bleBusy)return;bleBusy=true;
  try{
    if(!token){bleFeed=null;if(bleCapture)stopBLECapture();renderBluetooth(null);return;}
    bleFeed=await api('bluetooth');renderBluetooth(bleFeed);
    if(bleCapture){
      if(!bleFeed.connected||bleFeed.discovery?.status!=='scanning'){stopBLECapture();notice('Bluetooth lost. Recording stopped.');}
      else{const sample={recorded_at:new Date().toISOString(),feed:bleFeed};const size=new TextEncoder().encode(JSON.stringify(sample)).length;
        if(bleCapture.samples.length>=10000||bleBytes+size>MAX_BLE){stopBLECapture();notice('Bluetooth recording limit reached');}
        else{bleCapture.samples.push(sample);bleBytes+=size;}}
    }
  }catch{bleFeed=null;if(bleCapture){stopBLECapture();notice('Bluetooth lost. Recording stopped.');}renderBluetooth(null);}
  finally{bleBusy=false;setTimeout(bluetoothPoll,1000);}
}
$('ble-record').addEventListener('click',()=>{
  if(bleCapture){stopBLECapture();return;}
  if(!bleFeed?.connected||bleFeed.discovery?.status!=='scanning')return;
  bleCapture={format:'team15.bluetooth/1',started_at:new Date().toISOString(),samples:[]};bleBytes=0;renderBluetooth(bleFeed);
});
function validateBLECapture(capture){
  if(capture?.format!=='team15.bluetooth/1'||!Array.isArray(capture.samples)||!capture.samples.length||capture.samples.length>10000||
    !capture.samples.every(s=>typeof s?.recorded_at==='string'&&s.feed&&typeof s.feed==='object'&&s.feed.discovery&&Array.isArray(s.feed.discovery.signals)))throw new Error('Invalid Bluetooth recording');
  return capture;
}
async function openBLEPlayback(entry){
  try{const capture=validateBLECapture(JSON.parse(await entry.blob.text()));blePlayback={id:entry.id,capture};
    $('ble-playback').hidden=false;$('ble-playback-name').textContent='Bluetooth playback';$('ble-timeline').max=String(capture.samples.length-1);$('ble-timeline').value='0';renderBLEPlayback();
  }catch{notice('Invalid Bluetooth recording');}
}
function renderBLEPlayback(){
  if(!blePlayback)return;const index=Number($('ble-timeline').value),sample=blePlayback.capture.samples[index];
  $('ble-playback-time').textContent=new Date(sample.recorded_at).toLocaleTimeString()+' · '+(index+1)+' / '+blePlayback.capture.samples.length;
  renderSignals($('ble-playback-signals'),sample.feed.discovery);
}
function closeBLEPlayback(){blePlayback=null;$('ble-playback').hidden=true;}
$('ble-timeline').addEventListener('input',renderBLEPlayback);$('close-ble-playback').addEventListener('click',closeBLEPlayback);
$('ble-file').addEventListener('change',async()=>{
  const file=$('ble-file').files[0];$('ble-file').value='';if(!file)return;if(file.size>MAX_BLE){notice('Bluetooth recording must be under 32 MB');return;}
  try{validateBLECapture(JSON.parse(await file.text()));const entry=await addRecording('bluetooth',file,file.name);openBLEPlayback(entry);}catch{notice('Invalid Bluetooth recording');}
});
window.addEventListener('pagehide',()=>{if(recorder?.state==='recording')recorder.stop();if(bleCapture)stopBLECapture();if(frameURL)URL.revokeObjectURL(frameURL);for(const entry of recordings)if(entry.url)URL.revokeObjectURL(entry.url);});
loadRecordings();cameraPoll();bluetoothPoll();
