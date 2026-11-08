"use strict";
// Authenticated beacon panel. Only /api/beacons sightings (verified, persisted) are
// shown as verified; everything else stays in diagnostics. No rescue targets.
(() => {
  const $ = id => document.getElementById(id);
  const el = (tag, cls, text) => {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text !== undefined) n.textContent = text;
    return n;
  };
  const ago = s => s < 1 ? "just now" : s < 120 ? `${Math.floor(s)} s ago` : `${Math.floor(s / 60)} min ago`;
  const REASON = {
    "replay:duplicate": "Replay · already-used token heard again",
    "replay:not_newer": "Replay · older than a token already accepted",
    "replay:stale": "Replay · token outside the time window (too old)",
    "replay:future": "Replay · token ahead of this receiver's clock",
    "forged:bad_tag": "Forged · enrolled alias, signature does not match",
    "unknown:unenrolled_alias": "Unknown · alias not enrolled here",
    "drop:framing": "Malformed · serial row not in the expected format",
    "drop:rssi_out_of_range": "Malformed · signal strength out of range",
    "drop:name_present": "Malformed · protocol token with a device name",
    "drop:length": "Malformed · wrong token length",
    "drop:reserved_alias": "Malformed · reserved alias 0",
    "error:halted": "Verification stopped",
    "ignored:receiver_not_ready": "Ignored · receiver had no fresh heartbeat",
    "not_processed:halted": "Not processed · verification stopped",
  };

  function banner(data) {
    const b = $("beacon-banner");
    b.className = "banner";
    b.hidden = !(data.source === "SIMULATED" || data.mode === "test-keys");
    if (data.source === "SIMULATED") {
      b.classList.add("sim");
      b.textContent = "SIMULATED · Synthetic serial input, simulator keys and separate replay state. Not hardware.";
    } else if (data.mode === "test-keys") {
      b.classList.add("test");
      b.textContent = "SYNTHETIC TEST KEYS · Labelled experiment. These keys are public; this is not a production enrollment.";
    }
  }

  function draw(data) {
    banner(data);
    $("beacon-mode").textContent = !data.source || data.source === data.mode_label ? data.mode_label
      : `${data.source} · ${data.mode_label}`;
    const r = data.receiver || {};
    const problem = data.status === "halted" || data.status === "receiver_unavailable";
    $("beacon-detail").className = `note${problem ? " warn" : ""}`;
    $("beacon-detail").textContent = data.status === "off" ? data.detail
      : `${data.detail} Receiver: ${r.status || "unknown"}. ${data.scope ? `Scope: ${data.scope}.` : ""}`;
    $("beacon-count").textContent = data.sightings.length;
    const grid = document.createDocumentFragment();
    for (const s of data.sightings) {
      const card = el("article", `beacon${s.stale ? " stale" : ""}`);
      const top = el("div", "signal-top");
      top.append(el("span", "signal-title", s.label), el("span", "verified", "AUTHENTICATED"));
      const when = el("div", "auth-age", `Last authenticated token ${ago(s.last_verified_age_s)}`);
      const meta = el("div", "classification",
        `${s.verified_tokens} verified token${s.verified_tokens === 1 ? "" : "s"} · window ${s.counter} · ${s.last_verified_utc}`);
      const strength = el("div", "strength");
      strength.append(el("strong", "", `${s.rssi} dBm`), el("span", "", "at last verification · not distance"));
      card.append(top, when, meta, strength);
      if (s.stale) card.append(el("div", "stale-note", `No new authenticated token for over ${data.stale_after_s} s. Kept as history.`));
      grid.append(card);
    }
    if (!data.sightings.length) grid.append(el("div", "empty", data.status === "off"
      ? "Verification is off. Nearby signals below remain unverified."
      : "No enrolled beacon has been authenticated in this session."));
    $("beacons").replaceChildren(grid);

    const counts = Object.entries(data.counts || {}).filter(([k]) => !k.startsWith("verified"));
    $("diag-total").textContent = counts.reduce((n, [, v]) => n + v, 0);
    const list = el("ul", "diag-counts");
    for (const [k, v] of counts) list.append(el("li", "", `${REASON[k] || (k.startsWith("drop:unsupported") ? "Unrelated BLE UUID (not this protocol)" : k)}: ${v}`));
    $("diag-counts").replaceChildren(list);
    const events = el("ol", "diag-events");
    for (const e of (data.events || []).filter(e => e.kind !== "verified").slice(0, 15)) {
      events.append(el("li", e.kind, `${ago(e.age_s)} · ${REASON[`${e.kind}:${e.reason}`] || `${e.kind}:${e.reason}`}`
        + (e.alias ? ` · alias ${e.alias}` : "") + (e.rssi !== null && e.rssi !== undefined ? ` · ${e.rssi} dBm` : "")));
    }
    if (!events.childElementCount) events.append(el("li", "", "No rejected events yet."));
    $("diag-events").replaceChildren(events);
  }

  async function poll() {
    try {
      const response = await fetch("/api/beacons", {cache: "no-store", signal: AbortSignal.timeout(4000)});
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      draw(await response.json());
    } catch (error) {
      $("beacon-detail").className = "note warn";
      $("beacon-detail").textContent = "Local server unreachable. Verified sightings shown are from the last successful update.";
    } finally {
      setTimeout(poll, 1000);
    }
  }
  poll();
})();
