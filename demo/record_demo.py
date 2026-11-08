"""Record the dual-robot rescue SIMULATION demo video from a real browser session.

    python3 -m dashboard.serve --port 8012 --qwen-url http://127.0.0.1:8090      # no --rescue-evidence-dir
    python3 demo/record_demo.py http://localhost:8012 /tmp/frames                 # needs: pip install playwright
    # then assemble the frames with ffmpeg (see demo/DEMO.md)

What this does: opens /rescue in Chrome (GPU, 1920 x 1080), runs scenario B (dynamic debris) and captures
the page's compositor frames over the Chrome DevTools screencast. The choreography changes only the
simulation SPEED, the CAMERA and an on-screen CAPTION. Every caption change waits for the real simulation
event it describes (a message from the coordinator or a phase change). Nothing in the mission is scripted:
the drone, the rover, the debris event, the stop, the replan and the Qwen report all come from the
simulation and services that the dashboard normally uses.

The recording server must run WITHOUT --rescue-evidence-dir, so that no real camera frame (which might
show a person) can appear in the video.
"""
from __future__ import annotations

import asyncio
import base64
import json
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8012"
OUT = Path(sys.argv[2] if len(sys.argv) > 2 else "frames")
W, H = 1920, 1080

INJECT = r"""
(() => {
  const css = document.createElement('style');
  css.textContent = `
    .toast{bottom:84px!important}
    #simBanner{position:absolute;left:50%;bottom:16px;transform:translateX(-50%);z-index:20;pointer-events:none;
      font:700 20px/1.2 Inter,system-ui,sans-serif;letter-spacing:.06em;color:#f2b33d;background:rgba(11,15,20,.88);
      border:2px solid #f2b33d;border-radius:8px;padding:8px 18px;white-space:nowrap}
    #simCaption{position:absolute;left:16px;top:132px;z-index:20;max-width:56%;pointer-events:none;
      font:600 19px/1.38 Inter,system-ui,sans-serif;color:#e8edf3;background:rgba(11,15,20,.82);
      border-left:4px solid #35d0e0;border-radius:6px;padding:10px 14px;transition:opacity .35s}
    #simCaption b{color:#35d0e0} #simCaption i{color:#f2b33d;font-style:normal}
    #simCard{position:fixed;inset:0;z-index:50;display:none;align-items:center;justify-content:center;
      background:rgba(8,11,15,.86);backdrop-filter:blur(3px)}
    #simCard div{max-width:1300px;text-align:center;font:600 30px/1.45 Inter,system-ui,sans-serif;color:#e8edf3}
    #simCard h1{font-size:46px;letter-spacing:.08em;margin:0 0 18px;color:#35d0e0}
    #simCard .w{color:#f2b33d;font-size:28px;margin-top:22px}
    #simCard .s{color:#aab6c4;font-size:22px;margin-top:14px}`;
  document.head.appendChild(css);
  const view = document.getElementById('view');
  const b = document.createElement('div'); b.id = 'simBanner'; b.textContent = 'SIMULATION — NO PHYSICAL ROBOT MOVEMENT'; view.appendChild(b);
  const c = document.createElement('div'); c.id = 'simCaption'; view.appendChild(c);
  const k = document.createElement('div'); k.id = 'simCard'; k.innerHTML = '<div></div>'; document.body.appendChild(k);
  window.__demo = {
    caption(html){ const e = document.getElementById('simCaption'); e.style.opacity = 0; setTimeout(() => { e.innerHTML = html; e.style.opacity = 1; }, 350); },
    card(html){ const e = document.getElementById('simCard'); e.firstChild.innerHTML = html; e.style.display = html ? 'flex' : 'none'; },
    speed(v){ const s = document.getElementById('speed'); if (![...s.options].some(o => o.value == v)) { const o = document.createElement('option'); o.value = o.text = v; s.appendChild(o); }
      s.value = String(v); s.dispatchEvent(new Event('change')); },
    cam(m){ document.querySelector(`[data-cam="${m}"]`).click(); },
    layer(n, on){ const e = document.querySelector(`[data-l="${n}"]`); if (e.checked !== on) e.click(); },
    msgs(){ return [...document.querySelectorAll('#log .msg')].map(d => d.textContent); },
  };
})();
"""


