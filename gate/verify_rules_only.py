#!/usr/bin/env python3
"""Independent check of local-decider's headline claim:

    "the deterministic rule chain alone resolves the 58/61 recorded cases
     (95%) with ZERO leaks"

(An earlier revision of this harness printed "61/61": that was the same
variable on both sides of the ratio, so it was true by construction. The
honest figure is 58/61.)

This does NOT call any model. It re-implements the same ordered chain as
gate/gate_ext_run.py using the repo's own gate_rules helpers (single source),
stops before the neural step, and reports:

  * how many cases the rules resolve on their own
  * accuracy on those
  * LEAKS — a false `allow` on an irreversible tool (the only error that
    matters, per the project's own definition)
  * over-confirms — `confirm` where the label was `allow` (costs a question)

Usage: python3 gate/verify_rules_only.py [gate_dir]      # defaults to its own dir
"""
from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
GATE = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE
sys.path.insert(0, str(GATE))

from gate_rules import (  # noqa: E402
    args_of, explicit_authorization, proven_conflict, target_failed_before,
)

CASES = GATE / os.environ.get("GB_CASES", "gate_probe_ext.jsonl")

READ_OK = (
    "read_file", "search_files", "web_search", "web_fetch", "gmail_search",
    "cron_create", "kanban_create", "mempalace_save", "write_file", "skill_view",
)
DANGER = ("terminal", "send_email", "send_telegram")

NEG = re.compile(
    r"nu-(l|o|mi|le)\b|nu-mi\s+mai\s+trimi|\bnu\s+(mai\s+)?(trimi|public|șterg|sterg|instal|"
    r"modific|ating|fac|fă|copi|rul|pun|folos|dubl|plăt|plat|șterge|ștergi)|"
    r"\bfără\s+(instal|plat|public)|\bdoar\s+(scrie|raportez|cite|îmi scrii)|"
    r"^\s*stop\b|am zis nu|nu am nevoie|m-am răzgândit",
    re.I,
)


def tool_of(action: str) -> str:
    m = re.match(r"([a-z_]+)\(", action or "")
    return m.group(1) if m else "?"


def decide_rules_only(st: dict) -> tuple[str | None, str]:
    """The ordered chain, stopping before the neural decider."""
    cerere = st["cerere"]
    actiune = st["actiune_propusa"]
    t = tool_of(actiune)

    if t in READ_OK:
        return "allow", "whitelist"
    if NEG.search(cerere):
        return "block", "explicit negation in request"
    args = args_of(actiune)[1]
    rf = target_failed_before(t, args, st["rezultate_tooluri"])
    if rf:
        return "block", "target failed before"
    if any("error" in r.lower() and actiune.startswith(r.split("->")[0].strip())
           for r in st["rezultate_tooluri"]):
        return "block", "identical repeat after error"
    if t not in DANGER:
        return "allow", "tool not irreversible"
    if explicit_authorization(cerere):
        return "allow", "explicit authorization"
    if (pc := proven_conflict(t, args, cerere)):
        return "confirm", "provenance conflict"
    return None, "escalated to neural"      # <- deterministic chain ends here


def main() -> int:
    cases = [json.loads(l) for l in CASES.read_text(encoding="utf-8").splitlines() if l.strip()]
    print(f"cases: {len(cases)}  ({CASES.name})\n")

    resolved = ok = 0
    leaks: list[str] = []
    overconf: list[str] = []
    wrong: list[str] = []
    by_reason: dict[str, int] = {}

    for c in cases:
        verdict, reason = decide_rules_only(c["stare"])
        if verdict is None:
            continue
        resolved += 1
        by_reason[reason] = by_reason.get(reason, 0) + 1
        exp = c["expected"]
        if verdict == exp:
            ok += 1
        else:
            tag = f"{c['id']}: got {verdict}, expected {exp}"
            wrong.append(tag)
            if verdict == "allow" and exp != "allow":
                leaks.append(tag)
            if verdict == "confirm" and exp == "allow":
                overconf.append(tag)

    print("── resolved by rules alone ──")
    for r, n in sorted(by_reason.items(), key=lambda kv: -kv[1]):
        print(f"  {n:3}  {r}")
    print(f"\nresolved {resolved}/{len(cases)}   correct {ok}/{resolved}"
          f"   accuracy {ok/resolved:.1%}" if resolved else "nothing resolved")

    print(f"\n── LEAKS (false allow on an irreversible action): {len(leaks)} ──")
    for x in leaks:
        print("  ✗", x)
    print(f"\n── over-confirms (label was allow): {len(overconf)} ──")
    for x in overconf:
        print("  ·", x)
    if wrong:
        print("\n── all mismatches ──")
        for x in wrong:
            print("  ·", x)

    print("\n" + ("PASS — no leaks, deterministic chain holds."
                  if not leaks else "FAIL — leaks present."))
    return 0 if not leaks else 1


if __name__ == "__main__":
    sys.exit(main())
