"""Arbiter LOCAL (Strands Decider 2B, servit pe /v1/systemone) pe aceleasi 9 stari TypeSafe.
Presetul harness_arbiter.json se trimite NESCHIMBAT: acelasi 'state' + aceleasi 'questions'.
"""
import json, os, time, urllib.request

D = os.path.dirname(os.path.abspath(__file__))
API = os.environ.get("SD_API", "http://127.0.0.1:8010/v1/systemone")
pre = json.load(open(os.path.join(D, "harness_arbiter.json"), encoding="utf-8"))
QUESTIONS = pre["questions"]

ST = os.environ.get("SD_STATES", "arb_states2.jsonl")   # statele cu tooluri_disponibile (acelasi ca la TypeSafe)
states = [json.loads(l) for l in open(os.path.join(D, ST), encoding="utf-8") if l.strip()]
outp = os.path.join(D, "arb_scored_strands.jsonl")
out = open(outp, "w", encoding="utf-8")
tot_ms = 0
for i, o in enumerate(states):
    body = json.dumps({"state": o["stare"], "questions": QUESTIONS}, ensure_ascii=False).encode()
    req = urllib.request.Request(API, data=body, headers={"content-type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            resp = json.loads(r.read().decode("utf-8"))
        dt = time.time() - t0
        tot_ms += resp.get("latency_ms", dt * 1000)
        rec = {"id": o["id"], "sec": round(dt, 2), "latency_ms": resp.get("latency_ms"),
               "usage": resp.get("usage"), "answers": resp.get("answers", {})}
        print(f"[{i+1}/{len(states)}] {o['id']} | {resp.get('latency_ms')}ms | {json.dumps(rec['answers'], ensure_ascii=False)[:400]}", flush=True)
    except Exception as e:
        rec = {"id": o["id"], "error": f"{type(e).__name__}: {e}"}
        print(f"[{i+1}/{len(states)}] {o['id']} | EROARE: {rec['error']}", flush=True)
    out.write(json.dumps(rec, ensure_ascii=False) + "\n")
    out.flush()
out.close()
print(f"GATA -> {outp} | total inference {tot_ms:.0f} ms pentru {len(states)} stari")
