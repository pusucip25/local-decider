#!/usr/bin/env python3
"""jev-browser CLI: doctor | table | run."""
from __future__ import annotations

import argparse
import json
import sys
import time

from . import __version__
from .agent import JevBrowserAgent
from .cdp import CDP, CDPError, browser_ws_url, page_targets
from .dom import describe, snapshot
from .policy import DEFAULT_MODEL, decide, load_key
from .textmodel import TextModel


def _connect(args) -> CDP:
    return CDP(port=args.port, target_url_contains=args.match,
               new_tab=args.new_tab, url=args.url)


# --------------------------------------------------------------------- doctor
def cmd_doctor(args) -> int:
    ok = True
    print(f"jev-browser {__version__}  (python {sys.version.split()[0]})\n")

    try:
        from websocket import __version__ as wsv  # noqa: F401
        print(f"  websocket-client   ok ({wsv})")
    except Exception as e:
        print(f"  websocket-client   MISSING ({e})  ->  pip install websocket-client")
        ok = False

    try:
        url = browser_ws_url(args.port)
        print(f"  chrome cdp         ok  (port {args.port})")
    except Exception as e:
        print(f"  chrome cdp         DOWN ({e})")
        print("                     start Chrome with: --remote-debugging-port=%d" % args.port)
        ok = False
        url = None

    if url:
        try:
            pages = page_targets(args.port)
            print(f"  page targets       {len(pages)}")
            for p in pages[:4]:
                print(f"                     - {(p.get('title') or '')[:34]:<34} {p.get('url','')[:48]}")
        except Exception as e:
            print(f"  page targets       error ({e})")

    try:
        k = load_key()
        print(f"  typesafe key       ok  ({len(k)} chars)")
    except Exception as e:
        print(f"  typesafe key       MISSING ({e})")
        ok = False

    try:
        from .policy import call
        r = call("ping", {"p": {"type": "noul", "instructions": "Is this a health check?"}},
                 args.decide_model, timeout=30)
        print(f"  typesafe api       ok  (model {args.decide_model}, "
              f"{r.get('usage', {}).get('input_tokens', '?')} in-tokens)")
    except Exception as e:
        print(f"  typesafe api       FAIL ({e})")
        ok = False

    t = TextModel(provider=args.text_provider, model=args.text_model)
    st = t.status()
    print(f"  text helper        {st}")
    if st.startswith("none"):
        print("                     (TYPE_TEXT steps will be skipped; decisions still work)")

    if url:
        try:
            c = CDP(port=args.port)
            s = snapshot(c)
            print(f"  element table      ok  ({len(s['elements'])} elements on '{s['title'][:40]}')")
            c.close()
        except Exception as e:
            print(f"  element table      FAIL ({e})")
            ok = False

    print("\n  READY" if ok else "\n  NOT READY - fix the lines above")
    return 0 if ok else 1


# ---------------------------------------------------------------------- table
def cmd_table(args) -> int:
    with _connect(args) as c:
        c.wait_ready()
        s = snapshot(c, args.max_elements)
    if args.json:
        print(json.dumps(s, ensure_ascii=False, indent=2))
    else:
        print(f"{s['title'][:70]}\n{s['url']}\n"
              f"scrollY={s['scrollY']} viewport={s['viewport']} "
              f"elements={len(s['elements'])}\n")
        print(describe(s["elements"]))
        print(f"\n--- page text ({len(s['text'])} chars) ---\n{s['text'][:600]}")
    return 0


# -------------------------------------------------------------------- one step
def cmd_step(args) -> int:
    with _connect(args) as c:
        c.wait_ready()
        s = snapshot(c, args.max_elements)
        d = decide(args.goal, s, [], args.decide_model)
    out = {k: v for k, v in d.items() if k != "target_element"}
    if d.get("target_element"):
        out["target_element"] = {k: v for k, v in d["target_element"].items() if k != "box"}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


# ----------------------------------------------------------------------- run
def cmd_run(args) -> int:
    text = TextModel(provider=args.text_provider, model=args.text_model,
                     verbose=args.verbose)
    with _connect(args) as c:
        if args.url:
            c.navigate(args.url)
        else:
            c.wait_ready()
        agent = JevBrowserAgent(c, args.goal, max_steps=args.max_steps,
                                decide_model=args.decide_model, text=text,
                                verbose=args.verbose,
                                dispatch_log=getattr(args, "dispatch_log", None))
        t0 = time.time()
        res = agent.run()

    if args.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        print(f"\n=== {res['status'].upper()} in {res['steps']} steps "
              f"({res['wall_seconds']}s wall, {res['decide_seconds']}s deciding) ===")
        print(f"tokens: {res['usage']}")
        if res.get("dispatch_log"):
            print(f"dispatch log: {res['dispatch_log']}")
        print(f"landed: {res['final_title'][:60]}\n        {res['final_url'][:100]}")
        non = [h for h in res["history"] if h["outcome"] not in ("ok",)]
        if non:
            print("non-ok steps:")
            for h in non:
                print(f"  [{h['step']:02d}] {h['op']:<11} {h['element'][:44]:<44} "
                      f"{h['outcome']} {h.get('note','')}")
    return 0 if res["status"] == "done" else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="jev-browser",
                               description="TypeSafe/Jev-driven browser agent over CDP")
    p.add_argument("--version", action="version", version=f"jev-browser {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    def common(sp):
        sp.add_argument("--port", type=int, default=9222)
        sp.add_argument("--match", default=None, help="attach to a page whose URL contains this")
        sp.add_argument("--new-tab", action="store_true", help="open a fresh tab instead")
        sp.add_argument("--url", default=None, help="navigate here first")
        sp.add_argument("--json", action="store_true")
        sp.add_argument("--verbose", "-v", action="store_true")
        sp.add_argument("--max-elements", type=int, default=60)
        sp.add_argument("--decide-model", default=DEFAULT_MODEL, help="jev-latest | jev-preview")
        sp.add_argument("--text-provider", default="auto",
                        help="auto | lmstudio | ollama | deepseek | none")
        sp.add_argument("--text-model", default=None)
        sp.add_argument("--dispatch-log", default=None,
                        help="append-only JSONL of issued mutations "
                             "(default ~/.cache/jev-browser/dispatch.jsonl; 'none' disables)")

    s = sub.add_parser("doctor", help="check CDP, key, API, element table, text helper")
    common(s)
    s.set_defaults(func=cmd_doctor)

    s = sub.add_parser("table", help="dump the indexed element table (debug)")
    common(s)
    s.set_defaults(func=cmd_table)

    s = sub.add_parser("step", help="show one decision without acting on the page")
    common(s)
    s.add_argument("--goal", required=True)
    s.set_defaults(func=cmd_step)

    s = sub.add_parser("run", help="run the agent loop toward a goal")
    common(s)
    s.add_argument("--goal", required=True)
    s.add_argument("--max-steps", type=int, default=40)
    s.set_defaults(func=cmd_run)

    args = p.parse_args(argv)
    try:
        return args.func(args)
    except CDPError as e:
        print(f"cdp error: {e}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
