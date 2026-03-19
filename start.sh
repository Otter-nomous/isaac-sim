#!/usr/bin/env bash
# start.sh – Start or create the Isaac Sim VM on GCP.
# Usage: bash start.sh

set -euo pipefail

PROJECT="issac-489618"
ZONE="us-central1-a"
NAME="isaac-sim-vm"

log() { echo -e "\n\033[1;34m[START]\033[0m $*"; }
ok()  { echo -e "\033[1;32m  ✓ $*\033[0m"; }

STATUS=$(gcloud compute instances describe "$NAME" \
    --project="$PROJECT" --zone="$ZONE" \
    --format="get(status)" 2>/dev/null || echo "NOT_FOUND")

if [[ "$STATUS" == "RUNNING" ]]; then
    ok "VM is already running."
elif [[ "$STATUS" == "TERMINATED" || "$STATUS" == "STOPPED" ]]; then
    log "Starting existing VM '$NAME' ..."
    gcloud compute instances start "$NAME" \
        --project="$PROJECT" --zone="$ZONE"
    ok "VM started."
else
    log "VM not found – provisioning a new one ..."
    python3 "$(dirname "$0")/deploy_isaac_sim.py" --project "$PROJECT" --zone "$ZONE" --name "$NAME"
fi

EXTERNAL_IP=$(gcloud compute instances describe "$NAME" \
    --project="$PROJECT" --zone="$ZONE" \
    --format="get(networkInterfaces[0].accessConfigs[0].natIP)")

echo ""
echo "  VM External IP : $EXTERNAL_IP"
echo "  Connect via Omniverse Streaming Client → $EXTERNAL_IP:49100"
echo ""
echo "  Tail Isaac Sim logs:"
echo "    gcloud compute ssh $NAME --zone $ZONE --command 'docker logs -f isaac-sim'"
