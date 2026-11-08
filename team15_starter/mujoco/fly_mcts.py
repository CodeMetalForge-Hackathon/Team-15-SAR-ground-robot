"""fly_mcts.py — the physical layer: a drone flies the MCTS plan in MuJoCo."""
from __future__ import annotations
import os, sys, argparse, time
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from sar.sar_core import World
from sar.planners import MCTS
from sar.sensors import apply

import mujoco

ALT = 1.0
SPEED = 0.18
TOL = 0.18
RENDER_EVERY = 4


def cell_xy(cell, n):
    i, j = cell
    return (float(j), float(n - 1 - i))


def build_xml(world):
    n = world.n
    ob5 = []
    for i in range(n):
        for j in range(n):
            if world.obstacles[i, j]:
                x, y = cell_xy((i, j), n)
                ob5.append(
                    f'<geom type="box" pos="{x} {y} 0.4" size="0.45 0.45 0.4" '
                    f'rgba="0.35 0.37 0.42 1"/>')
    people = []
    for idx, p in enumerate(world.people):
        x, y = cell_xy(p, n)
        people.append(
            f'<geom name="person{idx}" type="sphere" pos="{x} {y} 0.25" '
            f'size="0.35" rgba="0.95 0.95 0.98 1"/>')
    cx = (n - 1) / 2.0
    xml = f"""
<mujoco model="team15_sar">
  <option gravity="0 0 0" timestep="0.01"/>
  <visual><global offwidth="900" offheight="900"/></visual>
  <asset>
    <texture name="grid" type="2d" builtin="checker" rgb1="0.15 0.18 0.22"
             rgb2="0.10 0.12 0.15" width="300" height="300"/>
    <material name="grid" texture="grid" texrepeat="{n} {n}" reflectance="0.1"/>
  </asset>
  <worldbody>
    <light pos="{cx} {cx} 20" dir="0 0 -1" diffuse="0.9 0.9 0.9"/>
    <geom type="plane" pos="{cx} {cx} 0" size="{n} {n} 0.1" material="grid"/>
    {''.join(ob5)}
    {''.join(people)}
    <body name="drone" mocap="true" pos="0 0 {ALT}">
      <geom type="box" size="0.28 0.28 0.06" rgba="0.90 0.20 0.20 1"/>
      <geom type="box" pos="0.28 0.28 0" size="0.10 0.02 0.02" rgba="0.8 0.8 0.8 1"/>
      <geom type="box" pos="-0.28 0.28 0" size="0.10 0.02 0.02" rgba="0.8 0.8 0.8 1"/>
      <geom type="box" pos="0.28 -0.28 0" size="0.10 0.02 0.02" rgba="0.8 0.8 0.8 1"/>
      <geom type="box" pos="-0.28 -0.28 0" size="0.10 0.02 0.02" rgba="0.8 0.8 0.8 1"/>
    </body>
  </worldbody>
</mujoco>"""
    return xml


def run(seed=3, n_people=3, sensor="thermal", budget=400, make_gif=True, viewer=False):
    world = World(seed=seed, prior="multi", n_people=n_people)
    apply(world, sensor)
    planner = MCTS(world)
    belief = world.belief.copy()

    model = mujoco.MjModel.from_xml_string(build_xml(world))
    data = mujoco.MjData(model)
    mocap = model.body_mocapid[mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_BODY, "drone")]
    pgeom = {idx: mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_GEOM, f"person{idx}")
             for idx in range(len(world.people))}

    start = (world.n - 1, 0)
    drone = np.array([*cell_xy(start, world.n), ALT])
    data.mocap_pos[mocap] = drone
    target_cell = start
    target = np.array([*cell_xy(start, world.n), ALT])
    remaining = set(range(len(world.people)))

    renderer = mujoco.Renderer(model, 720, 720) if make_gif else None
    cam = mujoco.MjvCamera()
    cam.lookat = [(world.n - 1) / 2, (world.n - 1) / 2, 0]
    cam.distance = world.n * 1.5
    cam.azimuth, cam.elevation = 90, -60
    frames = []

    vwr = None
    if viewer:
        import mujoco.viewer as mjviewer
        vwr = mjviewer.launch_passive(model, data)

    for step in range(budget):
        to = target - drone
        dist = np.linalg.norm(to)
        if dist > TOL:
            drone = drone + SPEED * to / dist
        else:
            remaining -= world.detect(target_cell, remaining)
            for idx in set(pgeom) - remaining:
                model.geom_rgba[pgeom[idx]] = [0.45, 0.45, 0.5, 1]
            if not remaining:
                data.mocap_pos[mocap] = drone
                mujoco.mj_step(model, data)
                if renderer:
                    renderer.update_scene(data, cam); frames.append(renderer.render())
                break
            world.update_no_detection(belief, target_cell)
            target_cell = planner.next_move(world, belief, target_cell)
            target = np.array([*cell_xy(target_cell, world.n), ALT])

        data.mocap_pos[mocap] = drone
        mujoco.mj_step(model, data)
        if vwr is not None:
            vwr.sync()
            time.sleep(0.015)                 # pace the live window
        if renderer and step % RENDER_EVERY == 0:
            renderer.update_scene(data, cam); frames.append(renderer.render())

    found = len(world.people) - len(remaining)
    print(f"MuJoCo flight done: found {found}/{len(world.people)} people in {step} steps")
    if renderer and frames:
        import imageio
        imageio.mimsave("mujoco_search.gif", frames, fps=20)
        print(f"saved mujoco_search.gif ({len(frames)} frames)")
    if vwr is not None:
        print("Flight complete — orbit with the mouse, close the window when done.")
        while vwr.is_running():            # keep the window open until you close it
            vwr.sync()
            time.sleep(0.1)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--people", type=int, default=3)
    ap.add_argument("--seed", type=int, default=3)
    ap.add_argument("--sensor", default="thermal")
    ap.add_argument("--viewer", action="store_true", help="live 3D window (Mac: use mjpython)")
    args = ap.parse_args()
    run(seed=args.seed, n_people=args.people, sensor=args.sensor,
        make_gif=not args.viewer, viewer=args.viewer)


if __name__ == "__main__":
    main()
