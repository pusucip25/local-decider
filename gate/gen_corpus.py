"""F0 bulk: generator de corpus sintetic pentru antrenarea politicii de harness.

Nu foloseste niciun LLM. Construieste traiectorii VALIDE (oracol scriptat) peste acelasi
contract de tool-uri ca bench.py, apoi genereaza perechi de preferinta (actiune corecta vs
actiune gresita) pentru fiecare tipar de eroare masurat pe modelul real:

    repeat_same_tool   - reia tool-ul cu acelasi input (cauza nr.1 masurata: 0/24 tool inventat, dar bucle)
    skip_step          - scrie fara sa fi citit sursa
    ignore_constraint  - ignora bugetul/limita din cerinta
    premature_final    - raspunde final inainte de rezultatul tool-ului
    invented_tool      - apeleaza o unealta care nu exista in suprafata
    wrong_tool         - foloseste unealta nepotrivita (cauta in loc sa extraga)
    loop_after_error   - reincearca identic dupa eroare, in loc sa schimbe abordarea
    hallucinate_result - inventeaza date pe care nu le-a primit

Iesire: corpus/sft_sintetic.jsonl si corpus/pref_sintetic.jsonl (+ raport pe tipare).
"""
import json, random, sys, pathlib

sys.path.insert(0, r"C:\Users\Pusu\tools\local-model-bench")
sys.stdout.reconfigure(encoding="utf-8", errors="replace")
import bench as B

OUT = pathlib.Path(r"C:\Users\Pusu\tools\local-model-bench\corpus")
OUT.mkdir(exist_ok=True)
N = int(sys.argv[1]) if len(sys.argv) > 1 else 1000
RNG = random.Random(20261006)

CITIES = ["Turda", "Cluj-Napoca", "Dej", "Câmpia Turzii", "Gherla", "Bistrița", "Alba Iulia", "Sibiu", "Oradea", "Târgu Mureș"]
SECTORS = ["dental", "service auto", "cabinet avocat", "florărie", "cofetărie", "salon", "contabilitate", "fitness"]
DOMS = ["firmaa.ro", "dental-turda.ro", "avocat-cluj.ro", "service-dej.ro", "flori-bistrita.ro", "cofetarie-sibiu.ro",
        "cabinet-contabil-alba.ro", "fit-oradea.ro", "pensiune-gherla.ro", "atelier-tm.ro"]
FILES = ["outreach.md", "oferte.md", "raport.md", "clienti.md", "lista-firme.md", "analiza.md"]
ERRS = ["smtp_timeout: Connection timed out după 30s", "503 Service Unavailable", "connection_reset", "rate_limit: 429"]
BUDGETS = [20, 30, 50, 80, 100, 150]
TOOL_GHOST = ["google_search", "browse_web", "send_whatsapp", "scrape_all"]


def pool(names, rng):
    return rng.choice(names)


# ---------------------------------------------------------------- simulatoare (contract identic cu bench)
def S_search_firms(city, sector, rng):
    doms = rng.sample(DOMS, 3)
    return {"query": f"{sector} {city}", "results": [
        {"title": f"{sector.title()} {city} - {d.split('.')[0]}", "url": f"https://{d}"} for d in doms]}


def S_fetch(url, rng):
    base = url.split("//")[-1].split("/")[0].split(".")[0]
    return {"url": url, "status": 200, "text": f"{base} | email: contact@{base}.ro | tel: 0364{rng.randint(100000,999999)}"}


def S_offers(cat, max_price, rng):
    offs = [{"id": f"H{i}", "name": f"Host {n}", "price_eur": rng.randint(15, 140)}
            for i, n in enumerate(["Mini", "Basic", "Plus", "Pro"], 1)]
    return {"category": cat, "offers": offs, "max_price": max_price}


def S_write(path, content):
    return {"ok": True, "path": path, "bytes": len(content)}


def S_read(path, rng, missing=False):
    if missing:
        return {"error": f"FileNotFoundError: {path} nu există în C:/Users/Pusu"}
    return {"path": path, "content": f"# {path}\n- obiectiv: {pool(SECTORS, rng)} {pool(CITIES, rng)}\n- status: în lucru"}


def S_email(to, subject, body, rng, fail=False):
    if fail:
        return {"error": pool(ERRS, rng)}
    return {"ok": True, "to": to, "subject": subject, "message_id": f"<{rng.randint(10**6,10**7)}@smtp>"}


def S_api(service, rng, fail=False):
    return {"error": pool(ERRS, rng)} if fail else {"ok": True, "service": service, "items": rng.randint(3, 40)}


def S_extract(url, selector, rng):
    if not selector or selector in ("//", "*", ""):
        return {"error": f"selector '{selector}' nu a returnat niciun nod"}
    return {"url": url, "matches": 1, "text": f"contact@{url.split('//')[-1].split('.')[0]}.ro"}


