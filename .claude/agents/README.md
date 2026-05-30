# Sentinel Testing Subagents

Six specialized Claude Code subagents for heavy testing of the Sentinel fraud detection API. Dispatch them from the main session via the `Agent` tool by passing the subagent's `name` as `subagent_type`.

All agents assume the backend is reachable at `http://localhost:8000`. Bring it up first:

```bash
cd backend && source venv/bin/activate && uvicorn main:app --reload
# or
docker compose up --build
```

## The six

| Agent | Use for |
|---|---|
| [fraud-simulator](agents/fraud-simulator.md) | Generate realistic mixed traffic (LOW/MEDIUM/HIGH) to populate the dashboard and stress the classifier. |
| [attack-scenario-runner](agents/attack-scenario-runner.md) | Run named fraud playbooks (card-testing, ATO, smurfing, mule, geo-impossible, merchant-anomaly) and produce a detection coverage matrix. |
| [security-prober](agents/security-prober.md) | Confirm-or-deny each documented security weakness with live evidence (open CORS, no auth, no rate limit, prompt injection, irreversible freeze, input validation). |
| [load-tester](agents/load-tester.md) | Ramp concurrent requests on `/analyze` and report p50/p95/p99, throughput, knee point. |
| [edge-case-hunter](agents/edge-case-hunter.md) | Boundary values, malformed-but-not-malicious inputs, threshold-exact amounts, unicode, missing fields. |
| [regression-validator](agents/regression-validator.md) | API contract checks + fixed-fixture classification regression in heuristic mode (or model-drift detection in LLM mode). |

## How to use

From the main Claude Code session:

```
Run the attack-scenario-runner on the ATO and smurfing scenarios.
```

```
Use the security-prober to confirm the open-CORS and no-auth vulnerabilities.
```

```
Use load-tester to find the breaking point at concurrency 50.
```

You can also run several in parallel — they're independent except they all share the same in-memory SQLite. Restart the backend between runs if you want a clean slate:

```
Dispatch fraud-simulator and regression-validator in parallel.
```

## Coverage map

What each agent is responsible for, and where the lines are drawn:

- **fraud-simulator** = realistic traffic. *Not* targeted attacks (that's attack-scenario-runner).
- **attack-scenario-runner** = named fraud patterns from the real world. *Not* security exploits against the API itself (that's security-prober).
- **security-prober** = exploits against the API (auth, CORS, injection). *Not* fraud detection quality.
- **load-tester** = throughput/latency under concurrency. *Not* correctness.
- **edge-case-hunter** = malformed-but-not-malicious inputs. *Not* exploits (that's security-prober).
- **regression-validator** = contract + fixed-fixture classification. *Not* exploratory testing.

## State management

The backend uses in-memory SQLite (per [CLAUDE.md](../CLAUDE.md)) — it resets on every restart. After any agent that froze users or polluted the transaction list, restart the backend to reset:

```bash
# kill the uvicorn process, then re-run it
```

## Adding more agents

Drop a new `.md` file in `.claude/agents/` with the same frontmatter shape:

```yaml
---
name: short-kebab-name
description: When to invoke this agent (used by the main session to decide).
tools: Bash, Read   # optional — restricts which tools the subagent can use
model: sonnet       # optional — defaults to the main session's model
---

System prompt: instructions, defaults, workflow, rules.
```
