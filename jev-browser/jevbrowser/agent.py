"""The loop: observe -> decide (one TypeSafe round trip) -> guard -> execute.

Design notes carried over from the jev-ultrafast approach:
  * the observation is an indexed element table, never raw HTML
  * the decision is one request that answers the operation AND every target head
  * text is the only thing a small LLM writes, and only for TYPE_TEXT
  * geometry, visibility, enabled state and occlusion are re-read immediately
    before every input; a changed element invalidates one decision, not the run
  * freshness is compared semantically (URL + element identity + scroll), not by
    counting DOM mutations
"""
from __future__ import annotations

import hashlib
import json
import os
import time

from . import dom
from .policy import decide
from .textmodel import TextModel

SETTLE_TIMEOUT = 4.0
MAX_REDECIDE = 1

_SIG_JS = r"""
(() => {
  const m = window.__jevEls || new Map();
  const parts = [];
  let n = 0;
  for (const [i, e] of m) {
    n++;
    if (n > 30) break;
    const nm = (e.getAttribute('aria-label') || e.innerText || e.placeholder || '')
      .replace(/\s+/g, ' ').trim().slice(0, 24);
    let val = '';
    try { val = (e.value === undefined || e.value === null) ? '' : String(e.value).slice(0, 24); } catch (x) {}
    let st = '';
    try {
      st = (e.checked === undefined)
        ? (e.getAttribute('aria-checked') || e.getAttribute('aria-selected') || '')
        : (e.checked ? '1' : '0');
    } catch (x) {}
    parts.push(i + ':' + e.tagName + ':' + nm + ':' + val + ':' + st);
  }
  let open = '';
  try { open = document.querySelectorAll('[role="dialog"],[role="listbox"],[role="menu"],dialog[open]').length; } catch (x) {}
  return [location.href, Math.round(window.scrollY),
          (document.body ? document.body.innerText.length : 0), open,
          parts.join('~')].join('||');
})()
"""


def page_signature(cdp) -> str:
    try:
        sig = cdp.evaluate(_SIG_JS)
    except Exception:
        return ""
    return hashlib.sha1((sig or "").encode("utf-8", "replace")).hexdigest()[:12]


