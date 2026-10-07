# jev-browser

Un strat propriu de browser-agent peste Chrome CDP: **observă → decide într-un
singur round-trip TypeSafe → execută**. LLM-ul mic scrie text doar când operația
este `TYPE_TEXT`.

Tehnica e împrumutată din `browser-use/jev-ultrafast` (MIT). Codul de acolo nu a
fost instalat — are 3 commit-uri și 0 mentenanță; a fost rescris aici peste
`chrome-remote-interface`-ul minimal din `cdp.py`.

## Cum se folosește

```bash
cd ~/tools/jev-browser

./jev-browser doctor        # starea mediului: websocket, CDP, cheie TypeSafe, model text
./jev-browser table --new-tab --url https://example.com   # doar tabelul de elemente
./jev-browser run --url https://example.com --goal "..."  # bucla completă
```

Opțiuni utile la `run`:

| Flag | Efect |
|---|---|
| `--goal "..."` | scopul în limbaj natural (obligatoriu) |
| `--url ...` | navighează înainte de a începe |
| `--new-tab` | deschide un tab nou în loc să folosească tabul activ |
| `--max-steps N` | plafon de pași (implicit 12) |
| `-v` | afișează probabilități, heads de țintă, timpi |
| `--dispatch-log PATH` | jurnal append-only (JSONL) al mutațiilor **emise**, nu al rezultatelor (implicit `~/.cache/jev-browser/dispatch.jsonl`; `none` dezactivează) |
| `--text-provider none\|lmstudio\|ollama\|deepseek` | forțează providerul de text |

## Bucla

```
step:
  observe   → tabel indexat de elemente (roles, nume, valori, opțiuni de select)
  decide    → O cerere TypeSafe întoarce: operația + un head de țintă per operație
  guard     → geometrie / vizibilitate / enabled / ocluzie recitite LIVE, imediat
              înainte de input; un element schimbat invalidează O decizie (re-decide
              o dată), nu rularea
  execute   → click/type/select/scroll pe coordonate reale, apoi așteaptă o
              schimbare semantică a paginii
```

Operații: `CLICK`, `TYPE_TEXT`, `SELECT`, `SCROLL_UP`, `SCROLL_DOWN`, `WAIT`,
`DONE`, `BLOCKED`. Doar operațiile suportate și elementele compatibile intră în
politică (action space dinamic).

## Cele patru idei luate din jev-ultrafast

1. **Un singur round-trip.** Întrebările de țintă sunt speculative: se cer toate
   heads într-o singură cerere, se folosește doar head-ul care corespunde
   operației alese. Două decizii, o singură călătorie de rețea.
2. **LLM mic doar pentru text.** TypeSafe nu inventează string-uri; la
   `TYPE_TEXT`/`SELECT` un model mic întoarce strict `{"text": "..."}`.
3. **Action space dinamic.** Fiecare observație produce un tabel nou; fiecare
   head de țintă conține doar elemente compatibile.
4. **Politica e mică.** ~2 KB de instrucțiuni (`policy.py`), fără scripturi
   specifice de site și fără string-uri de câmp pregate.

## Guard-uri (partea care nu era în original)

- `_live()` recitește geometria **înainte** de fiecare input, din harta vie de
  elemente, nu din snapshot-ul vechi.
- `_hittable()` verifică `elementFromPoint` — dacă ținta e acoperită de un
  banner/overlay, se face scroll o dată și se re-verifică; dacă tot e acoperită,
  rezultatul e `occluded`, nu un click în gol.
- **Un singur dispatch per click.** Re-click-ul poate anula un toggle (checkbox)
  sau trimite formularul de două ori.
- Freshness semantică: URL + scroll + starea elementelor (valoare, `checked`,
  `aria-checked`, dialoguri deschise), nu numărare de mutații DOM.
- Recuperare CDP: sesiunea căzută se re-atașează (`reattach`), iar dacă
  websocket-ul e mort se reface (`reconnect`); o sesiune pierdută nu omoară rularea.

## Provider de text

Ordinea la `auto`: LM Studio (`:1234`) → Ollama (`:11434`) → DeepSeek API.

**Modelele de reasoning sunt excluse intenționat** (`qwen3*`, `deepseek-r1*`,
`*-think`): ard tot bugetul de tokens pe `thinking` și întorc `content` gol, deci
sunt inutilizabile pentru o valoare de câmp. La Ollama se alege automat un model
non-thinking (ex. `llama3:8b`), se trimite `think: false` și `keep_alive: 30m`,
iar modelul se încarcă în memorie la rezolvare (`_warm`) ca primul pas real să nu
plătească timpul de load.

Variabile: `JEV_TEXT_PROVIDER`, `JEV_TEXT_MODEL`, `JEV_TEXT_BASE_URL`,
`JEV_DECIDE_MODEL` (modelul TypeSafe), `TYPESAFE_API_KEY`.

## Fișiere

| Fișier | Rol |
|---|---|
| `cdp.py` | client CDP minimal (websocket-client), sesiuni flattened, `reattach`/`reconnect` |
| `dom.py` | tabelul indexat de elemente + hărțile vii `__jevEls` / `__jevMeta` |
| `policy.py` | decizia TypeSafe într-un round-trip |
| `textmodel.py` | modelul mic de text (doar `TYPE_TEXT`/`SELECT`) |
| `agent.py` | bucla observe → decide → guard → execute |
| `cli.py` | `doctor` / `table` / `run` |

## Rezultat măsurat

Formular de rezervare controlat (`tests/form.html`), scop în limbaj natural,
4 câmpuri + submit:

```
=== DONE in 6 steps (9.81s wall, 2.43s deciding) ===
tokens: input 10696 / output 1562
dispatch log: C:\Users\Pusu\.cache\jev-browser\dispatch.jsonl
verificat în DOM: SUBMITTED|name=Maria Ionescu|email=maria@example.com|
                  country=Romania|agree=yes
```

2,43 s din 9,81 s reprezintă decizia (6 cereri TypeSafe ≈ 0,4 s fiecare); restul
sunt cele 3 apeluri llama3:8b și așteptările de stabilizare a paginii.

`deciding` e metrica stabilă (2,43 s înainte / **2,42 s** după adăugarea
jurnalului de dispatch); `wall` urmează încărcarea mașinii — o re-rulare a dat
12,24 s wall cu `deciding`, tokens și DOM identice.

Jurnalul de dispatch scrie o linie `phase: "dispatch"` **înainte** de fiecare
mutație și una `phase: "result"` după, cu fișierul deschis/scris/închis pe linie
(fără buffer de pierdut). Dacă procesul moare între cele două, jurnalul arată că
pagina s-a putut schimba — ce `history` nu poate face, pentru că `history` e
context trimis modelului.

## Limite cunoscute

- Necesită Chrome pornit cu `--remote-debugging-port=9222`.
- Coordonatele sunt în pixeli CSS ai viewport-ului; la zoom de pagină != 100%
  guard-ul de ocluzie poate raporta `occluded` (nu produce click greșit).
- `SELECT` nativ funcționează pe `<select>`; combobox-urile custom (ARIA) se
  tratează ca `CLICK` + listă de opțiuni.
- `WAIT` nu are încă implementare specială (se comportă ca un pas fără acțiune).
