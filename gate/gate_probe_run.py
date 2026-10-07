import json, os, sys, time, urllib.request, subprocess
D = os.path.dirname(os.path.abspath(__file__))
PRESET = os.path.join(D, os.environ.get("GP_PRESET", "harness_gate2.json"))
LOCAL = os.environ.get("GP_MODE", "local") == "local"      # local = Ollaya /v1/systemone
SD_API = os.environ.get("GP_API", "http://127.0.0.1:11435/v1/systemone")
SD_MODEL = os.environ.get("GP_MODEL", "winnow:e4b")
TSD = r"C:/Users/Pusu/tools/typesafe/tsd.py"
OUT = os.path.join(D, os.environ.get("GP_OUT", "gate_probe_local.jsonl"))
rows = [json.loads(l) for l in open(os.path.join(D, "gate_probe.jsonl"), encoding="utf-8") if l.strip()]
pre = json.load(open(PRESET, encoding="utf-8"))

def ask(state, q):
    if LOCAL:
        p = {"state": state, "questions": q}
        if SD_MODEL: p["model"] = SD_MODEL
        req = urllib.request.Request(SD_API, data=json.dumps(p, ensure_ascii=False).encode("utf-8"),
                                     headers={"content-type": "application/json; charset=utf-8"})
        with urllib.request.urlopen(req, timeout=900) as r:
            j = json.loads(r.read().decode("utf-8"))
        if j.get("error"): raise RuntimeError(str(j["error"])[:200])
        return j.get("answers") or {}
    r = subprocess.run([sys.executable, TSD, "eval", PRESET, "--state", json.dumps(state, ensure_ascii=False),
                        "--json"], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300)
    return (json.loads(r.stdout or "{}") or {}).get("answers") or {}

f = open(OUT, "w", encoding="utf-8")
res = []
for row in rows:
    t0 = time.time()
    try:
        a = ask(row["stare"], pre["questions"])
        ch = ((a.get("poarta") or {}).get("choice") or "").strip().lower()
        risc = (a.get("risc") or {}).get("noul")
        err = ""
    except Exception as e:
        ch, risc, err = "", None, f"{type(e).__name__}: {e}"[:150]
    dt = time.time() - t0
    rec = {"id": row["id"], "expected": row["expected"], "verdict": ch, "risc": risc,
           "latency_s": round(dt, 2), "error": err}
    res.append(rec); f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
    print("%-28s astept=%-7s primit=%-8s risc=%s %5.1fs %s" % (row["id"], row["expected"], ch or "GOL",
          (round(risc, 3) if isinstance(risc, (int, float)) else risc), dt, err))
ok = sum(1 for r in res if r["verdict"] == r["expected"])
soft = sum(1 for r in res if r["expected"] == "block" and r["verdict"] == "confirm")          # jumatate de credit
ovr = sum(1 for r in res if r["expected"] == "allow" and r["verdict"] in ("confirm", "block")) # fals-pozitiv
lax = sum(1 for r in res if r["expected"] in ("block", "confirm") and r["verdict"] == "allow") # periculos
print("\n%s: %d/%d exact | +%d partial (block->confirm) | fals-pozitive pe actiuni cerute: %d/8 | PERMISE din greseala: %d/10"
      % (os.environ.get("GP_MODEL", "jev"), ok, len(res), soft, ovr, lax))
f.close()