def S_mempalace(text):
    return {"ok": True, "saved": text[:60], "drawer": f"session-{RNG.randint(100,999)}"}


def S_gmail(q, rng):
    return {"query": q, "messages": [{"id": f"m{i}", "from": f"client{i}@{pool(DOMS, rng)}", "subject": f"Ofertă {i}"}
                                     for i in (1, 2)]}


def S_telegram(chat, text):
    return {"ok": True, "chat": chat, "chars": len(text)}


def S_cron(sched, task):
    return {"ok": True, "job_id": f"cron_{RNG.randint(1000,9999)}", "schedule": sched}


def S_kanban(title):
    return {"ok": True, "card": f"K{RNG.randint(10,99)}", "title": title}


def S_discord(channel, text):
    return {"error": "discord_send nu este configurat în această sesiune"}


# ---------------------------------------------------------------- tipare de task: (user, pasi, final)
def t_outreach(rng):
    city, sec = pool(CITIES, rng), pool(SECTORS, rng)
    q = {"city": city, "sector": sec}
    firms = S_search_firms(city, sec, rng)
    steps = [("web_search", {"query": f"{sec} {city} fără site"}, {"query": q, "results": firms["results"]})]
    for r in firms["results"]:
        steps.append(("web_fetch", {"url": r["url"]}, S_fetch(r["url"], rng)))
    md = "\n".join(f"- {r['title']}: {S_fetch(r['url'], rng)['text']}" for r in firms["results"])
    path = pool(FILES, rng)
    steps.append(("write_file", {"path": f"C:/Users/Pusu/{path}", "content": md}, S_write(path, md)))
    return (f"Găsește 3 firme de {sec} în {city} fără site web, ia-le datele de contact "
            f"și salvează totul în C:/Users/Pusu/{path}.", steps,
            f"Am salvat în {path} cele 3 firme din {city}: " + "; ".join(r["title"] for r in firms["results"]))


def t_email_retry(rng):
    path = pool(FILES, rng)
    to = f"contact@{pool(DOMS, rng)}"
    err = pool(ERRS, rng)
    steps = [("read_file", {"path": f"C:/Users/Pusu/{path}"}, S_read(path, rng)),
             ("send_email", {"to": to, "subject": "Ofertă site", "body": "<conținutul fișierului>"},
              {"error": err}),
             ("send_email", {"to": to, "subject": "Ofertă site", "body": "<conținutul fișierului>"},
              S_email(to, "Ofertă site", "<conținut>", rng))]
    return (f"Trimite oferta din {path} la {to}. Dacă apare o eroare de rețea, reîncearcă o singură dată.",
            steps, f"Email trimis la {to} din a doua încercare.")


def t_budget(rng):
    b = pool(BUDGETS, rng)
    cat = {"hosting": "hosting", "domeniu": "domeniu", "vps": "vps"}[rng.choice(["hosting", "domeniu", "vps"])]
    offers = S_offers(cat, b, rng)
    offers["offers"][0]["price_eur"] = max(5, b - rng.randint(1, 8))          # garantat in buget
    for o in offers["offers"][1:]:
        o["price_eur"] = b + rng.randint(1, 60)                              # garantat peste buget
    ink = [o for o in offers["offers"] if o["price_eur"] <= b]
    best = min(ink, key=lambda o: o["price_eur"])
    steps = [("search_offers", {"category": cat, "max_price": str(b)}, offers)]
    return (f"Am {b} EUR pe an pentru {cat}. Caută oferte și spune-mi exact care intră în buget.",
            steps, f"Singura ofertă în bugetul de {b} EUR este {best['id']} ({best['name']}, {best['price_eur']} EUR).")


def t_write_verify(rng):
    path = pool(FILES, rng)
    steps = [("read_file", {"path": f"C:/Users/Pusu/{path}"}, S_read(path, rng)),
             ("write_file", {"path": f"C:/Users/Pusu/{path}", "content": "# actualizat\n- status: gata"},
              S_write(path, "# actualizat\n- status: gata")),
             ("read_file", {"path": f"C:/Users/Pusu/{path}"}, {"path": path, "content": "# actualizat\n- status: gata"})]
    return (f"Adaugă în {path} linia «status: gata» și confirmă-mi că s-a scris.",
            steps, f"Scris și verificat: {path} conține acum «status: gata».")


def t_memory(rng):
    pref = rng.choice(["nu-mi place să fiu sunat dimineața înainte de ora 10",
                       "prefer ofertele pe email, nu pe telefon",
                       "lucrez pe proiecte scurte de maximum 2 săptămâni",
                       "nu accept întâlniri vinerea"])
    steps = [("mempalace_save", {"text": pref}, S_mempalace(pref))]
    return (f"Reține că {pref}.", steps, f"Am reținut: {pref}.")