async def main():
    OUT.mkdir(parents=True, exist_ok=True)
    stamps = []
    async with async_playwright() as p:
        browser = await p.chromium.launch(channel="chrome", headless=True,
                                          args=["--enable-gpu", "--ignore-gpu-blocklist", "--use-angle=metal"])
        page = await browser.new_page(viewport={"width": W, "height": H}, device_scale_factor=1)
        await page.goto(f"{BASE}/rescue?scenario=B&speed=4&quality=high")
        await page.wait_for_function("window.__rescue && window.__rescue.state && window.__rescue.state.t === 0")
        await page.evaluate(INJECT)
        await page.wait_for_timeout(1500)

        cdp = await page.context.new_cdp_session(page)
        n = {"i": 0}

        def on_frame(params):
            n["i"] += 1
            (OUT / f"f{n['i']:06d}.jpg").write_bytes(base64.b64decode(params["data"]))
            stamps.append(params["metadata"]["timestamp"])
            asyncio.ensure_future(cdp.send("Page.screencastFrameAck", {"sessionId": params["sessionId"]}))

        cdp.on("Page.screencastFrame", on_frame)
        await cdp.send("Page.startScreencast", {"format": "jpeg", "quality": 88, "maxWidth": W, "maxHeight": H,
                                                "everyNthFrame": 1})
        t0 = time.time()
        log = []

        async def ev(js):
            return await page.evaluate(js)

        async def say(html, hold=0.0):
            await ev(f"window.__demo.caption({json.dumps(html)})")
            log.append((round(time.time() - t0, 1), html))
            if hold:
                await page.wait_for_timeout(int(hold * 1000))

        async def until_msg(kind, text="", timeout=120):
            # wait for a real coordinator message (type + text) in the agent-communication log
            js = f"window.__demo.msgs().some(m => m.includes({json.dumps(kind)}) && m.includes({json.dumps(text)}))"
            await page.wait_for_function(js, timeout=timeout * 1000, polling=100)

        async def until(js, timeout=120):
            await page.wait_for_function(js, timeout=timeout * 1000, polling=100)

        # 0. intro (not running yet)
        await ev("window.__demo.cam('tactical')")
        await say("<b>Team-15 dual-robot search &amp; rescue</b> — a collapsed building (synthetic 48 m site). "
                  "<b>AIR-1</b> aerial scout + <b>GND-1</b> RoverC-Pro, both running our real planners. "
                  "Corridors start <i>UNKNOWN</i> (hatched amber).", 4.5)
        # 1. aerial search
        await ev("window.__demo.speed(4)")
        await ev("document.getElementById('bStart').click()")
        await ev("window.__demo.cam('aerial')")
        await say("<b>1 · Aerial search</b> — AIR-1 plans every move with our PR #17 Monte-Carlo tree search over a "
                  "probability map. The cyan square is its real camera footprint.")
        await until_msg("SURVIVOR", "POSSIBLE")
        await say("<b>2 · Survivor candidate</b> — reported only because it fell inside the footprint. "
                  "AIR-1 hovers three looks to confirm (Bayes confidence).")
        await until_msg("SURVIVOR", "LIKELY")
        await ev("window.__demo.cam('tactical')")
        await say("<b>3 · Shared map + route check</b> — before dispatch, the coordinator has the drone observe the "
                  "rover's route. Debris it saw on M1-N1 is avoided.")
        await until_msg("ASSIGN")
        await ev("window.__demo.speed(8)")
        await ev("window.__demo.cam('ground')")
        await say("<b>4 · Handoff</b> — GND-1 drives with our real Navigator + safety supervisor, on corridors "
                  "observed <b>CLEAR</b> only (blue chevrons = its Dijkstra route).", 5.0)
        await ev("window.__demo.cam('tactical')")
        await until("window.__rescue.state.t >= 88", timeout=60)
        await ev("window.__demo.speed(3)")
        await ev("window.__demo.layer('truth', true)")
        await say("<b>5 · Dynamic event</b> — the simulator drops debris on the planned corridor. "
                  "The agents are <i>not told</i> (grey = ground truth, shown to the viewer only).")
        await until_msg("EVENT", "debris")
        await ev("window.__demo.cam('ground')")
        await until_msg("OBSTACLE", "ultrasonic")
        await say("<b>6 · Obstacle</b> — the rover's ultrasonic stops it: STOP → VERIFY (3 readings) → "
                  "MARK BLOCKED → SCAN. The drone is tasked to re-check the block.")
        await until_msg("REQUEST_SENSING")
        await ev("window.__demo.cam('tactical')")
        await say("<b>7 · Cooperation</b> — no KNOWN-clear detour (its observations are stale), so the rover "
                  "<i>holds</i> and requests sensing. AIR-1 observes the detour.")
        await until_msg("REROUTE")
        await say("<b>8 · Replan</b> — the Navigator replans with Dijkstra over corridors now observed CLEAR, "
                  "then retreats along a verified path.", 3.0)
        await ev("window.__demo.layer('truth', false)")
        await ev("window.__demo.speed(14)")
        await ev("window.__demo.cam('cinematic')")
        await say("<b>9 · Rescue approach</b> — GND-1 follows the detour to the survivor's room.")
        await until_msg("REACHED", timeout=150)
        await ev("window.__demo.cam('ground')")
        await say("<b>10 · Safety decision</b> — at the standoff the rover's camera (simulated) sees the survivor. "
                  "The rover <i>stops</i>: the sighting stays UNCONFIRMED until a human reviews it.", 4.0)
        # the report panel (not the cached step state) shows when Qwen (or the labelled fallback) has answered
        await until("/QWEN_GUARDED|QWEN_FELL_BACK|FALLBACK|NOT_CONFIGURED/.test(document.getElementById('qStatus').textContent)",
                    timeout=60)
        await ev("window.__demo.cam('tactical')")
        await say("<b>11 · Rescue intelligence</b> (right panel) — Qwen3.5-2B + RAG explains the mission from "
                  "timestamped observation ids. <i>Advisory only</i>: no motor authority.", 6.0)
        await ev("""window.__demo.card(`<h1>TEAM-15 · RESCUE INTELLIGENCE DIGITAL TWIN</h1>
          Aerial scout + ground rover cooperate through a shared map.<br>Real Team-15 planners · deterministic safety ·
          Qwen advisory only
          <div class="s">Validated in simulation: 565 tests · 1540 / 1540 benchmark runs · 0 collisions ·
          0 entries into UNKNOWN corridors</div>
          <div class="w">SIMULATION — NO PHYSICAL ROBOT MOVEMENT · no real drone flight</div>`)""")
        await page.wait_for_timeout(5500)
        await cdp.send("Page.stopScreencast")
        await page.wait_for_timeout(300)
        state = await ev("({t: window.__rescue.state.t, phase: window.__rescue.state.phase, "
                         "report: document.getElementById('qStatus').textContent})")
        await browser.close()
    (OUT / "timestamps.json").write_text(json.dumps({"stamps": stamps, "captions": log, "final_state": state}))
    span = stamps[-1] - stamps[0] if stamps else 0
    print(json.dumps({"frames": len(stamps), "seconds": round(span, 1), "fps": round(len(stamps) / span, 1) if span else 0,
                      "final_state": state}, indent=1))


if __name__ == "__main__":
    asyncio.run(main())
