# Isaac Sim on GCP

Automates provisioning a GPU-accelerated Google Cloud VM and running [NVIDIA Isaac Sim](https://developer.nvidia.com/isaac-sim) inside a Docker container on it. Manage everything from your Mac — create, start, stop, and connect to the simulation without touching the cloud console.

## Overview

```
Your Mac  ──gcloud──▶  GCP VM (g2-standard-8, NVIDIA L4)
                            └─ Docker: nvcr.io/nvidia/isaac-sim:4.5.0
                                  └─ WebRTC stream ──▶  Omniverse Streaming Client
```

A single Python script provisions the VM, opens firewall rules, installs the full NVIDIA/Docker stack, and starts Isaac Sim in headless WebRTC mode. Day-to-day you use `start.sh` / `stop.sh` to resume and suspend the VM without re-provisioning.

## Prerequisites

- `gcloud` CLI installed and authenticated (`gcloud auth login`)
- GCP project with Compute Engine API enabled and GPU quota in `us-central1-a`
- Python 3.9+

## Key Scripts

### `deploy_isaac_sim.py` — full provisioning (run once)

```bash
python3 deploy_isaac_sim.py --project YOUR_GCP_PROJECT_ID
```

Does four things in order:

1. **Create VM** — `g2-standard-8` with 1× NVIDIA L4, 200 GB SSD, Ubuntu 22.04
2. **Configure firewall** — opens TCP 49100 (WebRTC signaling) and UDP 47998–48012 (media stream)
3. **Run `vm_setup.sh` on the VM** — installs NVIDIA drivers, Docker, NVIDIA Container Toolkit, pulls the Isaac Sim image, and starts the container
4. **Print connection info** — VM IP and instructions for the Omniverse Streaming Client

Useful flags:

| Flag | Purpose |
|---|---|
| `--skip-vm-create` | Use an existing VM (skip creation) |
| `--skip-firewall` | Skip firewall rules (already configured) |
| `--skip-setup` | Skip `vm_setup.sh` (VM already configured) |
| `--external-ip IP` | Override IP lookup |
| `--print-docker-cmd` | Print the `docker run` command and exit |

### `start.sh` — day-to-day start

```bash
bash start.sh
```

Checks the VM's current state:
- **RUNNING** → prints the IP and connection URL
- **TERMINATED/STOPPED** → resumes the VM (`gcloud compute instances start`, preserves disk)
- **NOT FOUND** → falls through to `deploy_isaac_sim.py` for full provisioning

### `stop.sh` — day-to-day stop

```bash
bash stop.sh           # safe stop (checks for active simulation)
bash stop.sh --force   # stop immediately regardless
```

Before stopping, SSHes into the VM and checks GPU utilization. If utilization is above 10% the script warns and exits rather than interrupting a running simulation. Stopping the VM reduces billing to storage cost only (disk is preserved).

### `vm_setup.sh` — VM configuration (runs on the VM)

Invoked automatically by `deploy_isaac_sim.py`. Can also be run manually on the VM:

```bash
VM_EXTERNAL_IP=<your-vm-ip> bash vm_setup.sh
```

Installs: NVIDIA driver, Docker CE, NVIDIA Container Toolkit. Then pulls the Isaac Sim image and starts the container in headless WebRTC mode.

## Connecting from Your Mac

After `deploy_isaac_sim.py` or `start.sh` completes:

1. Download the [Omniverse Streaming Client](https://www.nvidia.com/en-us/omniverse/apps/streaming-client/)
2. Connect to `VM_IP:49100`

To tail Isaac Sim logs:

```bash
gcloud compute ssh isaac-sim-vm --zone us-central1-a \
  --command "docker logs -f isaac-sim"
```

## VM Configuration

| Setting | Value |
|---|---|
| Machine type | `g2-standard-8` (8 vCPUs, 32 GB RAM) |
| GPU | 1× NVIDIA L4 (24 GB VRAM) |
| Disk | 200 GB SSD (`pd-ssd`) |
| OS | Ubuntu 22.04 LTS |
| Zone | `us-central1-a` |
| Isaac Sim image | `nvcr.io/nvidia/isaac-sim:4.5.0` |

---

## Customising Isaac Sim — Use a Dockerfile

> **Important:** Any custom Python packages, extensions, or configuration changes to the Isaac Sim environment **must be captured in a Dockerfile**, not applied ad-hoc inside a running container.

Ad-hoc changes made with `docker exec` or by SSHing into the VM are lost whenever the container is recreated (e.g. after a VM restart, image update, or migration). A Dockerfile makes the setup reproducible and portable.

### Example Dockerfile

```dockerfile
FROM nvcr.io/nvidia/isaac-sim:4.5.0

# Install custom Python dependencies into Isaac Sim's bundled Python
RUN /isaac-sim/python.sh -m pip install \
    pyzmq \
    numpy \
    opencv-python-headless

# Copy custom scripts or extensions into the container
COPY robot_dog_setup.py /robot_dog_setup.py
COPY my_extension/ /isaac-sim/exts/my_extension/

# Optional: set default environment variables
ENV ACCEPT_EULA=Y \
    PRIVACY_CONSENT=Y
```

Build and push to a registry your VM can pull from, then update the image name in `vm_setup.sh` and `deploy_isaac_sim.py`.

### Why this matters for migration

The GCP VM is not the only place Isaac Sim can run. Any Linux machine with an NVIDIA GPU can run the same container with zero changes. To migrate from GCP to a local workstation:

1. Copy the `Dockerfile` (and any scripts it references) to the workstation
2. `docker build -t my-isaac-sim .`
3. Run with the same `docker run` flags (see `--print-docker-cmd` above), minus the WebRTC IP arguments if running locally

No re-provisioning, no re-installing drivers manually, no configuration drift.

---

## Running Locally (Workstation)

To run Isaac Sim locally instead of on GCP, the workstation needs:

| Requirement | Details |
|---|---|
| **OS** | Linux (Ubuntu 22.04 recommended) — Isaac Sim does not support Docker on macOS/Windows with GPU passthrough |
| **GPU** | NVIDIA RTX-class GPU with ≥ 8 GB VRAM (RTX 3080 / 4080 / A4000 or better recommended) |
| **NVIDIA driver** | 525.85.12 or later (`nvidia-smi` should work) |
| **Docker** | Docker CE 20.10+ |
| **NVIDIA Container Toolkit** | Installed and configured as the default Docker runtime (`nvidia-ctk runtime configure --runtime=docker`) |

The `vm_setup.sh` script installs all of the above automatically on Ubuntu — you can run it on a local Ubuntu machine the same way it runs on the GCP VM.
