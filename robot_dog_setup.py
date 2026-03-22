"""
robot_dog_setup.py – Loads a Unitree Go2 and makes it walk with a trot gait.

Runs inside the full Isaac Sim GUI via:
    /isaac-sim/isaac-sim.sh --exec /robot_dog_setup.py --allow-root
"""

import asyncio
import math
import carb

ASSETS_S3 = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/4.5"

# ── Gait parameters ────────────────────────────────────────────────────────────
# Go2 joint names follow the pattern: {leg}_{part}_joint
# Legs: FL (front-left), FR (front-right), RL (rear-left), RR (rear-right)
# Trot gait: FL+RR swing together, FR+RL swing together (phase offset = π)
FREQ_HZ   = 1.5          # stride frequency
HIP_AMP   = 0.05         # hip abduction amplitude (rad)
THIGH_AMP = 0.30         # thigh flexion amplitude (rad)
CALF_AMP  = 0.50         # calf flexion amplitude (rad)

# Go2 standing-pose offsets (rad) – from Isaac Lab Go2 default joint pos
# Positive thigh = flex forward; negative calf = fold knee back
THIGH_OFFSET =  0.8
CALF_OFFSET  = -1.5

TROT_PHASE = {          # per-leg phase offset (rad)
    "FL": 0.0,
    "RR": 0.0,
    "FR": math.pi,
    "RL": math.pi,
}


async def load_robot_dog():
    import omni.kit.app
    import omni.usd
    import omni.timeline
    from pxr import UsdGeom, UsdLux, UsdPhysics, Gf, Usd
    from omni.isaac.core.utils.stage import add_reference_to_stage
    from omni.isaac.core.utils.nucleus import get_assets_root_path

    app = omni.kit.app.get_app()

    # ── Let the GUI settle ────────────────────────────────────────────────────
    for _ in range(30):
        await app.next_update_async()

    carb.log_warn("[robot_dog] Opening new stage ...")
    await omni.usd.get_context().new_stage_async()
    for _ in range(10):
        await app.next_update_async()

    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

    # ── Physics scene ─────────────────────────────────────────────────────────
    physics_scene = UsdPhysics.Scene.Define(stage, "/World/PhysicsScene")
    physics_scene.CreateGravityDirectionAttr(Gf.Vec3f(0.0, 0.0, -1.0))
    physics_scene.CreateGravityMagnitudeAttr(9.81)

    # ── Lighting ──────────────────────────────────────────────────────────────
    dome = UsdLux.DomeLight.Define(stage, "/World/DomeLight")
    dome.CreateIntensityAttr(1000.0)

    distant = UsdLux.DistantLight.Define(stage, "/World/SunLight")
    distant.CreateIntensityAttr(2000.0)
    distant.CreateAngleAttr(0.53)
    UsdGeom.Xformable(distant).AddXformOp(
        UsdGeom.XformOp.TypeRotateXYZ
    ).Set(Gf.Vec3f(-45.0, 0.0, 30.0))

    # ── Ground environment ────────────────────────────────────────────────────
    assets_root = get_assets_root_path() or ASSETS_S3
    try:
        add_reference_to_stage(
            f"{assets_root}/Isaac/Environments/Grid/default_environment.usd",
            "/World/Ground"
        )
    except Exception as exc:
        carb.log_warn(f"[robot_dog] Ground skipped: {exc}")

    # ── Robot dog (Unitree Go2) ───────────────────────────────────────────────
    robot_prim_path = None
    for rel_path, prim_path in [
        ("/Isaac/Robots/Unitree/Go2/go2.usd",             "/World/Go2"),
        ("/Isaac/Robots/Unitree/Go1/go1.usd",             "/World/Go1"),
        ("/Isaac/Robots/ANYbotics/ANYmal_C/anymal_c.usd", "/World/ANYmal"),
    ]:
        try:
            usd_url = f"{assets_root}{rel_path}"
            add_reference_to_stage(usd_url, prim_path)
            prim = stage.GetPrimAtPath(prim_path)
            xf = UsdGeom.Xformable(prim)
            xf.ClearXformOpOrder()
            xf.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.50))
            robot_prim_path = prim_path
            carb.log_warn(f"[robot_dog] Loaded: {usd_url}")
            break
        except Exception as exc:
            carb.log_warn(f"[robot_dog] Skipping {rel_path}: {exc}")

    if robot_prim_path is None:
        carb.log_error("[robot_dog] No robot could be loaded!")
        return

    # Wait a few frames for stage to settle before touching physics
    for _ in range(20):
        await app.next_update_async()

    # ── Set up joint drives ───────────────────────────────────────────────────
    robot_root = stage.GetPrimAtPath(robot_prim_path)
    joint_drives = {}   # joint_name → UsdPhysics.DriveAPI

    for prim in Usd.PrimRange(robot_root):
        if not UsdPhysics.RevoluteJoint(prim):
            continue
        name = prim.GetName()          # e.g. "FL_hip_joint"
        drive = UsdPhysics.DriveAPI.Apply(prim, "angular")
        # High stiffness for position control; damping prevents oscillation
        drive.CreateStiffnessAttr(200.0)
        drive.CreateDampingAttr(20.0)
        drive.CreateMaxForceAttr(100.0)
        joint_drives[name] = drive

    carb.log_warn(f"[robot_dog] Configured {len(joint_drives)} joint drives")

    if not joint_drives:
        carb.log_warn("[robot_dog] No joints found – robot will fall under gravity.")

    # ── Apply standing pose as initial targets ────────────────────────────────
    for name, drive in joint_drives.items():
        if "thigh" in name.lower():
            drive.CreateTargetPositionAttr(math.degrees(THIGH_OFFSET))
        elif "calf" in name.lower():
            drive.CreateTargetPositionAttr(math.degrees(CALF_OFFSET))
        else:
            drive.CreateTargetPositionAttr(0.0)

    # ── Start physics ─────────────────────────────────────────────────────────
    timeline = omni.timeline.get_timeline_interface()
    timeline.play()
    carb.log_warn("[robot_dog] Physics started – robot standing up ...")

    # Give the robot a moment to reach the standing pose before walking
    for _ in range(120):
        await app.next_update_async()

    carb.log_warn("[robot_dog] Starting trot gait ...")

    # ── Trot gait loop ────────────────────────────────────────────────────────
    omega = 2.0 * math.pi * FREQ_HZ
    step  = 0

    while True:
        await app.next_update_async()
        t = step * (1.0 / 60.0)      # assume ~60 fps update rate

        for name, drive in joint_drives.items():
            name_l = name.lower()
            # Extract leg prefix (FL / FR / RL / RR)
            leg = name[:2].upper() if len(name) >= 2 else ""
            phase = TROT_PHASE.get(leg, 0.0)

            if "hip" in name_l:
                target_rad = HIP_AMP * math.sin(omega * t + phase)
            elif "thigh" in name_l:
                target_rad = THIGH_OFFSET + THIGH_AMP * math.sin(omega * t + phase)
            elif "calf" in name_l:
                target_rad = CALF_OFFSET + CALF_AMP * math.sin(omega * t + phase)
            else:
                target_rad = 0.0

            drive.GetTargetPositionAttr().Set(math.degrees(target_rad))

        step += 1


asyncio.ensure_future(load_robot_dog())
