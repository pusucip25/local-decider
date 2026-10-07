# local-decider

**EN:** a browser agent whose *decision model* (the part that picks the next action) runs entirely on a
local GPU behind the same HTTP contract as the hosted one — plus a hard rule: **anything that can be
decided by a rule is decided by a rule, not by weights.** Measured on a labelled 112-case safety probe
and on a live CDP browser loop, with the final state verified in the DOM, not in the agent's own report.

**RO, teza:** decizia poate rula în casă — gratis, fără ca starea personală să plece la un API extern.
Iar ce e determinist se decide determinist: **modelul propune, regula dispune.**
Un fals-`allow` e un incident; un fals-`confirm` e o întrebare. Poarta se judecă după **scurgeri**, nu după acuratețe.

---

## 1. Ce e în repo

| director | ce este | stare (7 oct 2026) |
|---|---|---|
| `gate/` | poarta pre-acțiune `allow / confirm / block` pentru agentul de unelte: reguli deterministe + decider neural, 112 cazuri etichetate | livrată, măsurată, **scurgeri 0** |
| `jev-browser/` | bucla `jev-ultrafast` (browser-use) portată peste CDP minimal, decider comutabil prin `TYPESAFE_BASE_URL` | funcțională end-to-end; decider local verificat în DOM |
| `docs/RESULTS.md` | toate cifrele, negativele incluse, cu numele fișierelor de dovadă | |
| `docs/evidence/` | log-uri brute ale rulărilor + jurnale de mutație (dispatch JSONL) | |
| `docs/skill-snapshot/` | snapshot al skill-ului `typesafe-decisions` folosit la construcție | |

Antetul deciderului: **Ollaya** (`~/tools/ollaya`, daemon `127.0.0.1:11435`, `POST /v1/systemone`),
modele `winnow:e4b` / `laya:*`, GPU RTX 3060 12 GB, `precision=Q8_0`.

## 2. Ce s-a dovedit

### 2.1 Deciderul e comutabil prin configurare, nu prin cod

`jevbrowser/policy.py` citea deja `TYPESAFE_BASE_URL` din mediu. Deci swap-ul e:

```bash
export TYPESAFE_BASE_URL=http://127.0.0.1:11435   # System One local, în casă
export TYPESAFE_API_KEY=local                     # serverul local ignoră antetul
export TYPESAFE_MODEL=winnow:e4b
./jev-browser doctor                              # -> typesafe api ok (model winnow:e4b, 94 in-tokens)
```

Niciun client nu a fost rescris: contractul (`{state, model, questions}` →
`answers.<head>.{choice, confidence, probabilities}`, probabilități cu sumă 1) e **identic prin construcție**.
Serverul local a trecut `doctor` din prima încercare.

### 2.2 Rezultatul pe task (`tests/form.html`, același obiectiv, ambele brațe cu executor local)

Obiectiv: *„Fill the booking form: full name Maria Ionescu, email maria@example.com, country Romania,
accept the terms, then submit the booking."*

| braț | decider | poartă DONE | pași | deciding | DOM final (`#result`) | verdict |
|---|---|---|---|---|---|---|
| A | `jev-latest` (găzduit) | — | 6 | 2,45 s | `SUBMITTED\|…\|agree=yes` | **SUCCES** |
| B | `winnow:e4b` (local) | — | 5 | 3,87 s / 4,94 s | — (Submit neatins) | **EȘEC: DONE prematur** |
| C | `winnow:e4b` (local) | **da** | 6 | 4,88 s / 4,60 s | `SUBMITTED\|…\|agree=yes` | **SUCCES** |
| D | `jev-latest` (găzduit) | **da** | 6 | 2,45 s | `SUBMITTED\|…\|agree=yes` | **SUCCES** (poarta tăcută) |

Brațul B a fost reprodus **identic de două ori** (aceleași probabilități: 0,76 / 0,73 / 0,39 la acțiuni,
0,78 la DONE) → eșecul e determinist, nu zgomot. Toate cele 4 acțiuni locale au fost corecte;
eșecul e exclusiv **oprirea prematură**: modelul declară DONE înainte de submiterea cerută.
Brațul D dovedește că poarta nu strică nimic unde deciderul era deja corect.

Costul extern al brațelor locale: **0 tokeni, 0 biți în afara casei.**

### 2.3 Poarta pre-acțiune (`gate/`) — 112 cazuri etichetate

Ordine în lanț (reguli **înaintea** deciderului neural):

1. whitelist citiri/operații locale → `allow`
2. autorizare explicită în cerere („aprob", „dă-i drumul" — dezactivată de orice negație) → `allow`
3. ținta a eșuat deja (comparare pe **țintă**: destinatar / chat_id / comandă) → `block`
4. conflict de proveniență (unealtă ireversibilă a cărei țintă nu apare în cerere) → `confirm`
5. ne-ireversibile → `allow`
6. abia acum deciderul neural, care **poate doar escalada la `confirm`, niciodată `block`**

