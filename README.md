# local-decider

**A browser agent whose *decision model* — the part that picks the next action — runs entirely on a
local GPU, behind the same HTTP contract as the hosted one. Plus one hard rule:
anything that can be decided by a rule is decided by a rule, not by weights.**

Measured on a labelled 112-case safety probe and on a live CDP browser loop, with the final state
verified **in the DOM, not in the agent's own report**.

> A false `allow` is an incident; a false `confirm` is a question.
> **The gate is judged by leaks, not by accuracy.**

*Română: [README.ro.md](README.ro.md).*

---

## 1. What is in this repo

| directory | what it is | state (7 Oct 2026) |
|---|---|---|
| `gate/` | the pre-action gate `allow / confirm / block` for a tool-using agent: deterministic rules + a neural decider, 112 labelled cases | shipped, measured, **0 leaks** |
| `jev-browser/` | the `jev-ultrafast` (browser-use) loop ported onto a minimal CDP client; the decider is swappable via `TYPESAFE_BASE_URL` | works end-to-end; the local decider is DOM-verified |
| `docs/RESULTS.md` | every number, negatives included, with the name of the evidence file | |
| `docs/evidence/` | raw run logs + mutation journals (dispatch JSONL) | |
| `docs/skill-snapshot/` | snapshot of the `typesafe-decisions` skill used to build this | |

Reference decider: **Ollaya** (`~/tools/ollaya`, daemon on `127.0.0.1:11435`, `POST /v1/systemone`),
models `winnow:e4b` / `laya:*`, RTX 3060 12 GB, `precision=Q8_0`.

## 2. What was proven

### 2.1 The decider is swappable by configuration, not by code

`jevbrowser/policy.py` already read `TYPESAFE_BASE_URL` from the environment, so the swap is:

```bash
export TYPESAFE_BASE_URL=http://127.0.0.1:11435   # System One, in the house
export TYPESAFE_API_KEY=local                     # the local server ignores the header
export TYPESAFE_MODEL=winnow:e4b
./jev-browser doctor                              # -> typesafe api ok (model winnow:e4b, 94 in-tokens)
```

No client was rewritten: the contract (`{state, model, questions}` →
`answers.<head>.{choice, confidence, probabilities}`, probabilities summing to 1) is
**identical by construction**. The local server passed `doctor` on the first attempt.

### 2.2 The task result (`tests/form.html`, same goal, both arms with a local executor)

Goal: *"Fill the booking form: full name Maria Ionescu, email maria@example.com, country Romania,
accept the terms, then submit the booking."*

| arm | decider | DONE gate | steps | deciding | final DOM (`#result`) | verdict |
|---|---|---|---|---|---|---|
| A | `jev-latest` (hosted) | — | 6 | 2.45 s | `SUBMITTED\|…\|agree=yes` | **SUCCESS** |
| B | `winnow:e4b` (local) | — | 5 | 3.87 s / 4.94 s | — (Submit never touched) | **FAIL: premature DONE** |
| C | `winnow:e4b` (local) | **on** | 6 | 4.88 s / 4.60 s | `SUBMITTED\|…\|agree=yes` | **SUCCESS** |
| D | `jev-latest` (hosted) | **on** | 6 | 2.45 s | `SUBMITTED\|…\|agree=yes` | **SUCCESS** (gate silent) |

Arm B reproduced **identically twice** (same probabilities: 0.76 / 0.73 / 0.39 on the actions,
0.78 on DONE) — the failure is deterministic, not noise. All four local actions were correct; the
failure is exclusively the **early stop**: the model declares DONE before the requested submit.
Arm D proves the gate breaks nothing where the decider was already correct.

External cost of the local arms: **0 tokens, 0 bits leaving the house.**

### 2.3 The pre-action gate (`gate/`) — 112 labelled cases

Chain order (rules run **before** the neural decider):

1. whitelist of local reads/writes → `allow`
2. explicit authorization in the request ("approve", "go ahead" — disabled by any negation) → `allow`
3. the target already failed (compared **by target**: recipient / chat_id / command) → `block`
4. provenance conflict (irreversible tool whose target does not appear in the request) → `confirm`
5. non-irreversible tools → `allow`
6. only now the neural decider, which **may only escalate to `confirm`, never to `block`**

| arm | end-to-end | rules alone | neural decider | leaks |
|---|---|---|---|---|
| `winnow:e4b` local | **105/112** | 58/61 (95%) | 47/51 (92%) | **0** (was 5) |
| `jev-latest` hosted | **106/112** | 58/61 (95%) | 48/51 (94%) | **0** (was 4) |

> **Correction vs. earlier drafts of this README.** The deterministic arm used to print `61/61`.
> That was a formatting bug in `gate/gate_ext_run.py` (`det, det` in the summary `printf`, so the
> second number was always the first — 100% by construction, never measured). The true figure is
> **58/61**, and it was confirmed twice: with the repo's own harness after fixing the print, and
> with an independent harness that applies only the deterministic chain
> (`gate/verify_rules_only.py`). The three misses are all conservative over-confirms
> (`confirm` where the probe label is `allow`), and the leak count is unaffected: **0**.

Latency: the deterministic rules answer **before** the model, so the gate stays at ~0.21 s median
(local) / ~0.54 s (hosted). The 6–7 remaining cases **are not leaks**: either the decider refuses an
action that was genuinely requested (conservative bias, cost = one question), or it asks for
confirmation on a recipient that is never named in the request.

### 2.4 Second swap: Hammer 2.1 7B through a System One shim — 2/2 success

