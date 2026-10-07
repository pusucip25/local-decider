"""Reguli deterministe de PROVENIENTA a tintei, pentru poarta pre-actiune.

De ce exista: masurat 2026-10-06 pe 112 cazuri etichetate manual (gate_probe_ext.jsonl), deciderii
neurali (Jev cloud 65/75, winnow:e4b local 62/75) scurg exact aceeasi clasa de actiuni ireversibile
necerute: `send_telegram` si emailul catre o lista de destinatari. Intrebarea "a cerut utilizatorul
asta?" are insa un raspuns VERIFICABIL cand tinta actiunii poate fi comparata textual cu cererea.
Puse inaintea deciderului neural, aceste reguli duc scurgerile 5/4 -> 0 cu zero cereri refuzate in plus:
toate cele 5 emisiuni de telegram necerute au fost prinse, iar 4 cereri reale care inainte erau
refuzate de decider (inclusiv "anunta-ma pe telegram") au devenit allow corect.

Nu e o regula de siguranta generala: e specifica celor doua unelte unde tinta nu poate fi dedusa din
cerere. `terminal` NU trece pe aici -- acolo deciderul neural nu a scurs niciodata nimic in 112 cazuri.
"""
import json
import re

# Cuvinte care arata ca cererea desemneaza un SET de destinatari ("trimite la toti clientii"),
# nu o adresa anume: atunci tinta e ceruta, doar ca nu e scrisa literal.
SET_WORDS = re.compile(
    r"to[țt]i|tuturor|toate|list[ăa]|grup|echipa|abona[țt]i|clien[țt]i|firme|magazine|cele \d+|\d+ (firme|persoane|adrese|magazine)",
    re.I)
# Tinta implicita a utilizatorului: "trimite-mi", "pe emailul meu", "anunta-ma".
SELF_WORDS = re.compile(
    r"emailul meu|pe emailul meu|la mine|c[ăa]tre mine|trimite-mi|trimite-?mi|notific[ăa]-m[ăa]|"
    r"anun[țt][ăa]-m[ăa]|spune-mi pe|pe telegram|pe whatsapp",
    re.I)
TELEGRAM = ("send_telegram", "send_whatsapp", "telegram_send")


def args_of(text):
    """Din 'send_email({"to": "a@b.ro"})' scoate ('send_email', {...})."""
    m = re.match(r"\s*([a-z_]+)\s*\((.*)\)\s*$", text or "", re.S)
    if not m:
        return "", {}
    name, raw = m.group(1), m.group(2)
    for attempt in (raw, raw.replace("'", '"')):
        try:
            a = json.loads(attempt)
            return name, (a if isinstance(a, dict) else {})
        except Exception:
            continue
    return name, {}


def _recipients(args):
    to = args.get("to") or args.get("recipient") or args.get("to_email") or []
    return [str(x) for x in (to if isinstance(to, list) else [to]) if x]


def proven_conflict(name, args, request):
    """Return motivul (str) daca actiunea ireversibila are o tinta neverificabila in cerere, altfel None.

    name    -- numele uneltei propuse
    args    -- argumentele ei (dict)
    request -- cererea utilizatorului, text
    """
    req = (request or "").lower()
    if not req:
        return None
    if name in TELEGRAM:
        # Chat id-ul si continutul unui mesaj nu pot fi verificate fata de o cerere scurta: daca
        # cererea nu spune macar "telegram", emisia nu a fost ceruta prin acest canal.
        if ("telegram" not in req and "whatsapp" not in req
                and not re.search(r"grup|canal|list[ăa]|to[țt]i|tuturor", request, re.I)):
            return "emisiune pe %s, dar cererea nu mentioneaza canalul" % name
        return None
    if name in ("send_email", "gmail_send", "send_mail"):
        tos = _recipients(args)
        if not tos:
            return None
        named = any(t.lower() in req or t.split("@")[0][:6].lower() in req for t in tos)
        if named or SET_WORDS.search(request) or SELF_WORDS.search(request):
            return None
        return "email catre %s, dar destinatarul nu apare in cerere" % (tos[0] if len(tos) == 1 else "%d destinatari" % len(tos))
    return None


# --- eecul care conteaza TSINTA, nu argumentele intregi -------------------------------------------
# Intr-un "SMTP 550 mailbox unavailable" sau "chat not found" cauza e DESTINATARUL, nu subiectul:
# reincercarea aceleiasi tinte cu alt text e tot o repetare fara progres. Regula pe argumente intregi
# (same_args) rateaza exact acest caz -- masurat 2026-10-06, cazurile 082/084 pe proba de 112.
TARGET_KEYS = {"send_email": ("to", "to_email", "recipient", "destinatar"),
               "send_mail": ("to",),
               "gmail_send": ("to", "to_email", "recipient"),
               "send_telegram": ("chat_id", "chat", "target"),
               "send_whatsapp": ("chat_id", "to", "target"),
               "terminal": ("command",)}
ERR_WORDS = re.compile(r"error|failed|eroare|esec|e\u0219ec|refus|denied|unavailable|not found|\b(4\d\d|550)\b", re.I)


def target_of(name, args):
    """Identitatea tintei unei actiuni ireversibile (destinatar / chat / comanda)."""
    for k in TARGET_KEYS.get(name, ()):
        v = (args or {}).get(k)
        if v not in (None, "", [], {}):
            return json.dumps(v, sort_keys=True, ensure_ascii=False) if not isinstance(v, str) else v
    return None


def target_failed_before(name, args, rezultate):
    """Motiv (str) daca aceeasi TSINTA a esuat deja intr-un apel anterior, altfel None."""
    if name not in TARGET_KEYS or not rezultate:
        return None
    tgt = target_of(name, args)
    if tgt is None:
        return None
    for line in rezultate:
        line = str(line)
        if "->" not in line or not ERR_WORDS.search(line):
            continue
        n2, a2 = args_of(line.split("->")[0])
        if n2 == name and target_of(name, a2) == tgt:
            return "aceeasi tinta (%s) a esuat deja: %s" % (tgt[:60], line.split("->")[-1].strip()[:60])
    return None


# --- autorizare explicita -------------------------------------------------------------------------
# "Am zis da", "aprob", "dă-i drumul" = cererea insasi e autorizarea: poarta nu mai intreaba nimic.
# Masurat: declanseaza exact pe cele 3 cazuri de tip "autorizat explicit" si pe NICIUN caz etichetat
# confirm/block (0 risc). Orice negatie in cerere ("nu", "nici", "fara sa") dezactiveaza regula,
# ca sa nu transformam "nu aprob trimiterea" in permisiune.
AUTH = re.compile(r"aprob|am zis da|d[ăa]-i drumul|d[ăa],?\s*(trimite|instaleaz|ruleaz|public)|"
                  r"confirm c[ăa]|e ok s[ăa]|po[țt]i s[ăa] (instalezi|trimiti)|^da\b|,\s*da\b", re.I)
NEG_ANY = re.compile(r"\bnu\b|\bnici\b|f[ăa]r[ăa] s[ăa]", re.I)


def explicit_authorization(request):
    """True daca cererea insasi autorizeaza explicit actiunea (fara negatie in ea)."""
    return bool(request) and bool(AUTH.search(request)) and not NEG_ANY.search(request)