| armă | pipeline | determinist singur | decider neural | scurgeri |
|---|---|---|---|---|
| `winnow:e4b` local | **105/112** | 61/61 | 47/51 (92%) | **0** (era 5) |
| `jev-latest` găzduit | **106/112** | 61/61 | 48/51 (94%) | **0** (era 4) |

Latență: regulile răspund înaintea modelului, deci latența porții rămâne ~0,21 s median (local) /
~0,54 s (cloud). Cele 6–7 cazuri rămase **nu sunt scurgeri**: fie deciderul refuză o acțiune real
cerută (bias conservator), fie cere confirmare pe un destinatar nenumit în cerere.

## 3. Ce a divergat față de deciderul găzduit (și cum s-a rezolvat)

1. **Schemă mai strictă la head-urile cu un singur candidat.** Ollaya cere `criteria` cu minim 2 itemi;
   API-ul găzduit acceptă 1 → `HTTP 422 … T_SELECT.CHOICE.CRITERIA … min_length 2`.
   Rezolvat **determinist**: un head cu un singur candidat nu are nevoie de decizie, deci se rezolvă
   local, fără să fie întrebat modelul (`build_questions` → `fixed`). Mai puține întrebări, același răspuns.
2. **DONE prematur la deciderul local.** Rezolvat cu `done_guard()`: dacă obiectivul cere o acțiune de
   tip submit/confirm/save/send și există un control vizibil, activ, **neatins**, atunci DONE nu se
   acceptă — se execută acel control. DONE e o afirmație, nu o dovadă.

Ambele sunt fix-uri în `policy.py` (backup-ul pre-patch: `jevbrowser/policy.py.orig`, sha256
`1b252b51…443f1`). Semnătura publică a lui `decide()` a rămas neschimbată.

## 4. Cum se reproduce

**Poarta (112 cazuri):**

```bash
cd gate
GB_MODE=local GB_MODEL=winnow:e4b GB_TAG=ext2-winnow python gate_ext_run.py   # -> 105/112, scurgeri 0
GB_MODE=cloud GB_TAG=ext2-jev python gate_ext_run.py                          # -> 106/112, scurgeri 0
```

**Bucla de browser cu decider local:**

```bash
# 1. Chrome cu CDP (profil dedicat, ca să nu se atingă profilul real)
"C:/Program Files/Google/Chrome/Application/chrome.exe" \
  --remote-debugging-port=9222 --user-data-dir=C:/Users/Pusu/.chrome-jev about:blank

# 2. daemonul deciderului local
#    ~/tools/ollaya  -> 127.0.0.1:11435

# 3. bucla
cd jev-browser
export TYPESAFE_BASE_URL=http://127.0.0.1:11435 TYPESAFE_API_KEY=local TYPESAFE_MODEL=winnow:e4b
./jev-browser run --url file:///C:/Users/Pusu/tools/jev-browser/tests/form.html \
  --goal "Fill the booking form: full name Maria Ionescu, email maria@example.com, \
country Romania, accept the terms, then submit the booking." --max-steps 14 -v

# 4. dovada: starea reală a paginii, nu raportul agentului
python3 scripts/state.py     # -> DOM #result : 'SUBMITTED|…'  VERDICT: SUCCES
```

Pentru brațul găzduit: `unset TYPESAFE_BASE_URL TYPESAFE_API_KEY` + `export TYPESAFE_MODEL=jev-latest`
(cheia stă în `~/.typesafe/key`, **nu** în repo).

## 5. Ce NU este dovedit (limite)

- **O singură pagină, un singur obiectiv.** `tests/form.html` e un fixture. Nu există încă o probă
  multi-site cu etichete verificate în DOM.
- **`done_guard` e euristic**, calibrat pe verbele de submit din engleză/română; o pagină cu „Next"
  decorativ, neatins, îl poate face să insiste. Nu a fost măsurat pe pagini reale.
- **Deciderul local e ~2,4× mai lent per decizie** (≈1,0 s vs 0,41 s) pe winnow:e4b Q8 pe 3060.
  Nu s-a testat `laya:*` (mult mai mic) pe același task.
- **Brațul cloud a consumat real** (9 937 in / 1 430 out tokeni pe rulare) — swap-ul local elimină asta.
- Poarta neurală **nu** are voie să blocheze: `block` rămâne exclusiv determinist.

## 6. De ce contează

Partea deschisă a ecosistemului e **clientul**, niciodată judecătorul: `jev-ultrafast` e MIT, dar
deciderul lui e cloud-only și în early access. Aici bucla funcționează cu judecătorul **în casă**:
același contract, zero cost marginal, zero date care ies din rețea, iar diferența de comportament
(opusă pe DONE) se închide cu **reguli**, nu cu un model mai mare.
