#!/usr/bin/env bash
# run_robot_dog.sh – Deploy robot_dog.py to the GCP VM and launch it in Isaac Sim.
#
# Usage (from your Mac):
#   bash run_robot_dog.sh
#
# Then open:
#   http://<VM_IP>:6080/vnc.html

set -euo pipefail

PROJECT="issac-489618"
ZONE="us-central1-a"
NAME="isaac-sim-vm"
CONTAINER="isaac-sim"
IMAGE="nvcr.io/nvidia/isaac-sim:4.5.0"
DISPLAY_NUM=":99"

log() { echo -e "\n\033[1;34m[ROBOT]\033[0m $*"; }
ok()  { echo -e "\033[1;32m  ✓ $*\033[0m"; }

# ── 1. Check VM is running ────────────────────────────────────────────────────
STATUS=$(gcloud compute instances describe "$NAME" \
    --project="$PROJECT" --zone="$ZONE" \
    --format="get(status)" 2>/dev/null || echo "NOT_FOUND")

if [[ "$STATUS" != "RUNNING" ]]; then
    echo "VM is not running (status: $STATUS). Start it first:"
    echo "  bash start.sh"
    exit 1
fi

# ── 2. Copy robot_dog.py to the VM ───────────────────────────────────────────
log "Copying robot_dog.py to VM ..."
gcloud compute scp "$(dirname "$0")/robot_dog.py" "$NAME:~/robot_dog.py" \
    --project="$PROJECT" --zone="$ZONE"
ok "Script uploaded"

# ── 3. Re-launch Isaac Sim container running the robot dog scene ──────────────
log "Starting Isaac Sim with robot dog scene ..."

CACHE_BASE="\${HOME}/docker/isaac-sim/cache"

gcloud compute ssh "$NAME" \
    --project="$PROJECT" --zone="$ZONE" \
    --command "
        docker rm -f $CONTAINER 2>/dev/null || true

        sg docker -c \"docker run -d \\
            --name $CONTAINER \\
            --restart unless-stopped \\
            --privileged \\
            --gpus all \\
            --network=host \\
            --entrypoint /isaac-sim/python.sh \\
            -e ACCEPT_EULA=Y \\
            -e PRIVACY_CONSENT=Y \\
            -e DISPLAY=$DISPLAY_NUM \\
            -e OMNI_KIT_ALLOW_ROOT=1 \\
            -v /tmp/.X11-unix:/tmp/.X11-unix \\
            -v /var/run/utmp:/var/run/utmp:ro \\
            -v \\\${HOME}/robot_dog.py:/robot_dog.py:ro \\
            -v ${CACHE_BASE}/kit:/isaac-sim/kit/cache:rw \\
            -v ${CACHE_BASE}/ov:/root/.cache/ov:rw \\
            -v ${CACHE_BASE}/pip:/root/.cache/pip:rw \\
            -v ${CACHE_BASE}/glcache:/root/.cache/nvidia/GLCache:rw \\
            -v ${CACHE_BASE}/computecache:/root/.nv/ComputeCache:rw \\
            -v \\\${HOME}/docker/isaac-sim/logs:/root/.nvidia-omniverse/logs:rw \\
            -v \\\${HOME}/docker/isaac-sim/data:/root/.local/share/ov/data:rw \\
            -v \\\${HOME}/docker/isaac-sim/documents:/root/Documents:rw \\
            $IMAGE \\
            /robot_dog.py\"
    "

ok "Container started"

# ── 4. Show access info ───────────────────────────────────────────────────────
EXTERNAL_IP=$(gcloud compute instances describe "$NAME" \
    --project="$PROJECT" --zone="$ZONE" \
    --format="get(networkInterfaces[0].accessConfigs[0].natIP)")

echo ""
echo "  Robot dog scene loading (first run: ~3-5 min for asset download) ..."
echo ""
echo "  Tail logs:"
echo "    gcloud compute ssh $NAME --zone $ZONE --command 'docker logs -f $CONTAINER'"
echo ""
echo "  View in browser (no client needed):"
echo "  http://$EXTERNAL_IP:6080/vnc.html"
echo ""
