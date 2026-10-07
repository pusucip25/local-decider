"""Element table: one DOM snapshot -> indexed accessible elements + live refs.

The page-side script assigns a code-owned index to every visible interactive
node, keeps the real node references in a Map (used later for execution), and
returns a JSON blob the policy can read. Indices are positional per snapshot:
a fresh snapshot invalidates the old Map.
"""
from __future__ import annotations

import json

DEFAULT_MAX = 60

_TABLE_JS = r"""
(() => {
  const MAX = __MAX__;
  const ROLES = {
    a:'link', button:'button', input:'__input__', select:'combobox',
    textarea:'textbox', summary:'button', option:'option', label:'',
    nav:'', form:'', header:'', footer:'', main:'', section:'', article:''
  };
  const IN_ROLE = new Set(['button','link','textbox','searchbox','combobox','listbox',
    'option','checkbox','radio','switch','menuitem','menuitemcheckbox','menuitemradio',
    'tab','slider','spinbutton','textbox','treeitem','gridcell']);

  const txt = (s, n) => (s || '').replace(/\s+/g, ' ').trim().slice(0, n || 90);

  const visible = (el, r) => {
    if (!r || r.width < 2 || r.height < 2) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none') return false;
    if (parseFloat(cs.opacity || '1') < 0.05) return false;
    if (cs.pointerEvents === 'none' && !el.disabled) return true;
    return true;
  };

  const roleOf = (el) => {
    const explicit = el.getAttribute('role');
    if (explicit) return explicit.toLowerCase();
    const t = el.tagName.toLowerCase();
    if (t === 'input') {
      const ty = (el.getAttribute('type') || 'text').toLowerCase();
      if (ty === 'checkbox') return 'checkbox';
      if (ty === 'radio') return 'radio';
      if (ty === 'submit' || ty === 'button' || ty === 'reset') return 'button';
      if (ty === 'search') return 'searchbox';
      return 'textbox';
    }
    return ROLES[t] !== undefined ? ROLES[t] : '';
  };

  const nameOf = (el, role) => {
    const al = el.getAttribute('aria-label');
    if (al) return txt(al);
    const lb = el.getAttribute('aria-labelledby');
    if (lb) {
      const parts = lb.split(/\s+/).map(id => {
        const n = document.getElementById(id);
        return n ? n.innerText : '';
      }).filter(Boolean);
      if (parts.length) return txt(parts.join(' '));
    }
    if (el.id) {
      try {
        const l = document.querySelector('label[for="' + CSS.escape(el.id) + '"]');
        if (l) return txt(l.innerText);
      } catch (e) {}
    }
    const wl = el.closest('label');
    if (wl) { const v = txt(wl.innerText); if (v) return v; }
    const ph = el.getAttribute('placeholder');
    if (ph) return txt(ph);
    const nm = el.getAttribute('name');
    if (nm) return txt(nm);
    const it = txt(el.innerText || el.textContent || '');
    if (it) return it;
    return txt(el.getAttribute('title') || '') || role;
  };

  const valueOf = (el, role) => {
    const t = el.tagName.toLowerCase();
    if (role === 'checkbox' || role === 'radio' || role === 'switch')
      return el.checked ? 'checked' : 'unchecked';
    if (t === 'select') {
      const o = el.options[el.selectedIndex];
      return o ? txt(o.textContent, 40) : '';
    }
    if (t === 'input' || t === 'textarea') return txt(el.value, 60);
    const av = el.getAttribute('aria-valuetext') || el.getAttribute('aria-valuenow');
    if (av) return txt(av, 40);
    return '';
  };

  const isInteractive = (el, role) => {
    if (IN_ROLE.has(role)) return true;
    if (el.hasAttribute('onclick')) return true;
    if (el.getAttribute('contenteditable') === 'true') return true;
    return false;
  };

  const old = window.__jevEls;
  const map = new Map();
  const meta = new Map();
  window.__jevEls = map;
  window.__jevMeta = meta;

  const vw = window.innerWidth, vh = window.innerHeight;
  const cand = [];
  const sel = 'a[href],button,input,select,textarea,summary,[role],[contenteditable="true"],[tabindex],[onclick]';
  for (const el of document.querySelectorAll(sel)) {
    const st = getComputedStyle(el);
    if (st.display === 'none' || st.visibility === 'hidden') continue;
    const role = roleOf(el);
    if (!isInteractive(el, role)) continue;
    const r = el.getBoundingClientRect();
    if (!visible(el, r)) continue;
    const cx = r.x + r.width / 2, cy = r.y + r.height / 2;
    const inView = cx > 0 && cy > 0 && cx < vw && cy < vh && r.y < vh && r.bottom > 0;
    const occluded = (() => {
      if (!inView) return false;
      try {
        const top = document.elementFromPoint(
          Math.min(Math.max(cx, 1), vw - 1), Math.min(Math.max(cy, 1), vh - 1));
        return !!(top && top !== el && !el.contains(top) && !top.contains(el));
      } catch (e) { return false; }
    })();
    cand.push({el, role, r, inView, occluded});
  }

  cand.sort((a, b) => (b.inView ? 1 : 0) - (a.inView ? 1 : 0));
  const out = [];
  let i = 0;
  for (const c of cand) {
    if (out.length >= MAX) break;
    i += 1;
    const nm = nameOf(c.el, c.role);
    map.set(i, c.el);
    meta.set(i, {role: c.role || '', name: nm});
    out.push({
      i: i,
      role: c.role || '',
      name: nm,
      value: valueOf(c.el, c.role),
      tag: c.el.tagName.toLowerCase(),
      disabled: !!(c.el.disabled) || c.el.getAttribute('aria-disabled') === 'true',
      inView: c.inView,
      occluded: c.occluded,
      box: {x: Math.round(c.r.x), y: Math.round(c.r.y),
            w: Math.round(c.r.width), h: Math.round(c.r.height)}
    });
  }

  let text = '';
  try { text = (document.body ? document.body.innerText : '') || ''; } catch (e) {}
  text = text.replace(/\s+/g, ' ').trim().slice(0, 1800);

  return JSON.stringify({
    url: location.href,
    title: document.title,
    scrollY: Math.round(window.scrollY),
    viewport: {w: vw, h: vh},
    text: text,
    elements: out
  });
})()
"""