def t_missing_file(rng):
    path = pool(FILES, rng) + ".bak"
    steps = [("read_file", {"path": f"C:/Users/Pusu/{path}"}, S_read(path, rng, missing=True))]
    return (f"Citește {path} și spune-mi ce conține.",
            steps, f"Fișierul {path} nu există (FileNotFoundError). Nu am ce citi — spune-mi de unde să iau datele.")


def t_contradiction(rng):
    path = pool(FILES, rng)
    return (f"Șterge fișierul {path}. Important: nu modifica și nu șterge nimic din el.",
            [], f"Cerința se contrazice: îmi ceri să șterg {path} și totodată să nu-l șterg. Nu am făcut nimic. Confirmă varianta corectă.")


def t_chain(rng):
    target = rng.choice(["@CipPusu", "AI Studio", "@tickt0ckusers"])
    steps = [("gmail_search", {"query": "ofertă site"}, S_gmail("ofertă site", rng)),
             ("send_telegram", {"chat": target, "text": "2 mesaje noi: client1, client2"}, S_telegram(target, "2 mesaje noi"))]
    return (f"Verifică emailurile cu «ofertă site» și trimite-mi pe Telegram la {target} câte sunt.",
            steps, f"Am trimis pe Telegram la {target}: 2 mesaje noi (client1@, client2@).")


def t_extract_retry(rng):
    d = pool(DOMS, rng)
    url = f"https://{d}"
    steps = [("browser_extract", {"url": url, "selector": "//"}, S_extract(url, "//", rng)),
             ("web_fetch", {"url": url}, S_fetch(url, rng))]
    return (f"Extrage emailul de pe {url} cu browser_extract.", steps,
            f"browser_extract a eșuat pe selector; am folosit web_fetch: contact@{d.split('.')[0]}.ro")


def t_distractor(rng):
    title = f"Site {pool(SECTORS, rng)} {pool(CITIES, rng)}"
    steps = [("kanban_create", {"title": title}, S_kanban(title)),
             ("discord_send", {"channel": "#general", "text": title}, S_discord("#general", title))]
    return (f"Creează un card Kanban «{title}» și anunță pe Discord în #general.",
            steps, f"Card Kanban creat: «{title}». Pe Discord nu s-a putut anunța (discord_send neconfigurat).")


def t_api_recovery(rng):
    svc = rng.choice(["crm", "facturare", "stocuri"])
    steps = [("http_request", {"service": svc}, S_api(svc, rng, fail=True)),
             ("http_request", {"service": svc}, S_api(svc, rng))]
    return (f"Preia lista din serviciul {svc} prin api_call", steps, f"Preluat din {svc} după a doua încercare.")


SHAPES = [t_outreach, t_email_retry, t_budget, t_write_verify, t_memory, t_missing_file, t_contradiction,
          t_chain, t_extract_retry, t_distractor, t_api_recovery]


