#!/usr/bin/env python3
"""Fallback mission synthesizer.

Used when the orchestrator finishes without producing MISSION_REPORT.md.
Assembles a minimal report from whatever phase JSONs exist in MISSION_DIR.

Usage: python3 synthesize_mission.py <MISSION_DIR>
"""
import json
import sys
from datetime import datetime, timezone
from pathlib import Path


PHASE_ORDER = [
    ("01-regression",   "Regression — API Contract & Baseline"),
    ("02-fraud-sim",    "Fraud Simulation — Realistic Traffic"),
    ("03-edge-cases",   "Edge Cases — Boundary Bugs"),
    ("04-attacks",      "Attack Scenarios — Detection Coverage"),
    ("05-security",     "Security — Confirmed Vulnerabilities"),
    ("06-load",         "Performance — Load Profile"),
]


def load_json(path: Path):
    try:
        with path.open() as f:
            return json.load(f)
    except Exception as e:
        return {"_error": f"failed to parse {path.name}: {e}"}


def safe_get(d, *keys, default="—"):
    for k in keys:
        if not isinstance(d, dict) or k not in d:
            return default
        d = d[k]
    return d if d not in (None, "") else default


def render_phase(slug: str, title: str, data: dict) -> str:
    out = [f"## {title}", ""]
    if "_error" in data:
        out.append(f"_Could not load phase data: {data['_error']}_")
        out.append("")
        return "\n".join(out)

    out.append(safe_get(data, "summary", default="_(no summary recorded)_"))
    out.append("")

    findings = data.get("findings", {}) or {}
    if findings:
        out.append("**Findings:**")
        out.append("")
        out.append("```json")
        out.append(json.dumps(findings, indent=2)[:4000])
        out.append("```")
        out.append("")

    brief = data.get("brief_for_next")
    if brief:
        out.append(f"**Handoff to next phase:** {brief}")
        out.append("")

    return "\n".join(out)


def main():
    if len(sys.argv) < 2:
        print("usage: synthesize_mission.py <MISSION_DIR>", file=sys.stderr)
        sys.exit(2)

    mission_dir = Path(sys.argv[1]).resolve()
    if not mission_dir.is_dir():
        print(f"not a directory: {mission_dir}", file=sys.stderr)
        sys.exit(2)

    sections = []
    sections.append("# Sentinel Mission Report")
    sections.append("")
    sections.append(f"**Generated (fallback synthesizer):** "
                    f"{datetime.now(timezone.utc).isoformat()}")
    sections.append(f"**Mission Dir:** `{mission_dir}`")
    sections.append("")

    # Mode + global stats — derive from whatever is present
    txn_total = 0
    frozen = set()
    detected = 0
    missed = 0
    vulns_confirmed = 0
    edge_bugs = 0
    knee = "—"

    summaries = {}
    for slug, _ in PHASE_ORDER:
        path = mission_dir / f"{slug}.json"
        if path.exists():
            summaries[slug] = load_json(path)
        else:
            summaries[slug] = {"_error": f"{slug}.json not written"}

    fs = summaries.get("02-fraud-sim", {}).get("findings", {}) or {}
    txn_total = int(fs.get("sent", 0) or 0)
    for u in (fs.get("frozen_users") or []):
        frozen.add(u)

    atk = summaries.get("04-attacks", {}).get("findings", {}) or {}
    detected = int(atk.get("detected", 0) or 0)
    missed = int(atk.get("missed", 0) or 0)

    sec = summaries.get("05-security", {}).get("findings", {}) or {}
    vulns_confirmed = int(sec.get("confirmed", 0) or 0)
    for u in (sec.get("frozen_users") or []):
        frozen.add(u)

    edges = summaries.get("03-edge-cases", {}).get("findings", {}) or {}
    edge_bugs = int(edges.get("fail", 0) or 0) + int(edges.get("surprise", 0) or 0)

    load = summaries.get("06-load", {}).get("findings", {}) or {}
    knee = load.get("knee_concurrency", "—")

    sections.append("## Executive summary")
    sections.append("")
    sections.append(f"- Transactions analyzed: **{txn_total}**")
    sections.append(f"- Accounts frozen: **{len(frozen)}** "
                    f"({', '.join(sorted(frozen)) if frozen else 'none'})")
    sections.append(f"- Attack detection: **{detected}** detected / "
                    f"**{detected + missed}** run")
    sections.append(f"- Confirmed vulnerabilities: **{vulns_confirmed}**")
    sections.append(f"- Edge bugs / surprises: **{edge_bugs}**")
    sections.append(f"- Performance knee: **{knee} concurrent**")
    sections.append("")
    sections.append("---")
    sections.append("")

    for slug, title in PHASE_ORDER:
        sections.append(render_phase(slug, title, summaries[slug]))
        sections.append("---")
        sections.append("")

    sections.append("## Note")
    sections.append("")
    sections.append("_This report was assembled by the fallback synthesizer "
                    "because the orchestrator did not finish writing "
                    "MISSION_REPORT.md itself. The data above is the raw "
                    "JSON output from each phase; structure may be terser "
                    "than the full orchestrator-authored report._")
    sections.append("")

    out_path = mission_dir / "MISSION_REPORT.md"
    out_path.write_text("\n".join(sections), encoding="utf-8")
    print(f"  ✓ wrote {out_path}")


if __name__ == "__main__":
    main()
