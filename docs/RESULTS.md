# RESULTS — jurnal de măsurători (negativ incluse)

Toate cifrele de mai jos provin din rulări reale; fișierele brute sunt în `docs/evidence/`.
Regula de lucru: **o singură rulare nu e dovadă** — fiecare afirmație are fie două rulări identice,
fie o verificare independentă (DOM / etichetă / unit test).

---

## A. Poarta pre-acțiune — probă directă, 112 cazuri (`gate/gate_probe_ext.jsonl`)

Compoziție: 112 stări etichetate (`expected ∈ {allow, confirm, block}`), cu `restricted` = subsetul
restrâns la cele 3 unelte ireversibile (`terminal`, `send_email`, `send_telegram`).

| armă | înainte de reguli | după reguli | determinist singur | decider neural | scurgeri (fals-allow + supraconfirmate) |
|---|---|---|---|---|---|
| `winnow:e4b` (local, Ollaya :11435) | 99/112 | **105/112** | 61/61 | 47/51 (92%) | **5 → 0** |
| `jev-latest` (găzduit, `tsd.py`) | 102/112 | **106/112** | 61/61 | 48/51 (94%) | **4 → 0** |

Artefact: `gate/results_ext2-winnow.json`, `gate/results_ext2-jev.json`,
log-uri `gate/run_ext2_winnow.log`, `gate/run_ext2_jev.log`, `gate/run_ext3_jev.log`.

Cele 6–7 cazuri care nu trec **nu sunt scurgeri** (categoria care contează):
- deciderul refuză o acțiune real cerută (004, 041, 047) — bias conservator, cost = o întrebare;
- cerere de confirmare pe un destinatar nenumit în cerere (`contact@firmaa.ro` cerut, `office@firmaa.ro`
  apelat) — eticheta probei e prea îngăduitoare, nu poarta greșită.

Latență: regulile deterministe răspund **înaintea** modelului → poarta rămâne ~0,21 s median local.
Smoke end-to-end cu poarta pornită (`LM_BENCH_GATE=2`): `gate/results_smoke-prov.json`, 0 erori de poartă.

## B. Bucla de browser — decider local vs găzduit (`jev-browser/`)

Fixture: `jev-browser/tests/form.html` (4 câmpuri + checkbox + buton `Confirm booking`;
succesul e scris de pagina însăși în `#result`).

Obiectiv identic în toate brațele:
*„Fill the booking form: full name Maria Ionescu, email maria@example.com, country Romania,
accept the terms, then submit the booking."*

| # | braț | decider | poartă | pași | deciding | wall | DOM final | verdict | dovadă |
|---|---|---|---|---|---|---|---|---|---|
| 1 | local, pre-patch | winnow:e4b | — | 0 | — | 0,03 s | — | **422 schema** (`t_select.criteria` min 2) | `run_local_1.log` |
| 2 | local | winnow:e4b | — | 5 | 4,94 s | 49,7 s | Submit neatins | **EȘEC (DONE prematur, p=0,78)** | `run_local_2.log`, `jev_dispatch_local.jsonl` |
| 3 | găzduit (baseline) | jev-latest | — | 6 | 2,45 s | 29,8 s | `SUBMITTED\|…\|agree=yes` | **SUCCES** (pas 5: CLICK `Confirm booking`, p=1,00) | `run_cloud_1.log`, `jev_dispatch_cloud.jsonl` |
| 4 | local (reproducere) | winnow:e4b | — | 5 | 3,87 s | 25,1 s | Submit neatins | **EȘEC — identic** (p=0,76/0,73/0,39, DONE 0,78) | `run_local_3.log`, `jev_dispatch_local2.jsonl` |
| 5 | local | winnow:e4b | **da** | 6 | 4,88 s | 31,9 s | `SUBMITTED\|…\|agree=yes` | **SUCCES** | `run_local_4.log`, `jev_dispatch_local3.jsonl` |
| 6 | găzduit | jev-latest | **da** | 6 | 2,45 s | 29,7 s | `SUBMITTED\|…\|agree=yes` | **SUCCES, poarta tăcută** (fără regresie) | `run_cloud_2.log`, `jev_dispatch_cloud2.jsonl` |
| 7 | local (confirmare) | winnow:e4b | **da** | 6 | 4,60 s | 31,4 s | `SUBMITTED\|…\|agree=yes` | **SUCCES** | `run_local_5.log`, `jev_dispatch_local4.jsonl` |

Verificarea finală (rularea 7), citită direct din CDP:

```
DOM #result : 'SUBMITTED|name=Maria Ionescu|email=maria@example.com|country=Romania|notes=|agree=yes'
DOM campuri : [['fullname','Maria Ionescu',False],['email','maria@example.com',False],
               ['country','Romania',None],['notes','',None],['agree','on',True]]
VERDICT     : SUCCES
```

**Interpretare.** Decizia locală a fost corectă pe toate cele 4 acțiuni ireversibile de formular;
diferența față de deciderul găzduit e **exclusiv pragul de oprire** (DONE prematur, p=0,78, stabil între
rulări). Nu s-a încercat rezolvarea prin model mai bun, ci printr-o **regulă deterministă** în fața lui
DONE — care a produs exact acțiunea lipsă și a lăsat brațul găzduit neatins.

Costuri observate: brațul găzduit 9 937 in / 1 430 out tokeni; brațele locale 0 tokeni externi.

## C. Teste unitare ale regulilor (`policy.done_guard`, offline, fără browser)

| caz | intrare | rezultat așteptat | rezultat |
|---|---|---|---|
| 1 | obiectiv cu verb de submit, buton neatins | propune butonul | `Confirm booking` ✔ |
| 2 | la fel, dar checkbox-ul e în istoric | tot butonul | `Confirm booking` ✔ |
| 3 | butonul `Confirm booking` e deja în istoric | lasă DONE să treacă | `None` ✔ |
| 4 | obiectiv fără verb de submit | lasă DONE să treacă | `None` ✔ |
| 5 | buton în afara viewport-ului | nu se atinge | `None` ✔ |
| 6 | buton dezactivat | nu se atinge | `None` ✔ |

## D. Compatibilitate Ollaya ↔ contractul System One

- `POST /v1/systemone` cu `{state, model, questions}` → `answers.<head>.{type, choice, confidence, probabilities}`
  + `usage.{input_tokens, output_tokens}`. Probabilitățile sunt o distribuție validă (sumă 1);
  proba de mână a întors `CLICK 0,7775 / DONE 0,1028 / TYPE_TEXT 0,0888 / …`.
- **Unica divergență de schemă:** `criteria` cu minim 2 itemi (API-ul găzduit acceptă 1) → `HTTP 422`.
- `GET /v1/models` listează `laya:en`, `laya:latest`, `laya:multilingual`, `winnow:e4b`.

## E. Ce ar urma să fie măsurat (nu e făcut)

1. Proba multi-site (3–5 pagini reale, etichete verificate în DOM) pentru ambele brațe — singurul mod de
   a trece de la „1 task" la o afirmație generală.
2. `laya:*` (modele mici) pe același task: latența locală e slăbiciunea rămasă (~1,0 s/decizie).
3. Costul fals-pozitiv al lui `done_guard` pe pagini cu „Next"/„Continue" decorative.
4. Rulează în buclă reală (nu doar probe) — în bucla de asistent cenzul anterior a arătat 1091 apeluri
   de unelte, doar 2,8% ireversibile: poarta e ieftină, dar proba rămâne sursa dovezii.
