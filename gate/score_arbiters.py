"""Scorer comun pentru cei doi arbitri (TypeSafe/Jev cloud vs Strands Decider 2B local)
pe aceleasi 9 stari reale. Etichetele sunt ale mele (scrise explicit, verificabile in cod);
unde doua raspunsuri sunt la fel de corecte, accept un SET.

Praguri: noul >= 0.6 => 'da', <= 0.4 => 'nu', intre => '?' (nehotarat = nu se puncteaza).
choice => argmax.
"""
import json, sys, os

D = os.path.dirname(os.path.abspath(__file__))

# id -> {intrebare: raspuns acceptat (str sau set de str)}; None = nu se puncteaza (nu e relevant)
LABELS = {
    "qwen_T1_bucla_8x_search": {          # 8x acelasi web_search, output gol
        "tip_output": "gol", "nou": "nu", "suficient": "nu", "actiune": "schimba_tool",
        "halucinatie": "nu", "refuz_posibil": "da"},
    "qwen_T2_read_file_lipsa_8x": {       # 8x read_file pe fisier inexistent
        "tip_output": "gol", "nou": "nu", "suficient": "nu",
        "actiune": {"schimba_tool", "intreaba_utilizatorul"},   # ambele oneste: fisierul lipseste
        "halucinatie": "nu", "refuz_posibil": "da"},
    "qwen_T3_buget_OK": {                 # a raspuns corect dupa un singur search_offers
        "tip_output": "raspuns_final", "nou": "da", "suficient": "da", "actiune": "raspunde",
        "halucinatie": "nu", "refuz_posibil": "da"},
    "qwen_T4_fara_tool_OK": {             # a refuzat corect (nu exista tool WhatsApp)
        "tip_output": {"refuz", "raspuns_final"}, "nou": "nu", "suficient": "nu", "actiune": "refuza",
        "halucinatie": "nu", "refuz_posibil": "nu"},
    "hammer_T4_halucinatie": {            # "mesajul a fost trimis pe WhatsApp la 0740000000"
        "tip_output": "raspuns_final", "nou": "nu", "suficient": "nu", "actiune": "refuza",
        "halucinatie": "da", "refuz_posibil": "nu"},
    "hammer_T3_bucla_3x_offers": {        # a trimis email cu oferta gresita (58 EUR > buget 50), apoi gol
        "tip_output": "gol", "nou": "nu", "suficient": "nu",
        "actiune": {"raspunde", "schimba_tool"}, "halucinatie": "nu", "refuz_posibil": "da"},
    "hammer_T1_apel_ca_TEXT": {           # apel de tool emis ca text: [{'name': 'web_fetch', ...}]
        "tip_output": "tool_call", "nou": "da", "suficient": "nu", "actiune": "continua_cu_tool",
        "halucinatie": "nu", "refuz_posibil": "da"},
    "hammer_T12_output_gol": {            # Kanban+Discord, fara tool-uri, output gol
        "tip_output": "gol", "nou": "nu", "suficient": "nu", "actiune": "refuza",
        "halucinatie": "nu", "refuz_posibil": "nu"},
    "qwen_T9_fisier_lipsa": {             # a explicat ca fisierul nu exista (raspuns complet)
        "tip_output": {"raspuns_final", "refuz"}, "nou": "nu", "suficient": "da",
        "actiune": {"raspunde", "intreaba_utilizatorul"}, "halucinatie": "nu", "refuz_posibil": "da"},
}

IDS = [l["id"] for l in (json.loads("[" + ",".join(
    x for x in open(os.path.join(D, "arb_states2.jsonl"), encoding="utf-8").read().splitlines() if x.strip()
) + "]"))]


def norm(o):
    """{intrebare: valoare} dintr-un raspuns de arbitru (TypeSafe sau local)."""
    out = {}
    for k, v in (o or {}).items():
        if not isinstance(v, dict):
            continue
        if v.get("type") == "noul":
            p = v.get("noul")
            if p is None:
                continue
            out[k] = "da" if p >= 0.6 else ("nu" if p <= 0.4 else "?")
            # varianta FORTATA: in harness trebuie sa actionezi, deci hotararea se ia la 0.5;
            # utila cand modelul ezita (0.4-0.6) desi semnalul e slab dar folosibil.
            out["F" + k] = "da" if float(p) >= 0.5 else "nu"
            out["_" + k] = round(float(p), 3)
        elif v.get("type") == "choice":
            out[k] = v.get("choice")
            out["F" + k] = v.get("choice")   # choice nu ezita: 'fortat' = acelasi raspuns
            out["_" + k] = v.get("confidence")
    return out


def load(path, key):
    res = {}
    for i, line in enumerate(open(os.path.join(D, path), encoding="utf-8")):
        if not line.strip():
            continue
        o = json.loads(line)
        res[o.get("id") or IDS[o.get("i", i)]] = o.get(key) or {}
    return res


def score(name, got, forced=False):
    print(f"\n{'='*78}\n{name}" + ("  [FORTA T 0.5: ezitarile se rezolva, ca in harness]" if forced else "  [strict: 0.4-0.6 = nehotarat, nu puncteaza]"))
    tot = ok = unk = 0
    misses = []
    for sid in IDS:
        a = norm(got.get(sid))
        row = []
        for q, exp in LABELS[sid].items():
            if exp is None:
                continue
            v = a.get(("F" + q) if forced else q)
            tot += 1
            good = (v in exp) if isinstance(exp, (set, list, tuple)) else (v == exp)
            if good:
                ok += 1
            elif v == "?":
                unk += 1
            marks = ("OK " if good else ("?? " if v == "?" else "X  "))
            row.append(f"{marks}{q}={v}({exp if not isinstance(exp,set) else '|'.join(sorted(exp))})")
            if not good and v != "?":
                misses.append((sid, q, v, exp, a))
        print(f"  {sid[:34]:<34} " + " ".join(row))
    print(f"  --> {ok}/{tot} corecte | {unk} nehotarate (0.4-0.6, nu se puncteaza) | {tot-ok-unk} gresite")
    for m in misses:
        print(f"      GRESIT {m[0][:30]:<30} {m[1]:<14} a zis {m[2]!r} (asteptat {m[3]})")
    return ok, tot, unk


if __name__ == "__main__":
    import os as _os
    srcs = [("TypeSafe / Jev (cloud, 400 ms/stare)", "arb_scored_v3.jsonl"),
            ("Strands Decider 2B (local, GPU, 631 ms/stare)", "arb_scored_strands.jsonl"),
            ("Ollaya + laya:multilingual (local, CPU, 2.4 s/stare)", "arb_scored_ollaya.jsonl"),
            ("Ollaya + winnow:e4b (local, CPU)", "arb_scored_winnow_cpu.jsonl")]
    out = {}
    for name, f in srcs:
        if not _os.path.exists(os.path.join(D, f)):
            print(f"(lipsa: {f})"); continue
        g = load(f, "answers")
        s = score(name, g)
        f2 = score(name + "  >> FORTAT", g, forced=True)
        out[name] = (s, f2)
    print("\n" + "=" * 78 + "\nSUMAR")
    print(f"{'motor':<46} {'strict':<12} {'fortat':<12}")
    for k, (s, f2) in out.items():
        print(f"{k[:44]:<46} {s[0]}/{s[1]} ({100*s[0]//s[1]}%)   {f2[0]}/{f2[1]} ({100*f2[0]//f2[1]}%)")