def table_js(max_elements: int = DEFAULT_MAX) -> str:
    return _TABLE_JS.replace("__MAX__", str(int(max_elements)))


def snapshot(cdp, max_elements: int = DEFAULT_MAX) -> dict:
    """Take a fresh snapshot and return {url,title,scrollY,viewport,text,elements}."""
    raw = cdp.evaluate(table_js(max_elements))
    return json.loads(raw)


def box_of(cdp, index: int) -> dict | None:
    """Re-read geometry for an index from the CURRENT (live) snapshot map.
    Name/role come from the snapshot's own metadata map, so the guard compares
    like with like (the same accessible name the policy saw)."""
    expr = (
        "(() => { const e = (window.__jevEls||new Map()).get(%d);"
        " const m = (window.__jevMeta||new Map()).get(%d) || {};"
        " if (!e || !e.isConnected) return null;"
        " const r = e.getBoundingClientRect();"
        " const cs = getComputedStyle(e);"
        " return JSON.stringify({x:r.x,y:r.y,w:r.width,h:r.height,"
        " disabled: !!e.disabled || e.getAttribute('aria-disabled')==='true',"
        " vis: cs.visibility, disp: cs.display,"
        " role: m.role || '', name: m.name || ''}); })()"
        % (int(index), int(index))
    )
    raw = cdp.evaluate(expr)
    return json.loads(raw) if raw else None


def identity_of(cdp, index: int) -> str:
    """Semantic identity of a live element (for freshness guards)."""
    expr = (
        "(() => { const e = (window.__jevEls||new Map()).get(%d);"
        " const m = (window.__jevMeta||new Map()).get(%d) || {};"
        " if (!e || !e.isConnected) return '';"
        " const r = e.getBoundingClientRect();"
        " return [e.tagName, m.role||'', m.name||'',"
        "  Math.round(r.x)+','+Math.round(r.y)+','+Math.round(r.width)].join('|'); })()"
        % (int(index), int(index))
    )
    v = cdp.evaluate(expr)
    return v or ""


def describe(elements: list) -> str:
    lines = []
    for e in elements:
        v = f" · value={e['value']}" if e.get("value") else ""
        flags = ""
        if e.get("disabled"):
            flags += " [disabled]"
        if not e.get("inView"):
            flags += " [off-view]"
        if e.get("occluded"):
            flags += " [occluded]"
        lines.append(f"[{e['i']}] {e['role']:<10} {e['name'][:60]}{v}{flags}")
    return "\n".join(lines)