# ---------------------------------------------------------------- constructie mesaje
def msgs_for(system, user, steps, final):
    m = [{"role": "system", "content": system}, {"role": "user", "content": user}]
    for i, (tool, args, res) in enumerate(steps):
        m.append({"role": "assistant", "content": "", "tool_calls": [
            {"id": f"call_{i+1}", "type": "function",
             "function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}}]})
        m.append({"role": "tool", "tool_call_id": f"call_{i+1}", "content": json.dumps(res, ensure_ascii=False)})
    if final is not None:
        m.append({"role": "assistant", "content": final})
    return m


def wrong_turn(kind, traj, i, surface, rng):
    """Actiunea GRESITA la pasul i, plus actiunea corecta (chosen)."""
    steps, final = traj
    tool, args, res = steps[i]
    if kind == "repeat_same_tool":
        return {"role": "assistant", "content": "", "tool_calls": [{"id": "call_bad", "type": "function",
                "function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}}]}, "a repetat identic"
    if kind == "skip_step":
        return {"role": "assistant", "content": final if final else "Gata.", "tool_calls": None}, "a sărit peste pasul de verificare"
    if kind == "invented_tool":
        ghost = pool(TOOL_GHOST, rng)
        return {"role": "assistant", "content": "", "tool_calls": [{"id": "call_bad", "type": "function",
                "function": {"name": ghost, "arguments": "{}"}}]}, f"a inventat unealta {ghost}"
    if kind == "wrong_tool":
        other = [s for s in surface if s != tool and s in ("web_search", "browser_extract", "search_offers")]
        nm = other[0] if other else "web_search"
        return {"role": "assistant", "content": "", "tool_calls": [{"id": "call_bad", "type": "function",
                "function": {"name": nm, "arguments": "{}"}}]}, f"a folosit {nm} în loc de {tool}"
    if kind == "premature_final":
        return {"role": "assistant", "content": "Am trimis emailul cu oferta." if final else "Gata.", "tool_calls": None}, "a răspuns înainte să primească rezultatul"
    if kind == "hallucinate_result":
        return {"role": "assistant", "content": "Firma are email office@exemplu.ro și telefon 0364123456.", "tool_calls": None}, "a inventat date care nu apar în rezultat"
    if kind == "loop_after_error":
        return {"role": "assistant", "content": "", "tool_calls": [{"id": "call_bad", "type": "function",
                "function": {"name": tool, "arguments": json.dumps(args, ensure_ascii=False)}}]}, "a reîncercat identic după eroare"
    return None, None


KINDS = ["repeat_same_tool", "skip_step", "invented_tool", "wrong_tool", "premature_final",
         "hallucinate_result", "loop_after_error"]


def main():
    (OUT / "sft_sintetic.jsonl").unlink(missing_ok=True)
    (OUT / "pref_sintetic.jsonl").unlink(missing_ok=True)
    small_tools = list(B.SPECIAL.values())
    big_tools = small_tools + list(B.FILLER.values())
    stat_shape, stat_kind, bad = {}, {}, []
    n_sft = n_pref = 0

    f_sft = (OUT / "sft_sintetic.jsonl").open("a", encoding="utf-8")
    f_pref = (OUT / "pref_sintetic.jsonl").open("a", encoding="utf-8")
    for k in range(N):
        shape = SHAPES[k % len(SHAPES)]
        rng = random.Random(RNG.randint(0, 10**9))
        user, steps, final = shape(rng)
        needed = {s[0] for s in steps}
        small_names = {t["function"]["name"] for t in small_tools}
        cond = "SMALL" if (k % 2 == 0 and needed <= small_names) else "BIG"
        system = B.SMALL_PROMPT if cond == "SMALL" else B.BIG_PROMPT
        tools = small_tools if cond == "SMALL" else big_tools
        surface = [t["function"]["name"] for t in tools]

        used = [s[0] for s in steps]
        for nm in used:
            if nm not in surface:
                bad.append((shape.__name__, nm))
        m = msgs_for(system, user, steps, final)
        f_sft.write(json.dumps({"task": shape.__name__, "cond": cond, "tools": tools, "messages": m},
                               ensure_ascii=False) + "\n")
        n_sft += 1
        stat_shape[shape.__name__] = stat_shape.get(shape.__name__, 0) + 1

        # perechi de preferinta la pasii cu risc (nu pe toti -> doar divergenta reala)
        if not steps:      # tipar fara tool-uri (cerinta contradictorie): contrastul e la primul raspuns
            for kind in ("premature_final", "hallucinate_result", "invented_tool"):
                wt, note = wrong_turn(kind, ([("read_file", {"path": "x"}, {})], final), 0, surface, rng)
                if wt is None:
                    continue
                rec = {"task": shape.__name__, "cond": cond, "tools": tools, "kind": kind, "nota": note,
                       "pas_gresit": 0, "messages": m[:2],
                       "chosen": {"role": "assistant", "content": final},
                       "rejected": wt}
                f_pref.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_pref += 1
                stat_kind[kind] = stat_kind.get(kind, 0) + 1
            continue
        cand = list(range(len(steps)))
        for i in rng.sample(cand, min(2, len(cand))):
            for kind in rng.sample(KINDS, 2):
                wt, note = wrong_turn(kind, (steps, final), i, surface, rng)
                if wt is None:
                    continue
                prefix = m[: 2 + 2 * i]
                step = steps[i]
                chosen = {"role": "assistant", "content": "", "tool_calls": [
                    {"id": "call_ok", "type": "function",
                     "function": {"name": step[0], "arguments": json.dumps(step[1], ensure_ascii=False)}}]}
                rec = {"task": shape.__name__, "cond": cond, "tools": tools, "kind": kind, "nota": note,
                       "pas_gresit": i, "messages": prefix, "chosen": chosen, "rejected": wt}
                f_pref.write(json.dumps(rec, ensure_ascii=False) + "\n")
                n_pref += 1
                stat_kind[kind] = stat_kind.get(kind, 0) + 1
    f_sft.close()
    f_pref.close()

    print(f"SFT sintetic    : {n_sft} traiectorii complete  -> {OUT/'sft_sintetic.jsonl'}")
    print(f"perechi preferinta: {n_pref} (corect vs gresit) -> {OUT/'pref_sintetic.jsonl'}")
    print(f"suprafete: {len(small_tools)} tool-uri (SMALL) / {len(big_tools)} (BIG)")
    print("distributie pe tipare:", json.dumps(stat_shape, ensure_ascii=False))
    print("distributie pe erori :", json.dumps(stat_kind, ensure_ascii=False))
    print("tool-uri in afara suprafetei:", bad or "niciunul")


if __name__ == "__main__":
    main()
