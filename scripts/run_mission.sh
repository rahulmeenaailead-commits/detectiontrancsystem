#!/usr/bin/env bash
# Sentinel Mission Control — one-command 6-agent coordinated sweep.
# Usage: ./scripts/run_mission.sh [API_BASE]
#   Defaults to http://localhost:8000

set -euo pipefail

# --- Config -----------------------------------------------------------------
API_BASE="${1:-${API_BASE:-http://localhost:8000}}"
PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP="$(date +%Y-%m-%d-%H%M%S)"
MISSION_DIR="$PROJECT_ROOT/reports/mission-$TIMESTAMP"
PROMPT_FILE="$PROJECT_ROOT/scripts/MISSION_PROMPT.md"
SYNTH_FILE="$PROJECT_ROOT/scripts/synthesize_mission.py"

# --- Banner -----------------------------------------------------------------
cat <<'BANNER'
████████████████████████████████████████████████████████████████
  SENTINEL MISSION CONTROL — 6-Agent Coordinated Sweep
████████████████████████████████████████████████████████████████
BANNER
echo ""
echo "  API base:     $API_BASE"
echo "  Mission dir:  $MISSION_DIR"
echo ""

# --- Preflight: backend -----------------------------------------------------
echo "[preflight] checking backend ..."
if ! curl -sf "$API_BASE/" >/dev/null 2>&1; then
  echo "  ✗ Backend not responding at $API_BASE"
  echo "    Start it with:  cd backend && uvicorn main:app --reload"
  exit 1
fi
echo "  ✓ backend up"

# --- Preflight: claude CLI --------------------------------------------------
echo "[preflight] checking claude CLI ..."
if ! command -v claude >/dev/null 2>&1; then
  echo "  ✗ claude CLI not found in PATH"
  exit 1
fi
echo "  ✓ claude $(claude --version 2>/dev/null | head -n1)"

# --- Preflight: required files ---------------------------------------------
[[ -f "$PROMPT_FILE" ]] || { echo "  ✗ missing $PROMPT_FILE"; exit 1; }
[[ -f "$SYNTH_FILE"  ]] || { echo "  ✗ missing $SYNTH_FILE"; exit 1; }
echo "  ✓ mission prompt + synthesizer present"

# --- Setup mission dir ------------------------------------------------------
mkdir -p "$MISSION_DIR"
echo "  ✓ mission folder created"
echo ""

# --- Build the orchestrator prompt -----------------------------------------
ORCHESTRATOR_PROMPT="$(cat "$PROMPT_FILE")

---

**Runtime values (use these literal paths in the sub-agent prompts):**
- MISSION_DIR=$MISSION_DIR
- API_BASE=$API_BASE
- Mission started at: $(date -u +%Y-%m-%dT%H:%M:%SZ)

Begin the mission now. Start with phase 1."

# --- Launch the orchestrator -----------------------------------------------
echo "[launch] handing off to mission orchestrator (claude) ..."
echo "────────────────────────────────────────────────────────────────"

START_EPOCH=$(date +%s)

# --dangerously-skip-permissions: required so sub-agents can curl/write without prompts
# --print: non-interactive, prints model output to stdout
if ! claude \
  --dangerously-skip-permissions \
  --print \
  "$ORCHESTRATOR_PROMPT"; then
  echo ""
  echo "  ✗ orchestrator exited non-zero — falling through to synthesizer"
fi

END_EPOCH=$(date +%s)
DURATION=$((END_EPOCH - START_EPOCH))

echo ""
echo "────────────────────────────────────────────────────────────────"
echo "[post] orchestrator returned after ${DURATION}s"

# --- Fallback synthesizer if orchestrator did not write report -------------
if [[ ! -f "$MISSION_DIR/MISSION_REPORT.md" ]]; then
  echo "[post] MISSION_REPORT.md missing — running fallback synthesizer"
  if command -v python3 >/dev/null 2>&1; then
    python3 "$SYNTH_FILE" "$MISSION_DIR" || echo "  ✗ fallback synthesizer failed"
  else
    echo "  ✗ python3 not found — cannot synthesize"
  fi
fi

# --- Final summary ----------------------------------------------------------
echo ""
echo "════════════════════════════════════════════════════════════════"
echo "  MISSION COMPLETE — ${DURATION}s"
echo ""
if [[ -f "$MISSION_DIR/MISSION_REPORT.md" ]]; then
  echo "  Report:    $MISSION_DIR/MISSION_REPORT.md"
else
  echo "  ⚠ No MISSION_REPORT.md produced. Raw phase files:"
fi
echo "  Phase files:"
ls -1 "$MISSION_DIR" 2>/dev/null | sed 's|^|    |'
echo "════════════════════════════════════════════════════════════════"
