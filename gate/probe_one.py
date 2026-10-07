import json, time, urllib.request, sys, os
D = os.path.dirname(os.path.abspath(__file__))
pre = json.load(open(os.path.join(D, "harness_arbiter.json"), encoding="utf-8"))
states = [json.loads(l) for l in open(os.path.join(D, "arb_states2.jsonl"), encoding="utf-8") if l.strip()]
idx = int(sys.argv[1]) if len(sys.argv) > 1 else 0
model = sys.argv[2] if len(sys.argv) > 2 else "winnow:e4b"
body = json.dumps({"model": model, "state": states[idx]["stare"], "questions": pre["questions"]}, ensure_ascii=False).encode("utf-8")
req = urllib.request.Request("http://127.0.0.1:11435/v1/systemone", data=body, headers={"content-type": "application/json; charset=utf-8"})
t0 = time.time()
with urllib.request.urlopen(req, timeout=900) as r:
    j = json.loads(r.read().decode("utf-8"))
dt = time.time() - t0
print(f"{states[idx]['id']} | {dt:.1f}s | usage {j.get('usage')} | trunc {j.get('state_truncated')}")
for k, v in (j.get("answers") or {}).items():
    print("  ", k, "=", v.get("choice") if v.get("type") == "choice" else round(v.get("noul", -1), 3))
