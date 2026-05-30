# Sentinel — Project Notes for Claude

Autonomous real-time fraud detection. FastAPI backend + Next.js dashboard, DeepSeek-powered agent with a deterministic heuristic fallback.

## Layout

- `backend/` — FastAPI app. Entry: `main.py`. Agent: `agent.py`. SQLite in-memory: `database.py`.
- `frontend/` — Next.js 14 App Router. State: `app/context/TransactionContext.tsx` (3s poll).
- `scripts/simulate_attack.sh` — demo driver (5 normal + 3 HIGH-risk txns).
- `docker-compose.yml` — single command to bring everything up.

## Dev Commands

Backend (local):
```
cd backend && source venv/bin/activate
pip install -r requirements.txt    # first time only
uvicorn main:app --reload
```

Frontend (local):
```
cd frontend && npm run dev
```

Everything together:
```
cp .env.example .env && docker compose up --build
```

Run the backend test:
```
cd backend && ./venv/bin/python test_agent.py
```

## Conventions

- **Agent mock-mode**: when `DEEPSEEK_API_KEY` is empty or `"your_key_here"`, `agent.py` uses a deterministic heuristic (`amount ≥ 5000` OR `amount ≥ 30× user avg` → HIGH). Real DeepSeek calls only fire with a real key. On API exceptions, fall back to the heuristic with the error annotated.
- **In-memory SQLite**: resets every process restart. Don't add migrations — just edit the `CREATE TABLE` blocks in `database.py`.
- **CORS is open** (`allow_origins=["*"]`). Hackathon only; tighten before any real deployment.
- **Frontend env**: `NEXT_PUBLIC_API_URL` baked at build time. In Compose, set to `http://localhost:8000` (the browser runs on the host, not inside the network).
- **Risk levels**: stored as `risk_level` column (`LOW`/`MEDIUM`/`HIGH`) plus `fraud_score` (0.0/0.5/1.0). Frontend reads `risk_level` directly.
- **Autonomous freeze**: any HIGH risk → `freeze_user(user_id)` flips `users.account_frozen = 1` and sets the transaction's `action_taken = "account_frozen"`.

## Key Files

- `backend/agent.py` — DeepSeek client + `_heuristic` fallback + `analyze_transaction`.
- `backend/main.py` — `/`, `/transactions`, `/analyze`.
- `frontend/app/context/TransactionContext.tsx` — polling, diff for fade-in, `simulate()` helper.
- `frontend/app/page.tsx` — stats bar + colored-row table + Simulate button.

## Testing Subagents

Six Claude Code subagents live in [.claude/agents/](.claude/agents/) for heavy testing of the running API. Dispatch via `Agent(subagent_type="<name>")`. See [.claude/agents/README.md](.claude/agents/README.md) for the full map.

- `fraud-simulator` — realistic mixed traffic.
- `attack-scenario-runner` — named fraud playbooks (ATO, smurfing, mule, geo-impossible, …) → detection coverage matrix.
- `security-prober` — confirm-or-deny each documented security weakness with live evidence.
- `load-tester` — concurrency ramp on `/analyze`, p50/p95/p99 + knee point.
- `edge-case-hunter` — boundary values, malformed-but-not-malicious inputs.
- `regression-validator` — API contract + fixed-fixture classification (heuristic mode) or model-drift detection (LLM mode).

All assume `http://localhost:8000` and a running backend. Restart the backend between runs to reset the in-memory SQLite.

## Mission Mode — one-command full sweep

```
./scripts/run_mission.sh
```

This is the unified entrypoint. It:

1. Health-checks the backend.
2. Creates `reports/mission-<timestamp>/`.
3. Invokes the `claude` CLI with [scripts/MISSION_PROMPT.md](scripts/MISSION_PROMPT.md) — that prompt makes Claude the orchestrator.
4. The orchestrator dispatches all 6 specialists sequentially via the `Agent` tool:
   `regression-validator` → `fraud-simulator` → `edge-case-hunter` → `attack-scenario-runner` → `security-prober` → `load-tester`.
5. Each specialist reads prior phase JSONs from `$MISSION_DIR`, runs its work, and writes `NN-name.json` + `.md`.
6. The orchestrator synthesizes `MISSION_REPORT.md` from all six JSONs.
7. Fallback: if the orchestrator did not produce the report, `scripts/synthesize_mission.py` renders one from the raw JSONs.

Three communication layers, stacked:
- **Shared report file** — every agent writes to `$MISSION_DIR/`. Replayable, debuggable.
- **Orchestrator relay** — main Claude distills each agent's result and primes the next.
- **Named handoffs** — JSON `brief_for_next` field per phase. Order matters; load-tester runs last because it stresses the system.

Outputs:
- `reports/mission-<ts>/01-regression.{json,md}` … `06-load.{json,md}`
- `reports/mission-<ts>/MISSION_REPORT.md` — the document to show in the demo.

## Gotchas

- Pydantic v2: use `model_dump()` not `dict()`.
- `python3 -m venv venv` — venv lives at `backend/venv/`, gitignored.
- Tailwind v4 may ship in fresh `create-next-app` scaffolds; `globals.css` may use `@import "tailwindcss"` instead of three `@tailwind` directives. Check before editing.
- The fade-in animation key is `animate-fade-in` (defined in `globals.css`); applied only to IDs in the context's `newIds` set for ~700ms.

## Avoiding "Stream idle timeout — partial response received"

This is a Claude Code client↔API transport error, not a bug in this repo. It fires when a single turn streams too much output without a pause. To keep each streaming chunk small enough that the idle timeout never trips:

- Do numbered/multi-part tasks **one at a time**, not all in one turn.
- Never write or edit a file longer than ~150 lines in a single tool call — split large writes into multiple passes.
- Don't dump huge command output: pipe long results through `head`/`tail`/`wc -l`, or write to a file and read the slice you need.
- Run the heavy testing subagents (`load-tester`, `attack-scenario-runner`) **directly from the orchestrator**, not nested, and keep their loops short — they are the most common trigger (see also reports/ notes on subagent stream-idle timeouts).
- Start a fresh session once a conversation gets long (~20+ tool calls); the error gets more likely the longer the session runs.
- If it still fires, just retry the turn — a partial-response timeout is transient. Raising `CLAUDE_STREAM_IDLE_TIMEOUT_MS` is unreliable; reducing per-turn output is what actually works.
