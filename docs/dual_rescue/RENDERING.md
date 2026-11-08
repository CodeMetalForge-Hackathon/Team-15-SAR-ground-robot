# Rescue digital twin: rendering architecture and measured performance

`http://localhost:8000/rescue` (`scripts/run_dual_rescue.sh`). Source: `dashboard/static/rescue/`
(`index.html`, `app.js`, `scene.js`). three.js r160 and OrbitControls are vendored under `vendor/three/`
(MIT), so the page needs no CDN and works offline.

## Architecture

```
simulation (Python, deterministic 0.05 s ticks)  --POST /api/rescue/step {sim_s}-->  JSON snapshot
      ^ the browser asks for speed x 0.1 s of sim time every 100 ms; pausing = not asking
      |
app.js  : panels, timeline, event log, controls, cinematic triggers (from real coordinator messages)
scene.js: Three.js scene built from the layout + theme; agents interpolated between two snapshots
```

* **The renderer never decides anything.** Drone and rover poses are the simulation's
  `x, y, heading`, linearly interpolated between the last two snapshots so motion looks smooth.
  * Survivor markers come only from the coordinator's candidates.
  * Debris appears only once AIR-1 or GND-1 has observed it.
  * The planned route is the Navigator's current `route`.
  * The camera footprint square is the exact cell window the sim looked through.
  * Ground truth is drawn only when the viewer turns on **Simulator ground truth**, in grey with a
    GROUND TRUTH label.
* **Environment geometry is procedural, from the simulated layout.**
  * A 1 m occupancy grid marks space within `corridor_half_m` + 0.45 m of a corridor, or near a room
    pocket, as free.
  * Everything else becomes theme geometry in a single `InstancedMesh`: broken walls and collapsed blocks
    (urban), racks and boxes (warehouse), hospital walls (corridors), trees and rocks (outdoor), broken
    concrete walls (maze).
  * Zones from the scenario (intact roof, smoke, mezzanine, canopy) are drawn as what the drone cannot
    see through. Canopy zones get dense trees.
  * Robot models are drawn ×2.2–3.5 scale for visibility; the legend says so.
* **Colours mean one thing each:**
  * cyan: aerial observation, coverage, candidate
  * blue: ground route and traversed corridors
  * hatched amber: UNKNOWN / STALE / OCCLUDED (never drawn as clear)
  * red: BLOCKED, hazard, safety stop
  * green: reached at standoff, staging
  * purple: model advisory (Qwen)
* **Cameras:** tactical, cinematic, aerial follow, ground follow, drone view (a render of the simulated
  world from the drone's pose, *not* a sensor feed), top-down, and free orbit (OrbitControls). The
  cinematic camera reacts to real coordinator events (SURVIVOR, ASSIGN, OBSTACLE, REROUTE, REACHED,
  FAULT…) and never skips simulation steps.
* **Presets:**

  | Preset | Pixel ratio | Shadows | Fog |
  |---|---|---|---|
  | Low | 0.75 | none | none |
  | Medium | 1.0 | 1024 | on |
  | High | ≤ 1.5 | 2048 | on |
  | Ultra / 4K | ≤ 2.0 | 4096 | on |

  An adaptive render scale lowers the internal resolution in 0.15 steps, down to 0.5, when the p95
  frame time exceeds 40 ms. It raises it again when p95 drops below 18 ms.
* **Telemetry panel:** FPS, mean and p95 frame time over 240 frames, draw calls, triangles, internal
  render resolution, render scale, preset, simulation tick rate, and the GPU string from
  `WEBGL_debug_renderer_info`.

## Measured performance

Measured with Chrome headless driven by Playwright (`--use-angle=metal`, device scale factor 1) on an
Apple M4 Pro. GPU string: `ANGLE (Apple, ANGLE Metal Renderer: Apple M4 Pro)`. Scenario B ran at 20×
with the server simulating at the same time. Values were read from the page's own telemetry after
10 s.

| Viewport | Preset | Internal 3D resolution | FPS | Mean frame | p95 frame | Draw calls | Triangles |
|---|---|---|---|---|---|---|---|
| 1920 × 1080 | High | 1190 × 823 | 60.0 | 16.66 ms | 17.3 ms | 154 | 20.8 k |
| 2560 × 1440 | High | 1587 × 1101 | 59.8 | 16.71 ms | 16.8 ms | 154 | 20.8 k |
| 3840 × 2160 | High | 2600 × 1675 | 59.0 | 16.94 ms | 16.8 ms | 154 | 20.8 k |
| 3840 × 2160 | Ultra (4096 shadows) | 2600 × 1675 | 60.0 | 16.66 ms | 17.6 ms | 154 | 20.8 k |
| 3840 × 2160 | Ultra, **presentation mode** (3D fills the screen) | **3840 × 2086** | 60.0 | 16.67 ms | 16.8 ms | 111 | 19.0 k |

Every other scene (A cinematic, C, D, K, O, M, E, W drone view) measured 59.8–60.0 FPS with p95 at or
below 17.5 ms at 1080p.

What these numbers do and do not show:

* 60 FPS is the browser's vsync cap, so the GPU headroom above 60 FPS was **not** measured.
* "4K" means a 3840 × 2160 viewport. Only presentation mode renders a near-native 3840 × 2086 3D canvas.
  With the sidebars open, the 3D view itself is 2600 × 1675.
* Other GPUs (a projector laptop, integrated graphics) were not measured. Adaptive scaling and the Low
  preset exist for them.

## Visual checks performed

Screenshots of the real rendered page are in `docs/dual_rescue/screenshots/` (PNG, gitignored by the
repository's no-photos rule; regenerate them with the Playwright script). They cover 13 views: 1080p,
1440p and 4K; presentation mode; urban, warehouse drone view, corridors ground follow, outdoor, maze
top-down, roofed C, multi-survivor D, and comms fault E.

Two problems were found by looking at the renders and fixed:

* Urban blocks hid the corridors and the rover. Urban walls are now broken boundary walls at
  1.3–3.0 m.
* Warehouse racks were too saturated. They now use a steel-blue rack colour with smaller boxes.

Not covered by automated tests: the 3D frame contents (judged visually), and mobile layouts below 900 px
(the side panels hide).

## Limitations

* There are no glTF assets. All models are procedural primitives.
* There is no post-processing (bloom, SSAO). ACES tone mapping, soft shadows and fog are used instead.
* Altitude is a constant 15 m display value. Takeoff and landing are not simulated, so they are not
  animated. The rover never strafes (the Navigator does not command it), so no strafe animation is
  shown.
