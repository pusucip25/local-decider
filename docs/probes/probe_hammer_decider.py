"""Probe the decider slot in isolation: Hammer behind the System One contract, real client path.

Uses jevbrowser/policy.py itself (not a hand-rolled request), so it exercises build_questions,
the HTTP call, and the answer parsing exactly as the loop does - if this is wrong, it is the
adapter, not the model.
"""
import json
import os
import sys

os.environ["TYPESAFE_BASE_URL"] = "http://127.0.0.1:11888"
os.environ["TYPESAFE_API_KEY"] = "local"
os.environ["TYPESAFE_MODEL"] = "hammer-bm"
sys.path.insert(0, "C:/Users/Pusu/tools/jev-browser")

from jevbrowser import policy  # noqa: E402

GOAL = ("Fill the booking form: full name Maria Ionescu, email maria@example.com, "
        "country Romania, accept the terms, then submit the booking.")

ELEMS = [
    {"i": 0, "role": "textbox", "name": "Full name", "tag": "input", "value": "", "inView": True},
    {"i": 1, "role": "textbox", "name": "Email", "tag": "input", "value": "", "inView": True},
    {"i": 2, "role": "combobox", "name": "Country", "tag": "select", "value": "", "inView": True,
     "options": ["Romania", "France", "Germany"]},
    {"i": 3, "role": "textbox", "name": "Notes", "tag": "textarea", "value": "", "inView": True},
    {"i": 4, "role": "checkbox", "name": "I accept the terms and conditions", "tag": "input",
     "value": "", "inView": True},
    {"i": 5, "role": "button", "name": "Confirm booking", "tag": "button", "value": "", "inView": True},
]

SNAP = {
    "url": "file:///C:/Users/Pusu/tools/jev-browser/tests/form.html",
    "title": "Booking",
    "viewport": {"w": 1280, "h": 800},
    "text": ("Booking form. Full name. Email. Country: Romania / France / Germany. Notes. "
             "I accept the terms and conditions. Confirm booking"),
    "elements": [dict(e, disabled=False) for e in ELEMS],
}

# what the page looks like at four points in the run; the right answer is in brackets
CASES = [
    ("nothing done yet", [], "TYPE_TEXT 0 or 1"),
    ("name + email typed", [
        {"op": "TYPE_TEXT", "element": "textbox · Full name", "value": "Maria Ionescu"},
        {"op": "TYPE_TEXT", "element": "textbox · Email", "value": "maria@example.com"},
    ], "SELECT 2 (country) or TYPE_TEXT 3"),
    ("country + terms done", [
        {"op": "TYPE_TEXT", "element": "textbox · Full name", "value": "Maria Ionescu"},
        {"op": "TYPE_TEXT", "element": "textbox · Email", "value": "maria@example.com"},
        {"op": "SELECT", "element": "combobox · Country", "value": "Romania"},
        {"op": "CLICK", "element": "checkbox · I accept the terms and conditions"},
    ], "CLICK 5 -> Submit"),
    ("everything done (DONE is correct here)", [
        {"op": "TYPE_TEXT", "element": "textbox · Full name", "value": "Maria Ionescu"},
        {"op": "TYPE_TEXT", "element": "textbox · Email", "value": "maria@example.com"},
        {"op": "SELECT", "element": "combobox · Country", "value": "Romania"},
        {"op": "CLICK", "element": "checkbox · I accept the terms and conditions"},
        {"op": "CLICK", "element": "button · Confirm booking"},
    ], "DONE"),
]

for label, hist, expect in CASES:
    r = policy.decide(GOAL, SNAP, hist)
    tgt = (r["target_element"] or {}).get("name")
    print(f"[{label}]")
    print(f"   op={r['op']:<10} target={r['target']} ({tgt})  conf={r['op_confidence']:.2f} "
          f"lat={r['latency_s']}s guard={r['guard']}")
    print(f"   asked={r['questions_asked']} pre_resolved={r['pre_resolved']}  expected: {expect}")
    print(f"   probs={json.dumps(r['op_probabilities'], ensure_ascii=False)}")
