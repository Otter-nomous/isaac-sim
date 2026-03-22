"""
robot_dog_setup.py – Runs inside the full Isaac Sim GUI via --exec.
Adds a Unitree Go2 to the stage as a visible USD prim (no physics needed).

Usage (from run_robot_dog.sh):
    /isaac-sim/isaac-sim.sh --exec /robot_dog_setup.py --allow-root
"""

import asyncio
import carb

ASSETS_S3 = "https://omniverse-content-production.s3-us-west-2.amazonaws.com/Assets/Isaac/4.5"

ROBOT_OPTIONS = [
    ("/Isaac/Robots/Unitree/Go2/go2.usd",             "/World/Go2"),
    ("/Isaac/Robots/Unitree/Go1/go1.usd",             "/World/Go1"),
    ("/Isaac/Robots/ANYbotics/ANYmal_C/anymal_c.usd", "/World/ANYmal"),
]


async def load_robot_dog():
    import omni.kit.app
    import omni.usd
    from pxr import UsdGeom, UsdLux, Gf
    from omni.isaac.core.utils.stage import add_reference_to_stage
    from omni.isaac.core.utils.nucleus import get_assets_root_path

    app = omni.kit.app.get_app()

    # Wait for GUI to fully settle
    for _ in range(30):
        await app.next_update_async()

    carb.log_warn("[robot_dog] Opening new stage ...")
    await omni.usd.get_context().new_stage_async()
    for _ in range(10):
        await app.next_update_async()

    stage = omni.usd.get_context().get_stage()
    UsdGeom.SetStageUpAxis(stage, UsdGeom.Tokens.z)
    UsdGeom.SetStageMetersPerUnit(stage, 1.0)

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
    ground_url = f"{assets_root}/Isaac/Environments/Grid/default_environment.usd"
    try:
        add_reference_to_stage(ground_url, "/World/Ground")
        carb.log_warn(f"[robot_dog] Ground loaded: {ground_url}")
    except Exception as exc:
        carb.log_warn(f"[robot_dog] Ground skipped: {exc}")

    # ── Robot dog ─────────────────────────────────────────────────────────────
    loaded = False
    for rel_path, prim_path in ROBOT_OPTIONS:
        usd_url = f"{assets_root}{rel_path}"
        carb.log_warn(f"[robot_dog] Trying: {usd_url}")
        try:
            add_reference_to_stage(usd_url, prim_path)
            # Position above ground
            prim = stage.GetPrimAtPath(prim_path)
            xf = UsdGeom.Xformable(prim)
            xf.ClearXformOpOrder()
            xf.AddTranslateOp().Set(Gf.Vec3d(0.0, 0.0, 0.0))
            carb.log_warn(f"[robot_dog] Loaded: {usd_url}")
            loaded = True
            break
        except Exception as exc:
            carb.log_warn(f"[robot_dog] Skipping {rel_path}: {exc}")

    if not loaded:
        carb.log_error("[robot_dog] No robot asset could be loaded!")
        return

    await app.next_update_async()
    carb.log_warn("[robot_dog] Robot dog is in the scene! View at noVNC.")


asyncio.ensure_future(load_robot_dog())
