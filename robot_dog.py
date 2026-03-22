#!/usr/bin/env python3
"""
robot_dog.py – Spawn a Unitree Go2 robot dog in Isaac Sim 4.5.0

Run inside the isaac-sim container:
    /isaac-sim/python.sh /robot_dog.py

Or use the deployment helper from your Mac:
    bash run_robot_dog.sh

View result in browser (no client needed):
    http://<VM_IP>:6080/vnc.html
"""

import sys
import numpy as np

from isaacsim import SimulationApp

# ── Launch Isaac Sim GUI ───────────────────────────────────────────────────────
app = SimulationApp({
    "headless": False,
    "width": 1920,
    "height": 1080,
    "renderer": "RayTracedLighting",
})

# Imports must come after SimulationApp is created
from omni.isaac.core import World
from omni.isaac.core.robots import Robot
from omni.isaac.core.utils.stage import add_reference_to_stage
from omni.isaac.core.utils.nucleus import get_assets_root_path
import omni.kit.commands
import carb
from pxr import UsdLux, Gf

# ── World + ground plane ───────────────────────────────────────────────────────
world = World(stage_units_in_meters=1.0)
world.scene.add_default_ground_plane()

# ── Lighting ───────────────────────────────────────────────────────────────────
stage = world.stage

dome = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
dome.CreateIntensityAttr(800.0)

distant = UsdLux.DistantLight.Define(stage, "/World/DistantLight")
distant.CreateIntensityAttr(2000.0)
distant.CreateAngleAttr(0.53)
distant.AddXformOp(distant.UsdGeomXformOp.TypeRotateXYZ).Set(Gf.Vec3f(-45.0, 0.0, 30.0))

# ── Robot dog asset ────────────────────────────────────────────────────────────
# Try Unitree Go2 first, fall back to ANYmal C (both are quadruped / "robot dog")
ROBOT_OPTIONS = [
    ("/Isaac/Robots/Unitree/Go2/go2.usd",              "/World/Go2",    "go2"),
    ("/Isaac/Robots/Unitree/Go1/go1.usd",              "/World/Go1",    "go1"),
    ("/Isaac/Robots/ANYbotics/ANYmal_C/anymal_c.usd",  "/World/ANYmal", "anymal_c"),
]

assets_root = get_assets_root_path()
if assets_root is None:
    # Public S3 mirror – no Nucleus server required
    assets_root = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/4.5"
    carb.log_warn(f"Nucleus unavailable – using S3 mirror: {assets_root}")

robot = None
for rel_path, prim_path, robot_name in ROBOT_OPTIONS:
    usd_path = f"{assets_root}{rel_path}"
    carb.log_info(f"Trying: {usd_path}")
    try:
        add_reference_to_stage(usd_path=usd_path, prim_path=prim_path)
        robot = world.scene.add(
            Robot(
                prim_path=prim_path,
                name=robot_name,
                position=np.array([0.0, 0.0, 0.55]),   # slightly above ground
            )
        )
        print(f"[robot_dog] Loaded: {usd_path}")
        break
    except Exception as exc:
        carb.log_warn(f"Skipping {rel_path}: {exc}")

if robot is None:
    print("[robot_dog] ERROR: No robot asset could be loaded.", file=sys.stderr)
    app.close()
    sys.exit(1)

# ── Simulation loop ────────────────────────────────────────────────────────────
world.reset()

pos, _ = robot.get_world_pose()
print(f"[robot_dog] '{robot.name}' spawned at position {pos}.")
print("[robot_dog] Scene running – open noVNC to view the robot.")

step = 0
while app.is_running():
    world.step(render=True)
    step += 1
    if step % 2000 == 0:
        pos, _ = robot.get_world_pose()
        print(f"[robot_dog] step={step:>6d}  pos={np.round(pos, 3)}")

app.close()
