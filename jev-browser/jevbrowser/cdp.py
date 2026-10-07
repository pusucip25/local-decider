"""Minimal Chrome DevTools Protocol client.

Deps: websocket-client (already present on this machine).
Talks to a Chrome started with --remote-debugging-port (default 9222),
attaches to a page target with flattened sessions, and speaks raw CDP.
"""
from __future__ import annotations

import json
import time
import urllib.request


class CDPError(RuntimeError):
    pass


def _get(url: str, timeout: float = 10.0) -> dict:
    with urllib.request.urlopen(url, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8"))


def list_targets(port: int = 9222, host: str = "127.0.0.1") -> list:
    return _get(f"http://{host}:{port}/json/list")


def browser_ws_url(port: int = 9222, host: str = "127.0.0.1") -> str:
    return _get(f"http://{host}:{port}/json/version")["webSocketDebuggerUrl"]


def page_targets(port: int = 9222, host: str = "127.0.0.1") -> list:
    return [t for t in list_targets(port, host) if t.get("type") == "page"]


class CDP:
    """One connection to the browser endpoint, attached to one page target."""

    def __init__(
        self,
        port: int = 9222,
        host: str = "127.0.0.1",
        target_url_contains: str | None = None,
        new_tab: bool = False,
        url: str | None = None,
        timeout: float = 90.0,
    ):
        from websocket import create_connection

        self.port = port
        self.host = host
        self._id = 0
        self.session_id: str | None = None
        self.target_id: str | None = None

        ws_url = browser_ws_url(port, host)
        self.ws = create_connection(
            ws_url,
            timeout=timeout,
            max_size=200 * 1024 * 1024,
            suppress_origin=True,
        )

        if new_tab:
            res = self.send("Target.createTarget", {"url": url or "about:blank"})
            target_id = res["targetId"]
        else:
            targets = [t for t in self.send("Target.getTargets")["targetInfos"]
                       if t.get("type") == "page"]
            if not targets:
                res = self.send("Target.createTarget", {"url": url or "about:blank"})
                target_id = res["targetId"]
            else:
                chosen = None
                if target_url_contains:
                    for t in targets:
                        if target_url_contains in (t.get("url") or ""):
                            chosen = t
                            break
                if chosen is None:
                    chosen = targets[0]
                target_id = chosen["targetId"]

        att = self.send("Target.attachToTarget", {"targetId": target_id, "flatten": True})
        self.session_id = att["sessionId"]
        self.target_id = target_id

        self.send("Page.enable")
        self.send("Runtime.enable")

    # ---------------------------------------------------------------- transport
    def send(self, method: str, params: dict | None = None, session: str | None = None,
             timeout: float | None = None):
        self._id += 1
        mid = self._id
        msg: dict = {"id": mid, "method": method}
        if params:
            msg["params"] = params
        sid = self.session_id if session is None else session
        if sid:
            msg["sessionId"] = sid

        self.ws.send(json.dumps(msg))
        deadline = time.time() + (timeout or 90.0)
        while True:
            if time.time() > deadline:
                raise CDPError(f"timeout waiting for {method}")
            try:
                raw = self.ws.recv()
            except Exception as e:  # socket timeout / closed
                raise CDPError(f"{method}: {e}")
            try:
                resp = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if resp.get("id") != mid:
                continue  # a CDP event; ignores are fine here
            if "error" in resp:
                raise CDPError(f"{method}: {resp['error'].get('message')}")
            return resp.get("result", {})

    def close(self):
        try:
            self.ws.close()
        except Exception:
            pass

    # ---------------------------------------------------------------- recovery
    def _pages(self) -> list:
        return [t for t in self.send("Target.getTargets", session="")["targetInfos"]
                if t.get("type") == "page"]

    def reattach(self, prefer_url: str | None = None) -> bool:
        """Re-attach after the session went stale (detach, target swap). Returns ok."""
        try:
            pages = self._pages()
        except Exception:
            return False
        if not pages:
            return False
        chosen = None
        for p in pages:
            if p.get("targetId") == self.target_id:
                chosen = p
                break
        if chosen is None and prefer_url:
            for p in pages:
                if prefer_url in (p.get("url") or ""):
                    chosen = p
                    break
        if chosen is None:
            chosen = pages[0]
        try:
            att = self.send("Target.attachToTarget",
                            {"targetId": chosen["targetId"], "flatten": True}, session="")
        except Exception:
            return False
        self.session_id = att["sessionId"]
        self.target_id = chosen["targetId"]
        try:
            self.send("Page.enable")
            self.send("Runtime.enable")
        except Exception:
            return False
        return True

    def reconnect(self, prefer_url: str | None = None) -> bool:
        """Rebuild the websocket entirely, then attach again."""
        from websocket import create_connection
        self.close()
        time.sleep(0.4)
        try:
            self.ws = create_connection(browser_ws_url(self.port, self.host), timeout=90.0,
                                        max_size=200 * 1024 * 1024, suppress_origin=True)
        except Exception:
            return False
        self.session_id = None
        return self.reattach(prefer_url)

    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()

    # ---------------------------------------------------------------- evaluate
    def evaluate(self, expression: str, await_promise: bool = True, timeout_ms: int = 30000):
        res = self.send(
            "Runtime.evaluate",
            {
                "expression": expression,
                "returnByValue": True,
                "awaitPromise": await_promise,
                "userGesture": True,
                "timeout": timeout_ms,
            },
        )
        if res.get("exceptionDetails"):
            d = res["exceptionDetails"]
            msg = (d.get("exception") or {}).get("description") or d.get("text")
            raise CDPError(f"JS error: {msg}")
        return res.get("result", {}).get("value")

    # ---------------------------------------------------------------- page
    def url(self) -> str:
        return self.evaluate("location.href")

    def navigate(self, url: str, timeout: float = 45.0) -> None:
        self.send("Page.navigate", {"url": url})
        self.wait_ready(timeout)

    def wait_ready(self, timeout: float = 45.0) -> None:
        deadline = time.time() + timeout
        while time.time() < deadline:
            try:
                if self.evaluate("document.readyState") == "complete":
                    break
            except CDPError:
                pass
            time.sleep(0.2)
        time.sleep(0.25)  # let the first paint settle

    # ---------------------------------------------------------------- input
    def click_xy(self, x: float, y: float) -> None:
        for t in ("mouseMoved", "mousePressed", "mouseReleased"):
            p = {"type": t, "x": x, "y": y, "button": "left", "clickCount": 1,
                 "buttons": 1 if t == "mousePressed" else 0}
            self.send("Input.dispatchMouseEvent", p)

    def wheel(self, x: float, y: float, delta_y: float) -> None:
        self.send("Input.dispatchMouseEvent",
                  {"type": "mouseWheel", "x": x, "y": y, "deltaX": 0, "deltaY": delta_y})

    def insert_text(self, text: str) -> None:
        self.send("Input.insertText", {"text": text})

    def press(self, key: str) -> None:
        common = {"key": key, "code": key, "windowsVirtualKeyCode": 13 if key == "Enter" else 0}
        self.send("Input.dispatchKeyEvent", {"type": "keyDown", **common})
        self.send("Input.dispatchKeyEvent", {"type": "keyUp", **common})
