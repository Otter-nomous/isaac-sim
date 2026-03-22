#!/usr/bin/env bash
# vm_setup.sh – Runs ON the GCP VM (Ubuntu 22.04, g2-standard-8 / NVIDIA L4)
# Installs: NVIDIA driver, Docker, NVIDIA Container Toolkit, then launches Isaac Sim.
#
# Invoked by deploy_isaac_sim.py with VM_EXTERNAL_IP set in the environment.
# Can also be run manually:
#   VM_EXTERNAL_IP=<your-vm-ip> bash vm_setup.sh
#
# Viewing the sim:
#   Open http://<VM_EXTERNAL_IP>:6080/vnc.html in your browser (no client needed).

set -euo pipefail

# ─── Config ───────────────────────────────────────────────────────────────────

ISAAC_IMAGE="nvcr.io/nvidia/isaac-sim:4.5.0"
CONTAINER_NAME="isaac-sim"
DISPLAY_NUM=":99"
NOVNC_PORT=6080

# Persistent volume directories (host paths)
CACHE_BASE="${HOME}/docker/isaac-sim/cache"
LOGS_DIR="${HOME}/docker/isaac-sim/logs"
DATA_DIR="${HOME}/docker/isaac-sim/data"
DOCS_DIR="${HOME}/docker/isaac-sim/documents"

# ─── Helpers ──────────────────────────────────────────────────────────────────

log()  { echo -e "\n\033[1;34m[SETUP]\033[0m $*"; }
ok()   { echo -e "\033[1;32m  ✓ $*\033[0m"; }
die()  { echo -e "\033[1;31m[ERROR]\033[0m $*" >&2; exit 1; }

require_env() {
    [[ -n "${VM_EXTERNAL_IP:-}" ]] || \
        die "VM_EXTERNAL_IP is not set. Export it before running this script."
}

# ─── 1. System update ─────────────────────────────────────────────────────────

system_update() {
    log "Updating system packages ..."
    sudo apt-get update -y
    sudo apt-get upgrade -y
    sudo apt-get install -y \
        ca-certificates \
        curl \
        gnupg \
        lsb-release \
        software-properties-common \
        build-essential \
        dkms \
        linux-headers-$(uname -r)
    ok "System updated"
}

# ─── 2. NVIDIA Driver ─────────────────────────────────────────────────────────

install_nvidia_driver() {
    if nvidia-smi &>/dev/null; then
        ok "NVIDIA driver already installed – $(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1)"
        return
    fi

    log "Installing NVIDIA driver (ubuntu-drivers recommended) ..."
    sudo add-apt-repository -y ppa:graphics-drivers/ppa
    sudo apt-get update -y
    sudo apt-get install -y ubuntu-drivers-common
    # ubuntu-drivers selects the recommended production driver for the L4 GPU
    sudo ubuntu-drivers install --gpgpu
    ok "NVIDIA driver installed. A reboot may be required on first install."

    # If running in CI / non-interactive, load the module now
    sudo modprobe nvidia 2>/dev/null || true
}

# ─── 3. Docker ────────────────────────────────────────────────────────────────

install_docker() {
    if docker version &>/dev/null; then
        ok "Docker already installed – $(docker version --format '{{.Server.Version}}')"
        return
    fi

    log "Installing Docker CE ..."
    sudo install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg \
        | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    sudo chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
        "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] \
https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" \
        | sudo tee /etc/apt/sources.list.d/docker.list >/dev/null

    sudo apt-get update -y
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    sudo systemctl enable --now docker
    sudo usermod -aG docker "${USER}"
    ok "Docker installed"
}

# ─── 4. NVIDIA Container Toolkit ──────────────────────────────────────────────

install_nvidia_container_toolkit() {
    if dpkg -l | grep -q nvidia-container-toolkit; then
        ok "NVIDIA Container Toolkit already installed"
        return
    fi

    log "Installing NVIDIA Container Toolkit ..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey \
        | sudo gpg --batch --yes --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg

    curl -sL https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list \
        | sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' \
        | sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list

    sudo apt-get update -y
    sudo apt-get install -y nvidia-container-toolkit

    # Configure Docker runtime to use NVIDIA
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker
    ok "NVIDIA Container Toolkit installed and Docker runtime configured"
}

# ─── 5. NvFBC (GPU framebuffer capture library) ───────────────────────────────

install_nvfbc() {
    if ldconfig -p | grep -q libnvidia-fbc; then
        ok "NvFBC already installed"
        return
    fi

    log "Installing NvFBC (framebuffer capture) ..."
    # Match the installed driver series (580-server on GCP L4)
    DRIVER_VER=$(nvidia-smi --query-gpu=driver_version --format=csv,noheader | head -1 | cut -d. -f1)
    PKG="libnvidia-fbc1-${DRIVER_VER}-server"
    if ! apt-cache show "$PKG" &>/dev/null; then
        PKG="libnvidia-fbc1-${DRIVER_VER}"
    fi
    sudo apt-get install -y "$PKG"
    sudo ldconfig
    ok "NvFBC installed: $PKG"
}

# ─── 6. Virtual display + VNC viewer ──────────────────────────────────────────

install_display_stack() {
    log "Installing Xvfb, x11vnc, noVNC ..."
    sudo apt-get install -y xvfb x11vnc novnc
    ok "Display stack installed"
}

start_virtual_display() {
    log "Starting virtual display on ${DISPLAY_NUM} ..."
    pkill Xvfb 2>/dev/null || true
    Xvfb "${DISPLAY_NUM}" -screen 0 1920x1080x24 &>/tmp/xvfb.log &
    sleep 2
    DISPLAY="${DISPLAY_NUM}" xhost +local:root 2>/dev/null || true
    ok "Xvfb running on display ${DISPLAY_NUM}"
}