class JevBrowserAgent:
    def __init__(self, cdp, goal: str, max_steps: int = 40,
                 decide_model: str = "jev-latest", text: TextModel | None = None,
                 verbose: bool = False, allow_missing_text: bool = False,
                 dispatch_log: str | None = None):
        self.cdp = cdp
        self.goal = goal
        self.max_steps = max_steps
        self.decide_model = decide_model
        self.text = text or TextModel(verbose=verbose)
        self.verbose = verbose
        self.allow_missing_text = allow_missing_text
        # append-only record of every mutation ISSUED (not its outcome); survives a
        # crash between dispatch and observation, which `history` cannot
        if dispatch_log is None:
            dispatch_log = os.path.join(os.path.expanduser("~"), ".cache",
                                        "jev-browser", "dispatch.jsonl")
        elif dispatch_log.strip().lower() in ("", "none", "-", "off"):
            dispatch_log = None
        if dispatch_log:
            try:
                os.makedirs(os.path.dirname(os.path.abspath(dispatch_log)), exist_ok=True)
            except OSError as e:
                if verbose:
                    print(f"  ! dispatch log unavailable ({e})", flush=True)
                dispatch_log = None
        self.dispatch_log_path = dispatch_log
        self.history: list = []
        self.log: list = []
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self.decide_seconds = 0.0

    # ------------------------------------------------------------------ helpers
    def _say(self, msg: str) -> None:
        self.log.append(msg)
        if self.verbose:
            print(msg, flush=True)

    def _settle(self, before: str, timeout: float = SETTLE_TIMEOUT) -> bool:
        """Wait until the page changes semantically (or give up)."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            time.sleep(0.25)
            if page_signature(self.cdp) != before:
                time.sleep(0.15)
                return True
        return False

    def _record(self, step: int, op: str, target, label: str, outcome: str, note: str = ""):
        self.history.append({
            "step": step, "op": op, "target": target,
            "element": label, "outcome": outcome,
            **({"note": note} if note else {}),
        })

    def _dispatch(self, step: int, op: str, target, label: str, phase: str,
                  outcome: str = "", note: str = "") -> None:
        """One JSONL line per phase: "dispatch" BEFORE the mutation, then "result".

        `history` is model-visible and records how a step ENDED; this file records
        that the mutation was ISSUED. If the process dies in between, the log still
        shows the page may have changed (upstream rule: log execution, then observe
        its result). Opened, written and closed per line, so a crash cannot lose it.
        """
        if not self.dispatch_log_path:
            return
        rec = {"t": time.strftime("%Y-%m-%dT%H:%M:%S"), "epoch": round(time.time(), 3),
               "step": step, "op": op, "target": target, "element": label, "phase": phase}
        if outcome:
            rec["outcome"] = outcome
        if note:
            rec["note"] = note
        try:
            with open(self.dispatch_log_path, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except OSError as e:
            self._say(f"     ! dispatch log write failed ({e})")

    def _live(self, index: int) -> dict | None:
        return dom.box_of(self.cdp, index)

    def _observe(self) -> dict:
        """Snapshot with CDP recovery: a stale session is re-attached, not fatal."""
        last: Exception | None = None
        for attempt in (1, 2, 3):
            try:
                return dom.snapshot(self.cdp)
            except Exception as e:
                last = e
                msg = str(e).lower()
                stale = ("session with given id" in msg or "not attached" in msg
                         or "target closed" in msg or "websocket" in msg
                         or "not found" in msg or "connection" in msg)
                if not stale or attempt == 3:
                    break
                self._say(f"     ! cdp session lost ({e}) - reconnecting")
                if not self.cdp.reattach():
                    self.cdp.reconnect()
                time.sleep(0.4)
        raise last if last else RuntimeError("observe failed")

    def _focus_and_clear(self, index: int) -> None:
        self.cdp.evaluate(
            "(() => { const e=(window.__jevEls||new Map()).get(%d); if(!e) return;"
            " e.focus(); if (e.setSelectionRange && e.value !== undefined)"
            " { try { e.setSelectionRange(0, (e.value||'').length); } catch(x) {} } })()"
            % index
        )

    def _set_value_js(self, index: int, value: str) -> bool:
        expr = (
            "(() => { const e=(window.__jevEls||new Map()).get(%d); if(!e) return false;"
            " const proto = e.tagName==='TEXTAREA' ? HTMLTextAreaElement.prototype : HTMLInputElement.prototype;"
            " const d = Object.getOwnPropertyDescriptor(proto, 'value');"
            " if (d && d.set) d.set.call(e, %s); else e.value = %s;"
            " e.dispatchEvent(new Event('input', {bubbles:true}));"
            " e.dispatchEvent(new Event('change', {bubbles:true}));"
            " return true; })()" % (index, _js_str(value), _js_str(value))
        )
        return bool(self.cdp.evaluate(expr))

    def _select_option_js(self, index: int, value: str) -> bool:
        expr = (
            "(() => { const e=(window.__jevEls||new Map()).get(%d);"
            " if(!e || e.tagName!=='SELECT') return false;"
            " const want=%s; let hit=null;"
            " for (const o of e.options) { if (o.textContent.trim()===want || o.value===want)"
            " { hit=o; break; } }"
            " if (!hit) { const w=want.toLowerCase();"
            "   for (const o of e.options) { if (o.textContent.trim().toLowerCase().includes(w)) { hit=o; break; } } }"
            " if (!hit) return false;"
            " e.value = hit.value;"
            " e.dispatchEvent(new Event('input', {bubbles:true}));"
            " e.dispatchEvent(new Event('change', {bubbles:true}));"
            " return true; })()" % (index, _js_str(value))
        )
        return bool(self.cdp.evaluate(expr))

    # ------------------------------------------------------------------ actions
    def _hittable(self, index: int, x: float, y: float) -> bool:
        """True when the top-most element at (x,y) is our target or an ancestor/descendant."""
        expr = ("(() => { const e=(window.__jevEls||new Map()).get(%d);"
                " if (!e) return false;"
                " const t=document.elementFromPoint(%f,%f);"
                " return !!t && (t===e || e.contains(t) || t.contains(e)); })()"
                % (index, x, y))
        try:
            return bool(self.cdp.evaluate(expr))
        except Exception:
            return False

    def _do_click(self, index: int, label: str) -> tuple[str, str]:
        box = self._live(index)
        if not box:
            return "stale", "element gone before input"
        if box.get("disabled"):
            return "stale", "element became disabled"
        if box["w"] < 2 or box["h"] < 2 or box.get("disp") == "none":
            return "stale", "element not renderable"

        vp = {"w": 0, "h": 0}
        try:
            vp = json.loads(self.cdp.evaluate(
                "JSON.stringify({w: innerWidth, h: innerHeight})") or "{}")
        except Exception:
            pass
        vx = box["x"] + box["w"] / 2
        vy = box["y"] + box["h"] / 2

        need_scroll = (vx < 0 or vy < 0 or vx > vp.get("w", 0) or vy > vp.get("h", 0)
                       or not self._hittable(index, vx, vy))
        if need_scroll:
            # off-screen or covered: scroll it in, re-read, and only then click once
            self.cdp.evaluate(
                "(() => { const e=(window.__jevEls||new Map()).get(%d);"
                " if (e) e.scrollIntoView({block:'center', inline:'center'}); })()" % index)
            time.sleep(0.4)
            box = self._live(index)
            if not box:
                return "stale", "element gone after scrolling it into view"
            vx = box["x"] + box["w"] / 2
            vy = box["y"] + box["h"] / 2
            if not self._hittable(index, vx, vy):
                return "occluded", "target covered by another element"

        before = page_signature(self.cdp)
        self.cdp.click_xy(vx, vy)
        # exactly one dispatch: re-clicking can undo a toggle (checkbox) or double-submit
        if self._settle(before):
            return "ok", ""
        return "nochange", "click produced no visible change"

    def _do_type(self, index: int, label: str, snap: dict, element: dict) -> tuple[str, str]:
        value, how = self.text.write(self.goal, element, snap, self.history)
        if value is None:
            return "notext", f"no text value available (text helper: {self.text.status()})"
        box = self._live(index)
        if not box:
            return "stale", "element gone before input"
        before = page_signature(self.cdp)
        self.cdp.evaluate(
            "(() => { const e=(window.__jevEls||new Map()).get(%d);"
            " if (e) e.scrollIntoView({block:'center'}); })()" % index)
        time.sleep(0.2)
        box = self._live(index) or box
        self.cdp.click_xy(box["x"] + box["w"] / 2, box["y"] + box["h"] / 2)
        time.sleep(0.2)
        self._focus_and_clear(index)
        self.cdp.insert_text(value)
        time.sleep(0.15)
        took = self.cdp.evaluate(
            "(() => { const e=(window.__jevEls||new Map()).get(%d);"
            " return e ? String(e.value) : null; })()" % index)
        if took is None or value.strip() not in str(took):
            if not self._set_value_js(index, value):
                return "failed", "could not enter text"
        self.text.invalidate(self.goal, element)
        self._settle(before, timeout=2.0)
        return "ok", f"{how}: {value[:40]!r}"

    def _select_options(self, index: int) -> list:
        raw = self.cdp.evaluate(
            "(() => { const e=(window.__jevEls||new Map()).get(%d);"
            " if(!e || e.tagName!=='SELECT') return '[]';"
            " return JSON.stringify(Array.from(e.options).map(o => (o.textContent||'').trim()).filter(Boolean)); })()"
            % index)
        try:
            import json as _json
            return _json.loads(raw or "[]")
        except Exception:
            return []

    def _do_select(self, index: int, label: str, snap: dict) -> tuple[str, str]:
        element = next((e for e in snap.get("elements", []) if e["i"] == index), None)
        tag = (element or {}).get("tag", "")
        box = self._live(index)
        if not box:
            return "stale", "element gone before input"
        if tag == "select":
            options = self._select_options(index)
            if not options:
                return "failed", "select has no readable options"
            probe = dict(element or {})
            probe["options"] = options
            probe["value"] = ""
            want, how = self.text.write(self.goal, probe, snap, self.history)
            if want is None:
                return "notext", f"no option chosen (text helper: {self.text.status()})"
            before = page_signature(self.cdp)
            if self._select_option_js(index, want):
                self._settle(before, timeout=2.0)
                return "ok", f"{how}: {want[:40]!r}"
            return "failed", f"no option matching {want[:30]!r}"
        # ARIA combobox: the policy opens it with a CLICK; a SELECT here becomes a click
        return self._do_click(index, label)

    def _do_scroll(self, up: bool) -> tuple[str, str]:
        vp = self.cdp.evaluate("JSON.stringify({w:innerWidth,h:innerHeight})")
        import json as _json
        v = _json.loads(vp or '{"w":1000,"h":700}')
        before = page_signature(self.cdp)
        self.cdp.wheel(v["w"] / 2, v["h"] / 2, -600 if up else 600)
        if self._settle(before, timeout=2.0):
            return "ok", ""
        self.cdp.evaluate(f"window.scrollBy(0, {(-600 if up else 600)})")
        self._settle(before, timeout=2.0)
        return "ok", "js scroll fallback"

    # ------------------------------------------------------------------ loop
    def run(self) -> dict:
        t_start = time.time()
        status = "max_steps"
        recent: list = []

        for step in range(1, self.max_steps + 1):
            try:
                snap = self._observe()
            except Exception as e:
                status = f"observe_failed: {e}"
                break

            if self.verbose:
                print(f"\n--- step {step} | {snap.get('title','')[:50]} | "
                      f"{len(snap.get('elements', []))} elements", flush=True)

            try:
                d = decide(self.goal, snap, self.history, self.decide_model)
            except Exception as e:
                status = f"decide_failed: {e}"
                break

            self.decide_seconds += d["latency_s"]
            for k in self.usage:
                self.usage[k] += int((d.get("usage") or {}).get(k, 0) or 0)

            op, target = d["op"], d["target"]
            el = d["target_element"]
            label = f"{el['role']} · {el['name'][:50]}" if el else "-"
            prob = d["op_probabilities"].get(op, d["op_confidence"])
            self._say(f"[{step:02d}] {op:<11} {label}  "
                      f"(p={prob:.2f}, {d['latency_s']}s, heads={','.join(d['questions_asked'][1:]) or '-'})"
                      + (f"  <-- guard: {d['guard']}" if d.get("guard") else ""))

            if op == "DONE":
                self._record(step, op, target, label, "ok")
                status = "done"
                break
            if op == "BLOCKED":
                self._record(step, op, target, label, "blocked")
                status = "blocked"
                break
            if op == "WAIT":
                self._record(step, op, target, label, "ok")
                time.sleep(1.0)
                continue

            # loop detection: the same structured action three times in a row
            recent.append((op, target))
            if len(recent) >= 3 and len(set(recent[-3:])) == 1:
                self._say(f"     ! repeated {op} [target {target}] 3x - forcing a scroll")
                self._record(step, op, target, label, "loop")
                self._dispatch(step, "SCROLL_DOWN", None, "(forced, 3x repeat)", "dispatch")
                so, sn = self._do_scroll(up=False)
                self._dispatch(step, "SCROLL_DOWN", None, "(forced, 3x repeat)", "result",
                               so, sn or "after 3 identical actions")
                recent.clear()
                continue

            if op in ("CLICK", "TYPE_TEXT", "SELECT") and target is None:
                self._record(step, op, target, label, "notext" if op == "TYPE_TEXT" else "stale",
                             "policy returned no usable target")
                self._dispatch(step, "SCROLL_DOWN", None, "(recover, no target)", "dispatch")
                so, sn = self._do_scroll(up=False)
                self._dispatch(step, "SCROLL_DOWN", None, "(recover, no target)", "result",
                               so, sn or "policy returned no usable target")
                continue

            # ---- guard: the target must still be the same element we decided on
            redone = 0
            while True:
                live = self._live(target) if target else None
                same = bool(live) and _name_ok(live, el)
                if same or redone >= MAX_REDECIDE:
                    break
                redone += 1
                self._say("     ! target changed since the decision - re-deciding once")
                try:
                    snap = self._observe()
                    d = decide(self.goal, snap, self.history, self.decide_model)
                except Exception as e:
                    status = f"decide_failed: {e}"
                    break
                self.decide_seconds += d["latency_s"]
                for k in self.usage:
                    self.usage[k] += int((d.get("usage") or {}).get(k, 0) or 0)
                op, target, el = d["op"], d["target"], d["target_element"]
                label = f"{el['role']} · {el['name'][:50]}" if el else "-"
            if status.startswith("decide_failed"):
                break

            # ---- execute
            # log the dispatch BEFORE the mutation: if anything after this line dies,
            # the page may already have changed and the log says so
            self._dispatch(step, op, target, label, "dispatch")
            try:
                if op == "CLICK":
                    outcome, note = self._do_click(target, label)
                elif op == "TYPE_TEXT":
                    outcome, note = self._do_type(target, label, snap, el or {})
                elif op == "SELECT":
                    outcome, note = self._do_select(target, label, snap)
                elif op == "SCROLL_UP":
                    outcome, note = self._do_scroll(up=True)
                elif op == "SCROLL_DOWN":
                    outcome, note = self._do_scroll(up=False)
                else:
                    outcome, note = "failed", f"unknown op {op}"
            except Exception as e:
                outcome, note = "failed", f"{type(e).__name__}: {e}"
                self.cdp.reattach() or self.cdp.reconnect()

            self._record(step, op, target, label, outcome, note)
            self._dispatch(step, op, target, label, "result", outcome, note)
            self._say(f"     -> {outcome}" + (f" ({note})" if note else ""))
            if note and outcome in ("notext", "failed"):
                self._say(f"     ! {note}")
            time.sleep(0.15)

        total = time.time() - t_start
        return {
            "status": status,
            "goal": self.goal,
            "steps": len(self.history),
            "final_url": self.cdp.url(),
            "final_title": self.cdp.evaluate("document.title") or "",
            "wall_seconds": round(total, 2),
            "decide_seconds": round(self.decide_seconds, 2),
            "usage": self.usage,
            "history": self.history,
            "log": self.log,
            "dispatch_log": self.dispatch_log_path,
        }


def _name_ok(live: dict, el: dict | None) -> bool:
    if not el:
        return False
    want = (el.get("name") or "").strip().lower()[:24]
    got = (live.get("name") or "").strip().lower()
    if not want:
        return True
    if not got:
        return False
    return want[:12] in got or got[:12] in want


def _js_str(s: str) -> str:
    return __import__("json").dumps(s, ensure_ascii=False)
