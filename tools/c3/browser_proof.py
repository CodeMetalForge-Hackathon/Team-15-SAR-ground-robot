"""C3 browser proof (SIMULATED): real Chrome renders the dashboard served by ble_sim.

    python3 tools/c3/browser_proof.py REPO_ROOT OUTDIR RUN_CARD_HTML

Starts `python3 -m ble_sim serve` (private pty, simulator keys, own state), opens a
run card (actual run ID, revision, test log), then the dashboard for one full
40-second schedule cycle. Records the browser to video, takes screenshots, and
checks the DOM. Everything shown is SIMULATED; this is not hardware proof.
"""
import json, subprocess, sys, tempfile, time
from pathlib import Path
from playwright.sync_api import sync_playwright

root, out, card = Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve(), Path(sys.argv[3]).resolve()
out.mkdir(parents=True, exist_ok=True)
state = tempfile.mkdtemp(prefix="olf-sim-proof-")
sim = subprocess.Popen([sys.executable, "-B", "-m", "ble_sim", "serve", "--port", "8766", "--state-dir", state],
                       cwd=root, stdout=open(out / "sim_server.log", "w"), stderr=subprocess.STDOUT)
checks, t_start = {}, time.monotonic()
try:
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", headless=True)
        ctx = b.new_context(viewport={"width": 1440, "height": 900}, record_video_dir=str(out / "video"),
                            record_video_size={"width": 1440, "height": 900})
        page = ctx.new_page()
        page.goto(card.as_uri())
        page.wait_for_timeout(6000)
        page.goto("http://127.0.0.1:8766/")
        page.wait_for_selector(".beacon .verified", timeout=20000)
        checks["first_authenticated_card_s_after_sim_start"] = round(time.monotonic() - t_start, 2)
        page.screenshot(path=str(out / "01_first_verified.png"))
        checks["banner"] = page.inner_text("#beacon-banner")
        checks["mode_tag"] = page.inner_text("#beacon-mode")
        checks["connection"] = page.inner_text("#connection")
        checks["first_card"] = page.inner_text(".beacon")
        page.wait_for_timeout(4000)
        page.click("details.diagnostics summary")
        seen_phases = set()
        for i in range(44):                                   # one full 40 s cycle and a bit
            page.wait_for_timeout(1000)
            api = json.loads(page.evaluate("fetch('/api/beacons').then(r => r.text())"))
            seen_phases.add(tuple(sorted(api["counts"])))
            if i in (10, 22, 40):
                page.screenshot(path=str(out / f"0{2 + (i > 10) + (i > 22)}_cycle_{i:02d}s.png"), full_page=True)
        page.locator("details.diagnostics").scroll_into_view_if_needed()
        page.screenshot(path=str(out / "05_diagnostics.png"), full_page=True)
        api = json.loads(page.evaluate("fetch('/api/beacons').then(r => r.text())"))
        disc = json.loads(page.evaluate("fetch('/api/discovery').then(r => r.text())"))
        checks.update(api_counts=api["counts"], api_sightings=api["sightings"], api_source=api["source"],
                      api_mode=api["mode"], receiver=api["receiver"],
                      nearby_panel=page.inner_text("#signals"), diagnostics_text=page.inner_text("details.diagnostics"),
                      discovery_source=disc["source"], discovery_signals=len(disc["signals"]))
        video = page.video.path()
        ctx.close()
        b.close()
    checks["video_webm"] = Path(video).name
finally:
    sim.terminate()
    sim.wait(timeout=5)
need = ["verified:fresh", "replay:duplicate", "replay:stale", "replay:future", "forged:bad_tag",
        "unknown:unenrolled_alias", "drop:framing", "drop:rssi_out_of_range", "drop:name_present"]
checks["assertions"] = {
    "SIMULATED banner visible": "SIMULATED" in checks["banner"],
    "header never says LIVE for simulated data": "LIVE" not in checks["connection"]
        and "NOT HARDWARE" in checks["connection"],
    "card says AUTHENTICATED": "AUTHENTICATED" in checks["first_card"],
    "API source SIMULATED": checks["api_source"] == "SIMULATED" and checks["discovery_source"] == "SIMULATED",
    "all outcome kinds seen": all(k in checks["api_counts"] for k in need),
    "nearby signals stay UNVERIFIED": "UNVERIFIED" in checks["nearby_panel"],
    "Apple hint shown as possible only": "Possible Apple device" in checks["nearby_panel"],
    "diagnostics list forged/replay/unknown/malformed": all(w in checks["diagnostics_text"] for w in
                                                            ("Forged", "Replay", "Unknown", "Malformed")),
    "sighting kept through loss": len(checks["api_sightings"]) >= 1,
}
(out / "browser_checks.json").write_text(json.dumps(checks, indent=1))
print(json.dumps(checks["assertions"], indent=1))
sys.exit(0 if all(checks["assertions"].values()) else 1)
