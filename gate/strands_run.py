"""Ruleaza arbiterul LOCAL (Strands Decider 2B) pe aceleasi 9 stari date la TypeSafe.
Test cap-la-cap: decizie locala, cost 0, fara API, fara date personale trimise in afara.
"""
import json, subprocess, sys, os, time

D = os.path.dirname(os.path.abspath(__file__))
PY = r"C:/Users/Pusu/tools/strands-venv/Scripts/strands-decider.exe"
CKPT = os.environ.get("SD_CKPT", "StrandsAgents/strands-decider-2B-hobson-v19")
DEV = os.environ.get("SD_DEVICE", "cpu")

pre = json.load(open(os.path.join(D, "harness_arbiter.json"), encoding="utf-8"))
Q = pre["questions"]
ORDER = list(Q.keys())            # tip_output, nou, suficient, actiune, refuz_posibil


def flat(t):
    return " ".join(str(t).split()).replace(",", ";")


def args_for(state):
    a = ["--state", json.dumps(state, ensure_ascii=False), "--json", "--device", DEV]
    for name in ORDER:
        q = Q[name]
        instr = flat(q.get("instructions", name))
        if q["type"] == "noul":
            a += ["--noul", instr]
        elif q["type"] == "choice":
            opts = ",".join(q["criteria"].keys())
            a += ["--choice", f"{instr}?={opts}"]
    return a


states = [json.loads(l) for l in open(os.path.join(D, "arb_states.jsonl"), encoding="utf-8") if l.strip()]
out = open(os.path.join(D, "arb_scored_strands.jsonl"), "w", encoding="utf-8")
for i, o in enumerate(states):
    t0 = time.time()
    cmd = [PY, "ask", CKPT] + args_for(o["stare"])
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900)
        raw = r.stdout.strip()
        try:
            resp = json.loads(raw)
        except Exception:
            resp = {"_raw": raw[:800], "_err": r.stderr[-400:]}
        dt = time.time() - t0
        rec = {"id": o["id"], "sec": round(dt, 2), "answers": (resp.get("answers") or resp)}
        print(f"[{i+1}/{len(states)}] {o['id']} | {dt:.1f}s | {json.dumps(rec['answers'], ensure_ascii=False)[:420]}", flush=True)
    except Exception as e:
        rec = {"id": o["id"], "error": f"{type(e).__name__}: {e}"}
        print(f"[{i+1}/{len(states)}] {o['id']} | EROARE: {rec['error']}", flush=True)
    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    out.flush()
out.close()
print("GATA ->", os.path.join(D, "arb_scored_strands.jsonl"))
