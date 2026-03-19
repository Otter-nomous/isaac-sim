#!/usr/bin/env bash
# stop.sh – Stop the Isaac Sim VM if no training job is running.
# Usage:
#   bash stop.sh          # checks for active training, stops only if idle
#   bash stop.sh --force  # stops immediately regardless of training status

set -euo pipefail

PROJECT="issac-489618"
ZONE="us-central1-a"
NAME="isaac-sim-vm"
FORCE=${1:-""}

log()  { echo -e "\n\033[1;34m[STOP]\033[0m $*"; }
ok()   { echo -e "\033[1;32m  ✓ $*\033[0m"; }
warn() { echo -e "\033[1;33m  ! $*\033[0m"; }

# Check VM is actually running
STATUS=$(gcloud compute instances describe "$NAME" \
    --project="$PROJECT" --zone="$ZONE" \
    --format="get(status)" 2>/dev/null || echo "NOT_FOUND")

if [[ "$STATUS" == "NOT_FOUND" || "$STATUS" == "TERMINATED" || "$STATUS" == "STOPPED" ]]; then
    ok "VM is not running – nothing to stop."
    exit 0
fi

if [[ "$FORCE" != "--force" ]]; then
    log "Checking for active training jobs on VM ..."

    # Check if isaac-sim container is running AND GPU is actively being used (>10% utilization)
    TRAINING_ACTIVE=$(gcloud compute ssh "$NAME" \
        --project="$PROJECT" --zone="$ZONE" \
        --strict-host-key-checking=no \
        --command '
            CONTAINER_RUNNING=$(docker inspect -f "{{.State.Running}}" isaac-sim 2>/dev/null || echo "false")
            if [[ "$CONTAINER_RUNNING" != "true" ]]; then
                echo "idle"
                exit 0
            fi
            GPU_UTIL=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
            if [[ -n "$GPU_UTIL" && "$GPU_UTIL" -gt 10 ]]; then
                echo "training"
            else
                echo "idle"
            fi
        ' 2>/dev/null || echo "idle")

    if [[ "$TRAINING_ACTIVE" == "training" ]]; then
        warn "Training job is active (GPU utilization >10%) – skipping shutdown."
        warn "Use 'bash stop.sh --force' to stop anyway."
        exit 0
    fi

    ok "No active training job detected."
fi

log "Stopping VM '$NAME' (disk preserved, billing reduced) ..."
gcloud compute instances stop "$NAME" \
    --project="$PROJECT" --zone="$ZONE"
ok "VM stopped. Restart anytime with: bash start.sh"
