#!/usr/bin/env python3
"""
Isaac Sim GCP Deployment Orchestrator
Provisions a GCP VM, configures firewall rules, and deploys NVIDIA Isaac Sim
with WebRTC streaming. Run this script from your local machine.

Usage:
    python3 deploy_isaac_sim.py --project YOUR_PROJECT_ID [options]
    python3 deploy_isaac_sim.py --project my-project --zone us-central1-a --name isaac-sim-vm

Prerequisites:
    - gcloud CLI installed and authenticated (gcloud auth login)
    - gcloud CLI project set or passed via --project
"""

import argparse
import subprocess
import sys
import json
import time
import os
from pathlib import Path


# ─── Constants ────────────────────────────────────────────────────────────────

INSTANCE_TYPE   = "g2-standard-8"
GPU_TYPE        = "nvidia-l4"
GPU_COUNT       = 1
DISK_SIZE_GB    = 200
IMAGE_FAMILY    = "ubuntu-2204-lts"
IMAGE_PROJECT   = "ubuntu-os-cloud"

SIGNAL_PORT     = 49100          # TCP – WebRTC signaling
STREAM_PORT_LO  = 47998          # UDP – media start
STREAM_PORT_HI  = 48012          # UDP – media end

FW_SIGNAL_RULE  = "allow-isaac-signal"
FW_STREAM_RULE  = "allow-isaac-stream"
NETWORK_TAG     = "isaac-sim"

ISAAC_IMAGE     = "nvcr.io/nvidia/isaac-sim:4.5.0"

SETUP_SCRIPT    = Path(__file__).parent / "vm_setup.sh"


# ─── Helpers ──────────────────────────────────────────────────────────────────

def run(cmd: list[str], check=True, capture=False) -> subprocess.CompletedProcess:
    """Run a shell command, streaming output unless capture=True."""
    print(f"\n$ {' '.join(cmd)}")
    return subprocess.run(
        cmd,
        check=check,
        capture_output=capture,
        text=True,
    )


def run_capture(cmd: list[str]) -> str:
    result = run(cmd, capture=True)
    return result.stdout.strip()


def gcloud(args: list[str], **kwargs) -> subprocess.CompletedProcess:
    return run(["gcloud"] + args, **kwargs)


def gcloud_capture(args: list[str]) -> str:
    return run_capture(["gcloud"] + args)


# ─── GCP Operations ───────────────────────────────────────────────────────────

def set_project(project: str):
    gcloud(["config", "set", "project", project])


def create_vm(project: str, zone: str, name: str, maintenance_policy: str):
    """Create the GCP VM with L4 GPU and Ubuntu 22.04."""
    print(f"\n[1/4] Creating VM '{name}' in {zone} ...")
    gcloud([
        "compute", "instances", "create", name,
        f"--project={project}",
        f"--zone={zone}",
        f"--machine-type={INSTANCE_TYPE}",
        f"--accelerator=type={GPU_TYPE},count={GPU_COUNT}",
        f"--maintenance-policy={maintenance_policy}",
        f"--boot-disk-size={DISK_SIZE_GB}GB",
        "--boot-disk-type=pd-ssd",
        f"--image-family={IMAGE_FAMILY}",
        f"--image-project={IMAGE_PROJECT}",
        f"--tags={NETWORK_TAG}",
        "--scopes=default",
    ])


def get_external_ip(project: str, zone: str, name: str) -> str:
    """Retrieve the VM's external IP address."""
    ip = gcloud_capture([
        "compute", "instances", "describe", name,
        f"--project={project}",
        f"--zone={zone}",
        "--format=get(networkInterfaces[0].accessConfigs[0].natIP)",
    ])
    if not ip:
        raise RuntimeError("Could not retrieve external IP – check that the VM has an external IP.")
    return ip


def configure_firewall(project: str):
    """Open the required TCP/UDP ports for Isaac Sim WebRTC streaming."""
    print("\n[2/4] Configuring firewall rules ...")

    # Helper: check if rule already exists
    existing = gcloud_capture([
        "compute", "firewall-rules", "list",
        f"--project={project}",
        "--format=value(name)",
    ])
    existing_rules = existing.splitlines()

    # TCP 49100 – signaling
    if FW_SIGNAL_RULE not in existing_rules:
        gcloud([
            "compute", "firewall-rules", "create", FW_SIGNAL_RULE,
            f"--project={project}",
            "--direction=INGRESS",
            "--priority=1000",
            "--network=default",
            "--action=ALLOW",
            f"--rules=tcp:{SIGNAL_PORT}",
            f"--target-tags={NETWORK_TAG}",
            "--description=Isaac Sim WebRTC signaling port",
        ])
    else:
        print(f"  Rule '{FW_SIGNAL_RULE}' already exists – skipping.")

    # UDP 47998-48012 – media stream
    if FW_STREAM_RULE not in existing_rules:
        gcloud([
            "compute", "firewall-rules", "create", FW_STREAM_RULE,
            f"--project={project}",
            "--direction=INGRESS",
            "--priority=1000",
            "--network=default",
            "--action=ALLOW",
            f"--rules=udp:{STREAM_PORT_LO}-{STREAM_PORT_HI}",
            f"--target-tags={NETWORK_TAG}",
            "--description=Isaac Sim WebRTC media stream ports",
        ])
    else:
        print(f"  Rule '{FW_STREAM_RULE}' already exists – skipping.")


