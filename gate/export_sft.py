"""F0: transforma rulările de benchmark in corpus de antrenament (SFT + corectii).

Reconstruieste conversatiile complete prin replay determinist al simularorilor din bench.py
(handlerele sunt pure: acelasi args -> acelasi rezultat), apoi emite:
  sft.jsonl         -> traiectorii complete reusite (politica corecta pas cu pas)
  corrections.jsonl -> unde modelul a intrat in bucla: starea + actiunea corecta (contrast)
"""
import json, sys, pathlib

sys.path.insert(0, r"C:\Users\Pusu\tools\local-model-bench")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import bench as B

OUT = pathlib.Path(r"C:\Users\Pusu\tools\local-model-bench\corpus")
OUT.mkdir(exist_ok=True)
SRC = sorted(pathlib.Path(r"C:\Users\Pusu\tools\local-model-bench").glob("results_*.json"))

# actiunea corecta cand modelul a intrat in bucla (referinta per task)
CORRECTII = {
    "T1_outreach": {
        "drum": ["web_search"],
        "corect": {"tool": "web_fetch", "args": {"url": "https://firmaa.ro"}},
        "motiv": "rezultatul contine deja URL-urile firmelor; urmatorul pas e sa iei datele de pe "
                 "pagina, nu sa repeti cautarea cu alta formulare",
    },
    "T2_email_retry": {
        "drum": ["read_file"],
        "corect": {"tool": "send_email", "args": {"to": "contact@firmaa.ro", "subject": "Oferta site",
                                                  "body": "<continutul outreach.md>"}},
        "motiv": "fisierul lipseste: se raporteaza explicit sau se ridica o intrebare, nu se reia "
                 "citirea aceluiasi path",
    },
    "T11_extract_retry": {
        "drum": ["browser_extract"],
        "corect": {"tool": "web_fetch", "args": {"url": "https://firmaa.ro"}},
        "motiv": "dupa eroare de selector se schimba unealta (web_fetch), nu se reincearca "
                 "selectorul cu alta formulare",
    },
    "T8_contradiction": {
        "drum": [],
        "corect": {"tool": None, "args": {"final": "Cerinta se contrazice: mai intai imi ceri sa sterg "
                                          "fisierul, apoi sa nu-l sterg. Nu am sters nimic. Confirma "
                                          "care varianta e valabila."}},
        "motiv": "cerinta contradictorie -> nu ghici si nu executa, semnaleaza si cere clarificare",
    },
}


def tool_schemas(names):
    pool = dict(B.SPECIAL)
    pool.update(B.FILLER)
    return [pool[n] for n in names if n in pool]


def replay(run, avail):
    """Reconstruieste mesajele conversatiei cu rezultatele reale ale simularilor."""
    ctx = {"files": {}, "calls": [], "counters": {}, "available": avail}
    msgs = []
    for c in run["calls"]:
        if isinstance(c, (list, tuple)):          # format vechi: [nume, args]
            c = {"name": c[0], "args": c[1]}
        msgs.append({"role": "assistant", "content": "",
                     "tool_calls": [{"id": f"call_{len(msgs)}", "type": "function",
                                     "function": {"name": c["name"],
                                                  "arguments": json.dumps(c["args"], ensure_ascii=False)}}]})
        h = B.HANDLERS.get(c["name"], B.default_handler)
        try:
            res = h(c["args"], ctx)
        except Exception as e:
            res = {"error": f"{type(e).__name__}: {e}"}
        ctx["calls"].append({"name": c["name"], "args": c["args"], "result": res})
        msgs.append({"role": "tool", "tool_call_id": f"call_{len(msgs)-1}",
                     "content": json.dumps(res, ensure_ascii=False)})
    return msgs


def main():
    n_sft = n_corr = 0
    sample = None
    tasks = {t["id"]: t for t in B.TASKS()}
    for src in SRC:
        data = json.loads(src.read_text(encoding="utf-8"))
        for cond in data:
            avail = [t["function"]["name"] for t in (B.SMALL if cond == "SMALL" else B.BIG)]
            system = B.SMALL_PROMPT if cond == "SMALL" else B.BIG_PROMPT
            for run in data[cond]:
                task = tasks[run["id"]]
                head = [{"role": "system", "content": system},
                        {"role": "user", "content": task["user"]}]
                traj = replay(run, avail)
                tools = tool_schemas(avail)
                rec = {"task": run["id"], "cond": cond, "tools": tools,
                       "messages": head + traj}
                if run.get("success") is True and (run.get("final") or "").strip():
                    rec["messages"].append({"role": "assistant", "content": run["final"]})
                    with (OUT / "sft.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                    n_sft += 1
                    sample = sample or rec

                loop = run.get("max_same_tool_run", 0) >= 3
                if loop or (not (run.get("final") or "").strip()):
                    spec = CORRECTII.get(run["id"])
                    if not spec:
                        continue
                    def nm(c):
                        return c[0] if isinstance(c, (list, tuple)) else c["name"]
                    seq = [nm(c) for c in run["calls"]]
                    cut = len(seq)
                    for i in range(1, len(seq)):
                        if seq[i] == seq[i - 1] == (spec["drum"][0] if spec["drum"] else None):
                            cut = i
                            break
                    good = head + replay({"calls": run["calls"][:cut]}, avail)
                    if spec["corect"]["tool"] is None:
                        good.append({"role": "assistant", "content": spec["corect"]["args"]["final"]})
                    else:
                        good.append({"role": "assistant", "content": "", "tool_calls": [
                            {"id": "call_fix", "type": "function", "function": {
                                "name": spec["corect"]["tool"],
                                "arguments": json.dumps(spec["corect"]["args"], ensure_ascii=False)}}]})
                    crec = {"task": run["id"], "cond": cond, "tools": tools,
                            "stare_gresita": run["calls"][cut:cut + 3],
                            "motiv": spec["motiv"],
                            "messages": good}
                    with (OUT / "corrections.jsonl").open("a", encoding="utf-8") as f:
                        f.write(json.dumps(crec, ensure_ascii=False) + "\n")
                    n_corr += 1

    print(f"surse: {[s.name for s in SRC]}")
    print(f"SFT      : {n_sft} traiectorii -> {OUT / 'sft.jsonl'}")
    print(f"corectii : {n_corr} exemple de contrast -> {OUT / 'corrections.jsonl'}")
    if sample:
        m = sample["messages"]
        print("\n--- exemplu inregistrare SFT (task, cond, tools, nr mesaje) ---")
        print(sample["task"], "|", sample["cond"], "|", len(sample["tools"]), "tool-uri |", len(m), "mesaje")
        print("system:", m[0]["content"][:90].replace("\n", " "), "...")
        print("user  :", m[1]["content"][:90])
        print("pas1  :", m[2]["tool_calls"][0]["function"]["name"], m[2]["tool_calls"][0]["function"]["arguments"][:70])
        print("rez1  :", m[3]["content"][:100])
        print("ultim :", (m[-1].get("content") or str(m[-1].get("tool_calls")))[:110])


if __name__ == "__main__":
    main()
