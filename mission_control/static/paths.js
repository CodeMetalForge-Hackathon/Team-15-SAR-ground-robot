'use strict';
let pathsData=null,pathsVisible=false,pathsBusy=false,pathsOnline=false;
const pathNames={crazyflie:'Drone',rover:'Rover'},pathColors={crazyflie:'var(--accent-signal)',rover:'var(--surface-olive)'};
const svgNS='http://www.w3.org/2000/svg';
function svgNode(tag,attrs={},text=''){
  const node=document.createElementNS(svgNS,tag);for(const [key,value]of Object.entries(attrs))node.setAttribute(key,String(value));node.textContent=text;return node;
}
function plotSVG(width,height,label){return svgNode('svg',{viewBox:`0 0 ${width} ${height}`,role:'img','aria-label':label});}
function numberLabel(value){return Math.abs(value)<0.00001?'0':Number(value.toFixed(2)).toString();}
function segments(points){
  const groups=[];for(const point of points){if(!groups.length||groups.at(-1).at(-1).segment!==point.segment)groups.push([]);groups.at(-1).push(point);}return groups;
}
function line(svg,points,color,project,dashed=false){
  for(const group of segments(points)){
    if(group.length<2)continue;
    svg.append(svgNode('polyline',{points:group.map(p=>project(p).join(',')).join(' '),fill:'none',stroke:color,'stroke-width':2,'stroke-dasharray':dashed?'5 3':'none','vector-effect':'non-scaling-stroke'}));
  }
}
function drawXY(data){
  const width=640,height=320,pad=42,svg=plotSVG(width,height,'Drone and rover XY paths relative to the Jetson origin. X forward, Y left. Meters.');
  const points=Object.values(data.tracks).flatMap(t=>t.points);
  const xs=[-1,1,...points.map(p=>p.x)],ys=[-1,1,...points.map(p=>p.y)];
  const minX=Math.min(...xs)-0.25,maxX=Math.max(...xs)+0.25,minY=Math.min(...ys)-0.25,maxY=Math.max(...ys)+0.25;
  const scale=Math.min((width-2*pad)/(maxX-minX),(height-2*pad)/(maxY-minY));
  const cx=(maxX+minX)/2,cy=(maxY+minY)/2,project=p=>[width/2+(p.x-cx)*scale,height/2-(p.y-cy)*scale];
  const [ox,oy]=project({x:0,y:0});
  const extent=Math.max(maxX-minX,maxY-minY),raw=extent/6,magnitude=10**Math.floor(Math.log10(raw)),step=[1,2,5,10].map(n=>n*magnitude).find(n=>n>=raw);
  for(let x=Math.ceil(minX/step)*step;x<=maxX;x+=step){const [px]=project({x,y:0});svg.append(svgNode('line',{x1:px,y1:pad/2,x2:px,y2:height-pad,stroke:'var(--border-tactical)','stroke-width':0.5}),svgNode('text',{x:px,y:height-20,'text-anchor':'middle'},numberLabel(x)));}
  for(let y=Math.ceil(minY/step)*step;y<=maxY;y+=step){const [,py]=project({x:0,y});svg.append(svgNode('line',{x1:pad,y1:py,x2:width-pad/2,y2:py,stroke:'var(--border-tactical)','stroke-width':0.5}),svgNode('text',{x:pad-8,y:py+3,'text-anchor':'end'},numberLabel(y)));}
  svg.append(svgNode('line',{x1:pad,y1:oy,x2:width-pad/2,y2:oy,stroke:'var(--surface-olive)','stroke-width':1}),svgNode('line',{x1:ox,y1:pad/2,x2:ox,y2:height-pad,stroke:'var(--surface-olive)','stroke-width':1}));
  for(const [name,track]of Object.entries(data.tracks)){
    line(svg,track.points,pathColors[name],project,name==='rover');
    if(!track.latest)continue;
    const [x,y]=project(track.latest),fresh=connected&&pathsOnline&&track.status==='tracking';
    const marker=name==='rover'?svgNode('path',{d:`M ${x} ${y-6} L ${x+6} ${y} L ${x} ${y+6} L ${x-6} ${y} Z`}):svgNode('circle',{cx:x,cy:y,r:7});
    marker.setAttribute('fill',fresh?pathColors[name]:'var(--bg-canvas)');marker.setAttribute('stroke',pathColors[name]);marker.setAttribute('stroke-width','2');
    marker.append(svgNode('title',{},`${pathNames[name]}: ${numberLabel(track.latest.x)}, ${numberLabel(track.latest.y)}, ${numberLabel(track.latest.z)} m · ${track.mode} · ${fresh?'current':'last known'}`));svg.append(marker);
  }
  svg.append(svgNode('rect',{x:ox-3,y:oy-3,width:6,height:6,fill:'var(--text-stencil)'}),svgNode('text',{x:ox+10,y:oy-12},'Jetson (0, 0)'),svgNode('text',{x:width-22,y:height-5,'text-anchor':'end'},'+X forward · m'),svgNode('text',{x:pad,y:12},'+Y left · m'));
  $('xy-map').replaceChildren(svg);
}
function drawTime(data,container,metric,label){
  const width=320,height=126,pad={left:35,right:12,top:10,bottom:27},svg=plotSVG(width,height,label);
  const tracks=Object.entries(data.tracks).filter(([,t])=>t.points.length),all=tracks.flatMap(([,t])=>t.points);
  const start=all.length?Math.min(...all.map(p=>p.t)):0,end=all.length?Math.max(start+1,...all.map(p=>p.t)):1;
  const values=all.map(metric),low=Math.min(0,...values),high=Math.max(1,...values),spread=high-low;
  const project=p=>[pad.left+(p.t-start)/(end-start)*(width-pad.left-pad.right),height-pad.bottom-(metric(p)-low)/spread*(height-pad.top-pad.bottom)];
  for(let i=0;i<=2;i++){
    const value=low+spread*i/2,y=height-pad.bottom-i/2*(height-pad.top-pad.bottom);
    svg.append(svgNode('line',{x1:pad.left,y1:y,x2:width-pad.right,y2:y,stroke:'var(--border-tactical)','stroke-width':0.5}),svgNode('text',{x:pad.left-5,y:y+3,'text-anchor':'end'},numberLabel(value)));
  }
  for(const [name,track]of tracks){line(svg,track.points,pathColors[name],project,name==='rover');const [x,y]=project(track.points.at(-1));svg.append(svgNode('circle',{cx:x,cy:y,r:2.5,fill:pathColors[name]}));}
  svg.append(svgNode('text',{x:pad.left,y:height-9},numberLabel(start)+'s'),svgNode('text',{x:width-pad.right,y:height-9,'text-anchor':'end'},numberLabel(end)+'s'));
  $(container).replaceChildren(svg);
}
function renderPaths(){
  $('apply-frame').disabled=!connected||!session||!state?.paused;
  $('export-paths').disabled=!pathsData;
  const data=pathsData||{tracks:{rover:{points:[],status:'no_position'},crazyflie:{points:[],status:'no_position'}}};
  drawXY(data);drawTime(data,'altitude-chart',p=>p.z,'Drone and rover altitude over mission time, meters');drawTime(data,'distance-chart',p=>Math.hypot(p.x,p.y,p.z),'Distance of drone and rover from Jetson origin over mission time, meters');
  $('track-status').replaceChildren();
  const statuses={tracking:'Tracking',no_position:'No position',unaligned:'Needs alignment',invalid:'Invalid position',stale:'Stale',awaiting_position:'Waiting for position'};
  for(const [name,track]of Object.entries(data.tracks)){
    const card=element('div','','track-card'),status=connected&&pathsOnline?(statuses[track.status]||'No position'):'Offline';
    card.append(element('strong',pathNames[name]+' · '+status),element('small',[...new Set([track.mode,track.source].filter(Boolean))].join(' · ')));
    if(track.latest)card.append(element('span',[track.latest.x,track.latest.y,track.latest.z].map(numberLabel).join(' / ')+' m'));
    $('track-status').append(card);
  }
}
function switchView(paths){
  pathsVisible=paths;$('paths-stage').hidden=!paths;$('camera-stage').hidden=paths;
  $('view-camera').setAttribute('aria-pressed',String(!paths));$('view-paths').setAttribute('aria-pressed',String(paths));
  if(paths){renderPaths();pollPaths();}
}
async function pollPaths(){
  if(!pathsVisible||!token||pathsBusy)return;pathsBusy=true;
  try{pathsData=await api('tracks');pathsOnline=true;renderPaths();}catch{pathsOnline=false;renderPaths();}finally{pathsBusy=false;}
}
function fillFrame(){
  const frame=pathsData?.tracks[$('frame-node').value]?.calibration;
  for(const [index,axis]of ['x','y','z'].entries())$('frame-'+axis).value=frame?.translation_m[index]??0;
  $('frame-yaw').value=frame?.yaw_deg??0;
}
$('view-camera').addEventListener('click',()=>switchView(false));$('view-paths').addEventListener('click',()=>switchView(true));
$('frame-node').addEventListener('change',fillFrame);
$('frame-form').addEventListener('submit',async event=>{
  event.preventDefault();try{await api('frame',{node:$('frame-node').value,translation_m:['x','y','z'].map(a=>Number($('frame-'+a).value)),yaw_deg:Number($('frame-yaw').value)});await pollPaths();notice('Alignment applied; trail reset');}catch(error){notice(error.message);}
});
$('export-paths').addEventListener('click',()=>{
  if(!pathsData)return;const blob=new Blob([JSON.stringify({...pathsData,exported_at:new Date().toISOString(),coordinator_connected:connected&&pathsOnline},null,2)],{type:'application/json'}),url=URL.createObjectURL(blob),link=element('a');link.href=url;link.download='jetson-paths-'+new Date().toISOString().replace(/[:.]/g,'-')+'.json';link.click();setTimeout(()=>URL.revokeObjectURL(url),1000);
});
setInterval(()=>{if(pathsVisible){renderPaths();pollPaths();}},500);
