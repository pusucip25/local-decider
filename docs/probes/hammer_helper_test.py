"""Hammer in the TEXT-HELPER slot of jev-browser.

Role split in the loop:
  decider  = System One policy (winnow:e4b local / jev-latest cloud) -> picks op + target
  helper   = small local LLM, ONLY for op=TYPE_TEXT -> must return strict JSON {"text": "..."}
             (jevbrowser/textmodel.py, temp 0, max_tokens 48, one retry with the contract repeated)

This measures the helper slot: can Hammer follow that contract at all, vs the actor llama3:8b
that the loop currently picks by itself (LM Studio is down -> ollama -> pick_model -> llama3:8b).
"""
import json
import os
import re
import sys
import time

sys.path.insert(0, "C:/Users/Pusu/tools/jev-browser")
from jevbrowser.textmodel import TextModel  # noqa: E402

GOAL = ("Fill the booking form: full name Maria Ionescu, email maria@example.com, "
        "country Romania, accept the terms, then submit the booking.")

SNAP = {
    "url": "file:///C:/Users/Pusu/tools/jev-browser/tests/form.html",
    "text": ("Booking form. Full name. Email. Country -> Romania / France / Germany. Notes. "
             "I accept the terms and conditions. Confirm booking"),
}

ELEMENTS = [
    {"role": "textbox", "name": "Full name", "tag": "input", "value": "", "options": None},
    {"role": "textbox", "name": "Email", "tag": "input", "value": "", "options": None},
    {"role": "combobox", "name": "Country", "tag": "select", "value": "", "options": ["Romania", "France", "Germany"]},
    {"role": "textbox", "name": "Notes", "tag": "textarea", "value": "", "options": None},
]

EXPECTED = {"Full name": "Maria Ionescu", "Email": "maria@example.com", "Country": "Romania", "Notes": None}

MODELS = ["hammer-bm:latest", "hf.co/eaddario/Hammer2.1-7b-GGUF:Q4_K_M", "llama3:8b", "qwen35-bm:latest"]

os.environ["JEV_TEXT_PROVIDER"] = "ollama"


def raw_chat(model: str, msgs: list, max_tokens: int = 48, timeout: float = 180.0):
    """Same call textmodel._chat makes, but returns the raw content so we can see the failure mode."""
    import urllib.request
    payload = {"model": model, "messages": msgs, "temperature": 0, "max_tokens": max_tokens,
               "stream": False, "keep_alive": "30m", "think": False}
    req = urllib.request.Request("http://127.0.0.1:11434/v1/chat/completions",
                                 data=json.dumps(payload).encode("utf-8"), method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        resp = json.loads(r.read().decode("utf-8"))
    return resp["choices"][0]["message"].get("content") or ""


summary = []
for model in MODELS:
    tm = TextModel(provider="ollama", model=model)
    print(f"\n===== {model}   [{tm.status()}] =====")
    ok = 0
    for el in ELEMENTS:
        t0 = time.time()
        try:
            txt, how = tm.write(GOAL, el, SNAP, [])
        except Exception as e:  # noqa: BLE001
            txt, how = None, f"EXC {e}"
        dt = time.time() - t0
        exp = EXPECTED[el["name"]]
        if exp is None:
            good = txt is None or (txt or "").strip() not in (el["options"] or [])
        else:
            good = (txt or "").strip() == exp
        ok += good
        print(f"  [{'OK ' if good else 'BAD'}] {el['name']:11s} -> {txt!r:38s} ({how}, {dt:4.1f}s)  expected {exp!r}")
    # one raw peek: what does it actually emit?
    try:
        from jevbrowser.textmodel import TEXT_VALUE_PROMPT
        state = {"goal": GOAL, "field": {"role": "textbox", "name": "Full name", "tag": "input",
                 "current_value": ""}, "url": SNAP["url"], "page_text": SNAP["text"], "history": []}
        raw = raw_chat(model, [{"role": "system", "content": TEXT_VALUE_PROMPT},
                               {"role": "user", "content": json.dumps(state)}])
        print(f"  raw: {raw[:200]!r}")
    except Exception as e:  # noqa: BLE001
        print(f"  raw FAILED: {e}")
    summary.append((model, ok, len(ELEMENTS)))

print("\n===== SCOR (helper slot) =====")
for m, ok, n in summary:
    print(f"  {m:42s} {ok}/{n}")