Hammer 2.1 7B does not speak the System One contract, so it was placed behind it:
`jev-browser/scripts/hammer_systemone.py` translates one System One request into one Ollama chat
request and maps the answer back to `answers.<head>.{choice,confidence,probabilities}`.
`policy.py` — untouched.

| arm | decider | steps | deciding | final DOM | verdict |
|---|---|---|---|---|---|
| E | `hammer-bm:latest` | 6 | 16.93 s | `SUBMITTED\|…\|agree=yes` | **SUCCESS** |
| F | `hammer-bm:latest` (repeat) | 6 | 17.97 s | `SUBMITTED\|…\|agree=yes` | **SUCCESS** |

The correct sequence from the first try (name → email → country → checkbox → Confirm booking → DONE),
twice. **Cost:** ~3.5–4× slower per decision than `winnow:e4b` (16.9–18.0 s vs 4.6–4.9 s across 6
steps). As a **text helper** Hammer beats the incumbent: 4/4 on the four fields, including a correct
`null` on "Notes", where `llama3:8b` invented a value. Details in `docs/RESULTS.md` §F.

## 3. Where the local decider diverged from the hosted one (and how it was fixed)

1. **Stricter schema on single-candidate heads.** Ollaya requires `criteria` with at least 2 items;
   the hosted API accepts 1 → `HTTP 422 … T_SELECT.CHOICE.CRITERIA … min_length 2`.
   Fixed **deterministically**: a head with a single candidate needs no decision, so it is resolved
   locally without asking the model (`build_questions` → `fixed`). Fewer questions, same answer.
2. **Premature DONE on the local decider.** Fixed with `done_guard()`: if the goal asks for a
   submit/confirm/save/send action and a visible, enabled, **untouched** control exists, then DONE is
   not accepted — that control is executed instead. DONE is a claim, not evidence.

Both are fixes in `policy.py` (pre-patch backup: `jevbrowser/policy.py.orig`, sha256
`1b252b51…443f1`). The public signature of `decide()` is unchanged.

## 4. How to reproduce

### The gate (112 cases)

```bash
cd gate
GB_MODE=local GB_MODEL=winnow:e4b GB_TAG=ext2-winnow python gate_ext_run.py   # -> 105/112, 0 leaks
GB_MODE=cloud GB_TAG=ext2-jev python gate_ext_run.py                          # -> 106/112, 0 leaks

# deterministic chain only, no model required:
python3 verify_rules_only.py .                                                # -> 58/61, 0 leaks
```

### The browser loop with a local decider

The project was originally developed on Windows. The paths are now portable; on Linux:

```bash
# 1. Chrome with CDP on a dedicated profile (never your real one)
chromium --remote-debugging-port=9222 --user-data-dir="$PWD/.chrome-jev" about:blank &

# 2. the local decider daemon (Ollaya -> 127.0.0.1:11435), or a shim in front of any
#    OpenAI-compatible chat model:
python3 jev-browser/scripts/hammer_systemone.py --model <your-model> --port 11888 &

# 3. the loop
cd jev-browser
export TYPESAFE_BASE_URL=http://127.0.0.1:11435 TYPESAFE_API_KEY=local TYPESAFE_MODEL=winnow:e4b
./jev-browser doctor
./jev-browser run --url "file://$PWD/tests/form.html" \
  --goal "Fill the booking form: full name Maria Ionescu, email maria@example.com, country Romania, accept the terms, then submit the booking." \
  --max-steps 14 -v

# 4. evidence: the real page state, not the agent's report
python3 scripts/state.py     # -> DOM #result : 'SUBMITTED|…'  VERDICT: SUCCESS
```

For the hosted arm: `unset TYPESAFE_BASE_URL TYPESAFE_API_KEY` and
`export TYPESAFE_MODEL=jev-latest` (the key lives in `~/.typesafe/key`, **not** in the repo).

**Setup notes for a fresh Linux machine**

- `pip install websocket-client` (the only runtime dependency; a project-local `.venv` is picked up
  automatically by the launcher).
- The launchers resolve their own directory, so the repo can live anywhere.

## 5. What is NOT proven (limits)

- **One page, one goal.** `tests/form.html` is a fixture. There is no multi-site probe with
  DOM-verified labels yet.
- **`done_guard` is a heuristic**, calibrated on English/Romanian submit verbs; a page with a
  decorative, untouched "Next" can make it insist. It has not been measured on real pages.
- **The local decider is ~2.4× slower per decision** (≈1.0 s vs 0.41 s) on `winnow:e4b` Q8 on a
  3060. `laya:*` (much smaller) has not been tested on the same task.
- **The cloud arm really consumed tokens** (9,937 in / 1,430 out per run) — the local swap removes that.
- **The neural gate is not allowed to block:** `block` stays exclusively deterministic.
- **The decision quality tracks the decider.** Dropping in a small general chat model (tested:
  `gemma2:2b` through the shim, on Linux) keeps the whole pipeline running — CDP, the System One
  contract, the element table, the guards and the dispatch log all behave — but the loop stalls,
  repeatedly choosing `CLICK` on a textbox instead of `TYPE_TEXT`. That is a model-capability limit,
  not an architecture one, and it is exactly what the shim is designed to expose as a score.

## 6. Why it matters

The open half of this ecosystem is **the client**, never the judge: `jev-ultrafast` is MIT, but its
decider is cloud-only and in early access. Here the loop runs with the judge **in the house** — same
contract, zero marginal cost, zero data leaving the network — and the behavioural difference (which
is *opposite* on DONE) is closed with **rules**, not with a bigger model.

---

## License

MIT. Built by [Pusu](https://github.com/pusucip25).