start_novnc() {
    log "Starting noVNC on port ${NOVNC_PORT} ..."
    pkill x11vnc 2>/dev/null || true
    pkill websockify 2>/dev/null || true
    sleep 1

    DISPLAY="${DISPLAY_NUM}" x11vnc -display "${DISPLAY_NUM}" -nopw \
        -listen localhost -xkb -forever -bg -o /tmp/x11vnc.log
    /usr/share/novnc/utils/launch.sh \
        --vnc localhost:5900 --listen "${NOVNC_PORT}" &>/tmp/novnc.log &
    sleep 2
    ok "noVNC started – view at http://${VM_EXTERNAL_IP}:${NOVNC_PORT}/vnc.html"
}

# ─── 7. Persist NGC credentials (optional) ────────────────────────────────────

ngc_login() {
    if [[ -n "${NGC_API_KEY:-}" ]]; then
        log "Logging into NGC registry ..."
        echo "${NGC_API_KEY}" | docker login nvcr.io \
            --username "\$oauthtoken" \
            --password-stdin
        ok "NGC login successful"
    else
        echo "  NGC_API_KEY not set – skipping registry login."
        echo "  Isaac Sim image is publicly available; login only needed for private NGC assets."
    fi
}

# ─── 8. Create volume directories ─────────────────────────────────────────────

create_volumes() {
    log "Creating persistent volume directories ..."
    mkdir -p \
        "${CACHE_BASE}/kit" \
        "${CACHE_BASE}/ov" \
        "${CACHE_BASE}/pip" \
        "${CACHE_BASE}/glcache" \
        "${CACHE_BASE}/computecache" \
        "${LOGS_DIR}" \
        "${DATA_DIR}" \
        "${DOCS_DIR}"
    ok "Volume directories ready under ${HOME}/docker/isaac-sim/"
}

# ─── 9. Pull Isaac Sim image ──────────────────────────────────────────────────

pull_image() {
    log "Pulling Isaac Sim image (this takes 10-20 min on first run) ..."
    # Use newgrp trick so docker group membership is active without re-login
    sg docker -c "docker pull ${ISAAC_IMAGE}"
    ok "Image pulled: ${ISAAC_IMAGE}"
}

# ─── 10. Launch Isaac Sim ─────────────────────────────────────────────────────
#
# Runs Isaac Sim in full GUI mode on the virtual display (Xvfb).
# View the UI in your browser via noVNC – no client install needed.
#
# Note: Isaac Sim 4.5's built-in WebRTC streaming (runheadless.webrtc.sh) uses
# libNvStreamServer which does not initialise on GCP L4 instances (error
# 0x800E8401). The GUI-on-Xvfb + noVNC approach is the reliable alternative.

launch_isaac_sim() {
    log "Launching Isaac Sim (GUI mode on virtual display) ..."

    sg docker -c "docker rm -f ${CONTAINER_NAME} 2>/dev/null || true"

    sg docker -c "docker run -d \
        --name ${CONTAINER_NAME} \
        --restart unless-stopped \
        --privileged \
        --gpus all \
        --network=host \
        --entrypoint /isaac-sim/isaac-sim.sh \
        -e ACCEPT_EULA=Y \
        -e PRIVACY_CONSENT=Y \
        -e DISPLAY=${DISPLAY_NUM} \
        -e OMNI_KIT_ALLOW_ROOT=1 \
        -v /tmp/.X11-unix:/tmp/.X11-unix \
        -v /var/run/utmp:/var/run/utmp:ro \
        -v ${CACHE_BASE}/kit:/isaac-sim/kit/cache:rw \
        -v ${CACHE_BASE}/ov:/root/.cache/ov:rw \
        -v ${CACHE_BASE}/pip:/root/.cache/pip:rw \
        -v ${CACHE_BASE}/glcache:/root/.cache/nvidia/GLCache:rw \
        -v ${CACHE_BASE}/computecache:/root/.nv/ComputeCache:rw \
        -v ${LOGS_DIR}:/root/.nvidia-omniverse/logs:rw \
        -v ${DATA_DIR}:/root/.local/share/ov/data:rw \
        -v ${DOCS_DIR}:/root/Documents:rw \
        ${ISAAC_IMAGE} \
        --allow-root"

    ok "Container '${CONTAINER_NAME}' started"
    echo ""
    echo "  Tail logs with:"
    echo "    docker logs -f ${CONTAINER_NAME}"
}

# ─── 11. Verify GPU access inside container ───────────────────────────────────

verify_gpu() {
    log "Verifying GPU access in container ..."
    sleep 5
    sg docker -c "docker exec ${CONTAINER_NAME} nvidia-smi" 2>/dev/null \
        && ok "GPU visible inside container" \
        || echo "  GPU check skipped (container may still be starting up – check logs)."
}

# ─── Main ─────────────────────────────────────────────────────────────────────

main() {
    require_env

    echo ""
    echo "============================================================"
    echo "  Isaac Sim GCP VM Setup"
    echo "  VM External IP : ${VM_EXTERNAL_IP}"
    echo "============================================================"

    system_update
    install_nvidia_driver
    install_docker
    install_nvidia_container_toolkit
    install_nvfbc
    install_display_stack
    start_virtual_display
    ngc_login
    create_volumes
    pull_image
    launch_isaac_sim
    verify_gpu
    start_novnc

    echo ""
    echo "============================================================"
    echo "  Setup complete!"
    echo "  View Isaac Sim in your browser (no client needed):"
    echo "  http://${VM_EXTERNAL_IP}:${NOVNC_PORT}/vnc.html"
    echo "============================================================"
}

main "$@"