def upload_and_run_setup(project: str, zone: str, name: str, external_ip: str):
    """SCP the VM setup script and execute it remotely."""
    print("\n[3/4] Uploading and running VM setup script ...")

    if not SETUP_SCRIPT.exists():
        raise FileNotFoundError(f"Setup script not found: {SETUP_SCRIPT}")

    # Copy script to VM
    gcloud([
        "compute", "scp",
        str(SETUP_SCRIPT),
        f"{name}:/tmp/vm_setup.sh",
        f"--project={project}",
        f"--zone={zone}",
        "--strict-host-key-checking=no",
    ])

    # Execute with external IP injected
    gcloud([
        "compute", "ssh", name,
        f"--project={project}",
        f"--zone={zone}",
        "--strict-host-key-checking=no",
        "--command",
        f"chmod +x /tmp/vm_setup.sh && VM_EXTERNAL_IP={external_ip} bash /tmp/vm_setup.sh",
    ])


def print_connection_info(external_ip: str, name: str):
    """Print how to connect from a Mac using the WebRTC client."""
    separator = "─" * 60
    print(f"""
{separator}
  Isaac Sim Deployment Complete
{separator}

  VM External IP : {external_ip}
  Signal Port    : {SIGNAL_PORT}  (TCP)
  Stream Ports   : {STREAM_PORT_LO}-{STREAM_PORT_HI}  (UDP)

  WebRTC Streaming Client (from your Mac)
  ─────────────────────────────────────────
  1. Download the Omniverse Streaming Client from:
       https://www.nvidia.com/en-us/omniverse/apps/streaming-client/

  2. Launch the client and connect to:
       Server : {external_ip}
       Port   : {SIGNAL_PORT}

  SSH into the VM
  ─────────────────
  gcloud compute ssh {name} --zone <ZONE>

  Tail Isaac Sim logs
  ─────────────────────
  gcloud compute ssh {name} --zone <ZONE> \\
    --command "docker logs -f isaac-sim"

  Stop Isaac Sim
  ────────────────
  gcloud compute ssh {name} --zone <ZONE> \\
    --command "docker stop isaac-sim"
{separator}
""")


# ─── Docker command (printed for reference) ───────────────────────────────────

def print_docker_command(external_ip: str):
    """Display the full docker run command for reference."""
    cmd = f"""\
docker run -d \\
  --name isaac-sim \\
  --restart unless-stopped \\
  --gpus all \\
  --network=host \\
  -e ACCEPT_EULA=Y \\
  -e PRIVACY_CONSENT=Y \\
  -v ~/docker/isaac-sim/cache/kit:/isaac-sim/kit/cache:rw \\
  -v ~/docker/isaac-sim/cache/ov:/root/.cache/ov:rw \\
  -v ~/docker/isaac-sim/cache/pip:/root/.cache/pip:rw \\
  -v ~/docker/isaac-sim/cache/glcache:/root/.cache/nvidia/GLCache:rw \\
  -v ~/docker/isaac-sim/cache/computecache:/root/.nv/ComputeCache:rw \\
  -v ~/docker/isaac-sim/logs:/root/.nvidia-omniverse/logs:rw \\
  -v ~/docker/isaac-sim/data:/root/.local/share/ov/data:rw \\
  -v ~/docker/isaac-sim/documents:/root/Documents:rw \\
  {ISAAC_IMAGE} \\
  ./runheadless.webrtc.sh \\
  --/exts/omni.kit.livestream.app/primaryStream/publicIp={external_ip} \\
  --/exts/omni.kit.livestream.webrtc/signalingServerPort={SIGNAL_PORT} \\
  --/exts/omni.kit.livestream.webrtc/mediaServerPort={STREAM_PORT_LO}"""

    print("\n  Generated Docker Command:\n")
    for line in cmd.splitlines():
        print(f"    {line}")
    print()


# ─── CLI ──────────────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Deploy NVIDIA Isaac Sim on GCP with WebRTC streaming."
    )
    parser.add_argument("--project",  required=True, help="GCP project ID")
    parser.add_argument("--zone",     default="us-central1-a", help="GCP zone (default: us-central1-a)")
    parser.add_argument("--name",     default="isaac-sim-vm",  help="VM instance name")
    parser.add_argument(
        "--maintenance-policy",
        default="TERMINATE",
        choices=["TERMINATE", "MIGRATE"],
        help="On-host maintenance policy. GPU VMs must use TERMINATE (default).",
    )
    parser.add_argument(
        "--skip-vm-create",
        action="store_true",
        help="Skip VM creation (use an existing VM).",
    )
    parser.add_argument(
        "--skip-firewall",
        action="store_true",
        help="Skip firewall rule creation.",
    )
    parser.add_argument(
        "--skip-setup",
        action="store_true",
        help="Skip uploading/running vm_setup.sh (e.g. already configured).",
    )
    parser.add_argument(
        "--print-docker-cmd",
        action="store_true",
        help="Print the docker run command and exit (requires --external-ip).",
    )
    parser.add_argument(
        "--external-ip",
        help="Override external IP (used with --print-docker-cmd or --skip-vm-create).",
    )
    return parser.parse_args()


def main():
    args = parse_args()

    # Quick-print mode
    if args.print_docker_cmd:
        if not args.external_ip:
            sys.exit("--print-docker-cmd requires --external-ip <IP>")
        print_docker_command(args.external_ip)
        return

    set_project(args.project)

    if not args.skip_vm_create:
        create_vm(args.project, args.zone, args.name, args.maintenance_policy)
        print("  Waiting 30 s for VM to initialise SSH ...")
        time.sleep(30)

    external_ip = args.external_ip or get_external_ip(args.project, args.zone, args.name)
    print(f"\n  VM external IP: {external_ip}")

    if not args.skip_firewall:
        configure_firewall(args.project)

    if not args.skip_setup:
        upload_and_run_setup(args.project, args.zone, args.name, external_ip)

    print_docker_command(external_ip)
    print_connection_info(external_ip, args.name)


if __name__ == "__main__":
    main()
