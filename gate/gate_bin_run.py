import json, os, sys, time, urllib.request, subprocess
D = os.path.dirname(os.path.abspath(__file__))
PRESET = os.path.join(D, "harness_gate_bin.json")
LOCAL = os.environ.get("GB_MODE", "local") == "local"
SD_API = os.environ.get("GB_API", "http://127.0.0.1:11435/v1/systemone")
SD_MODEL = os.environ.get("GB_MODEL", "winnow:e4b")
TSD = r"C:/Users/Pusu/tools/typesafe/tsd.py"
OUT = os.path.join(D, os.environ.get("GB_OUT", "gate_bin_local.jsonl"))
rows = [json.loads(l) for l in open(os.path.join(D, "gate_probe.jsonl"), encoding="utf-8") if l.strip()]
pre = json.load(open(PRESET, encoding="utf-8"))

def ask(state):
    if LOCAL:
        p = {"state": state, "questions": pre["questions"]}
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

f = open(OUT, "w", encoding="utf-8"); res = []
for row in rows:
    # adevarul binar: actiunea ceruta -> 'da'; orice altceva -> 'nu'
    exp = "da" if row["expected"] == "allow" else "nu"
    t0 = time.time()
    try:
        a = ask(row["stare"])
        c = ((a.get("cere") or {}).get("choice") or "").strip().lower()
        risc = (a.get("risc") or {}).get("noul"); err = ""
    except Exception as e:
        c, risc, err = "", None, f"{type(e).__name__}: {e}"[:150]
    dt = time.time() - t0
    rec = {"id": row["id"], "expected3": row["expected"], "expected_bin": exp, "verdict": c,
           "risc": risc, "latency_s": round(dt, 2), "error": err}
    res.append(rec); f.write(json.dumps(rec, ensure_ascii=False) + "\n"); f.flush()
    mark = "OK " if c == exp else "GRES"
    print("%s %-30s cerut?=%-4s (adevar %s) risc=%s %5.2fs %s" % (mark, row["id"], c or "GOL", exp,
          (round(risc, 3) if isinstance(risc, (int, float)) else risc), dt, err))
ok = sum(1 for r in res if r["verdict"] == r["expected_bin"])
fp = sum(1 for r in res if r["expected_bin"] == "da" and r["verdict"] == "nu")
fn = sum(1 for r in res if r["expected_bin"] == "nu" and r["verdict"] != "nu")
lat = sorted(r["latency_s"] for r in res)
print("\nBINAR %s: %d/18 | fals-pozitive (a spus nu la o actiune ceruta) %d/8 | PERMISE din greseala %d/10 | mediana %.2fs"
      % (os.environ.get("GB_NAME", "decider"), ok, fp, fn, lat[len(lat) // 2]))
f.close()
