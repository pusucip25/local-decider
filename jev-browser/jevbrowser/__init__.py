"""jev-browser - a TypeSafe/Jev-driven browser agent layer for Chrome over CDP.

One TypeSafe round trip decides the operation and every target head; a small
local LLM only ever writes text. No screenshots, no HTML in the prompt.
"""
from .agent import JevBrowserAgent, page_signature          # noqa: F401
from .cdp import CDP, CDPError, page_targets                # noqa: F401
from .dom import describe, snapshot, table_js               # noqa: F401
from .policy import decide, OPERATIONS                      # noqa: F401
from .textmodel import TextModel                            # noqa: F401

__version__ = "0.2.0"
__all__ = ["CDP", "CDPError", "page_targets", "snapshot", "describe", "table_js",
           "decide", "OPERATIONS", "TextModel", "JevBrowserAgent", "page_signature"]
