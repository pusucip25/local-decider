"""Arbiter LOCAL via Ollaya (laya:multilingual, CPU) pe aceleasi 9 stari, prin /v1/systemone."""
import json, os, time, urllib.request

D = os.path.dirname(os.path.abspath(__file__))
API = os.environ.get("OLLAYA_API", "http://127.0.0.1:11435/v1/systemone")
MODEL = os.environ.get("OLLAYA_MODEL", "laya:multilingual")
pre = json.load(open(os.path.join(D, "harness_arbiter.json"), encoding="utf-8"))
states = [json.loads(l) for l in open(os.path.join(D, os.environ.get("SD_STATES", "arb_states2.jsonl")), encoding="utf-8") if l.strip()]
outp = os.path.join(D, os.environ.get("OLLAYA_OUT", "arb_scored_ollaya.jsonl"))
out = open(outp, "w", encoding="utf-8")
for i, o in enumerate(states):
    body = json.dumps({"model": MODEL, "state": o["stare"], "questions": pre["questions"]}, ensure_ascii=False).encode()
    req = urllib.request.Request(API, data=body, headers={"content-type": "application/json"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=600) as r:
            resp = json.loads(r.read().decode("utf-8"))
        rec = {"id": o["id"], "sec": round(time.time() - t0, 2), "truncated": resp.get("state_truncated"),
               "usage": resp.get("usage"), "answers": resp.get("answers") or resp.get("result", {}).get("answers", {})}
        print(f"[{i+1}/9] {o['id']:<34} {rec['sec']}s trunc={rec['truncated']} " +
              json.dumps({k: (v.get('choice') if v.get('type') == 'choice' else round(v.get('noul', -1), 2))
                          for k, v in (rec['answers'] or {}).items()}, ensure_ascii=False), flush=True)
    except Exception as e:
        rec = {"id": o["id"], "error": f"{type(e).__name__}: {e}"}
        print(f"[{i+1}/9] {o['id']} EROARE: {rec['error']}", flush=True)
    out.write(json.dumps(rec, ensure_ascii=False) + "\n"); out.flush()
out.close()
print("GATA ->", outp)
