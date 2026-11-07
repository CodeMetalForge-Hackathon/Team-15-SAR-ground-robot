"use strict";
const $ = id => document.getElementById(id);
let current = null, stream = null;
const node = (tag, cls, text) => {
  const el = document.createElement(tag);
  if (cls) el.className = cls;
  if (text !== undefined) el.textContent = text;
  return el;
};
const ageText = seconds => seconds < 1 ? "just now" : `${Math.floor(seconds)} s ago`;

function historyChart(signal) {
  const ns = "http://www.w3.org/2000/svg";
  const svg = document.createElementNS(ns, "svg");
  svg.setAttribute("viewBox", "0 0 300 64");
  svg.setAttribute("role", "img");
  svg.setAttribute("aria-label", `${signal.label}: received signal history over 30 seconds; vertical range −110 to −20 dBm`);
  const append = (tag, attrs) => {
    const child = document.createElementNS(ns, tag);
    for (const [k, v] of Object.entries(attrs)) child.setAttribute(k, v);
    svg.append(child);
  };
  for (const y of [8, 32, 56]) append("line", {x1:0,y1:y,x2:300,y2:y,stroke:"#29373e","stroke-dasharray":"2 5"});
  const position = ([age, rssi]) => [300 * (1 - Math.max(0, Math.min(30, age)) / 30), 56 - (Math.max(-110, Math.min(-20,rssi)) + 110) / 90 * 48];
  let previous = null;
  for (const sample of signal.history) {
    const [x,y] = position(sample);
    if (previous && previous[0] - sample[0] <= 3) {
      const [px,py] = position(previous);
      append("line", {x1:px,y1:py,x2:x,y2:y,stroke:"#b8ef93","stroke-width":1.8});
    }
    append("circle", {cx:x,cy:y,r:1.8,fill:"#b8ef93"});
    previous = sample;
  }
  return svg;
}

function draw() {
  if (!current) return;
  const data = current;
  const live = data.status === "scanning";
  $("connection").className = `connection${live ? " live" : ""}`;
  $("connection").textContent = live ? "LIVE USB · Passive scanning" : `Receiver ${data.status}`;
  $("active").textContent = live ? data.active : "—";
  $("packets").textContent = data.packets.toLocaleString();
  $("latest").textContent = data.last_packet_age_s === null ? "—" : `${Math.floor(data.last_packet_age_s)} s`;
  $("receiver-detail").textContent = `${data.detail}${data.malformed ? ` · ${data.malformed} malformed packets ignored` : ""}`;
  const filter = $("filter").value;
  const signals = data.signals.filter(s => filter === "all" || (filter === "active" ? !s.stale : s.classification === "Possible Apple device"));
  $("count").textContent = signals.length;
  $("signals").classList.toggle("offline", !live);
  const fragment = document.createDocumentFragment();
  for (const signal of signals) {
    const card = node("article", `signal${signal.stale ? " stale" : ""}`);
    const top = node("div", "signal-top");
    top.append(node("span", "signal-title", signal.label), node("span", "age", `${signal.stale ? "Last heard " : "Heard "}${ageText(signal.age_s)}`));
    const classification = node("div", "classification", signal.classification);
    classification.title = signal.hint;
    classification.append(node("span", "unverified", "UNVERIFIED"));
    card.append(top, classification);
    if (signal.name) card.append(node("div", "advertised-name", `Advertised name: ${signal.name}`));
    const strength = node("div", "strength");
    strength.append(node("strong", "", `${signal.rssi} dBm`), node("span", "", `${signal.count.toLocaleString()} advertisements`));
    const labels = node("div", "chart-label");
    labels.append(node("span", "", "30 s ago"), node("span", "", "−110 to −20 dBm"), node("span", "", "now"));
    card.append(strength, historyChart(signal), labels);
    fragment.append(card);
  }
  if (!signals.length) fragment.append(node("div", "empty", !live ? "Waiting for the USB receiver. No sample devices are shown." : filter !== "all" ? "No signals match this filter." : "Scanning. No advertisements heard in the last 60 seconds."));
  $("signals").replaceChildren(fragment);
}

async function poll() {
  try {
    const response = await fetch("/api/discovery", {cache:"no-store", signal:AbortSignal.timeout(4000)});
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    current = await response.json();
    draw();
  } catch (error) {
    $("connection").className = "connection";
    $("connection").textContent = "Local server unreachable";
    $("receiver-detail").textContent = "Connection lost. Displayed signals are from the last successful update.";
    $("active").textContent = "—";
    $("signals").classList.add("offline");
  } finally {
    setTimeout(poll, 1000);
  }
}
$("filter").addEventListener("change", draw);
function stopCamera() {
  if (stream) stream.getTracks().forEach(track => track.stop());
  stream = null;
  $("video").srcObject = null;
  $("video").hidden = $("video-label").hidden = true;
  $("camera-placeholder").hidden = false;
  $("camera-toggle").textContent = "Enable camera";
  $("camera-status").textContent = "Camera is off.";
}
$("camera-toggle").addEventListener("click", async () => {
  if (stream) { stopCamera(); return; }
  $("camera-toggle").disabled = true;
  try {
    if (!navigator.mediaDevices?.getUserMedia) throw new Error("Camera access is unavailable in this browser.");
    stream = await navigator.mediaDevices.getUserMedia({video:true,audio:false});
    $("video").srcObject = stream;
    $("video").hidden = $("video-label").hidden = false;
    $("camera-placeholder").hidden = true;
    $("camera-toggle").textContent = "Turn camera off";
    $("camera-status").textContent = "Local preview only · not recorded";
    stream.getVideoTracks()[0].addEventListener("ended", stopCamera);
  } catch (error) {
    stopCamera();
    $("camera-status").textContent = `Camera unavailable: ${error.message}`;
  } finally { $("camera-toggle").disabled = false; }
});
window.addEventListener("pagehide", stopCamera);
poll();
