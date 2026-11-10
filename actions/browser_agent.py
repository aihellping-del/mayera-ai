"""JARVIS's own personal browser (v3.20, user's ask).

Until now JARVIS could only OPEN a site in the user's everyday
browser (open_website) and click screen coordinates. The user
asked for a browser of JARVIS's own: 'mai jo bolu usko research
karega, or jisko bhi bolu usko click bhi kare' - research what he
says, and click what he names.

Design: launch Chrome or Edge (whichever the PC has) with a
dedicated profile folder (~/.jarvis_browser - JARVIS's own,
separate from the user's personal browser and its logins) and
drive it over the Chrome DevTools Protocol on localhost:9333,
using the `websockets` package the project already depends on.
No new dependency, no driver downloads.

What it can do: web search (DuckDuckGo's clean results page,
shown live in JARVIS's window so the user SEES the research
happening), list results by number, open a result, read the
page's text back for the model to summarise aloud, click a
visible link/button BY ITS NAME/TEXT, and go back.

Safety (his standing rulebook): a click whose label smells like
money or sending or deleting (buy / pay / checkout / order /
send / delete / subscribe...) is NOT performed silently - the
caller passes a confirm callback (the UI Haan/Nahi gate in
main.py); without approval the click is cancelled. CAPTCHA and
login walls are never bypassed - the user handles those in the
window himself, exactly like his rulebook says.

The transport is a tiny interface (eval / navigate / alive) so
tests drive a fake page; the real one is _CdpPage below.
"""

import asyncio
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

DEBUG_PORT = 9333
SEARCH_URL = "https://html.duckduckgo.com/html/?q="

# Click labels that must never be pressed without his Haan on the
# confirmation card. Matched case-insensitively as substrings.
RISKY_CLICK_WORDS = (
    "buy", "pay", "checkout", "check out", "order now", "place order",
    "send", "delete", "remove", "subscribe", "donate", "transfer",
    "withdraw", "confirm order", "kharid", "bhejo", "hatao", "mitao",
)


def _find_browser():
    """Chrome first, Edge second (same policy as the UI window)."""
    if not sys.platform.startswith("win"):
        return None
    env = os.environ
    candidates = [
        Path(env.get("ProgramFiles", "")) / "Google/Chrome/Application/chrome.exe",
        Path(env.get("ProgramFiles(x86)", "")) / "Google/Chrome/Application/chrome.exe",
        Path(env.get("LOCALAPPDATA", "")) / "Google/Chrome/Application/chrome.exe",
        Path(env.get("ProgramFiles(x86)", "")) / "Microsoft/Edge/Application/msedge.exe",
        Path(env.get("ProgramFiles", "")) / "Microsoft/Edge/Application/msedge.exe",
    ]
    for path in candidates:
        try:
            if path.is_file():
                return str(path)
        except OSError:
            continue
    return shutil.which("chrome") or shutil.which("msedge")


def _norm_text(text):
    return " ".join((text or "").lower().split())


def is_risky_label(label):
    low = _norm_text(label)
    return any(word in low for word in RISKY_CLICK_WORDS)


def _unwrap_result_url(href):
    """DuckDuckGo result links carry the real URL in ?uddg=."""
    try:
        parsed = urllib.parse.urlparse(href or "")
        qs = urllib.parse.parse_qs(parsed.query)
        if "uddg" in qs:
            return qs["uddg"][0]
    except Exception:  # noqa: BLE001
        pass
    return href or ""


_EXTRACT_RESULTS_JS = """
(() => {
  const pick = (a) => ({title: (a.innerText || '').trim(),
                        href: a.href || ''});
  let out = Array.from(document.querySelectorAll('a.result__a')).map(pick);
  if (!out.length) {
    out = Array.from(document.querySelectorAll('a'))
      .filter(a => (a.innerText || '').trim().length >= 20
                   && /^https?:/.test(a.href || ''))
      .map(pick);
  }
  return out.filter(r => r.title && r.href).slice(0, 8);
})()
"""

_FIND_CLICKABLE_JS = """
((query) => {
  const norm = (s) => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
  const els = Array.from(document.querySelectorAll(
    'a, button, [role="button"], input[type="submit"], input[type="button"]'));
  for (const el of els) {
    const rects = el.getClientRects();
    if (!rects || !rects.length) continue;
    const label = norm(el.innerText || el.value || el.getAttribute('aria-label'));
    if (label && label.includes(query)) {
      document.querySelectorAll('[data-jarvis-click]').forEach(
        e => e.removeAttribute('data-jarvis-click'));
      el.setAttribute('data-jarvis-click', '1');
      el.scrollIntoView({block: 'center'});
      const r = el.getBoundingClientRect();
      // Where the element sits on the real screen, so the user's
      // own mouse arrow can glide there visibly (v3.24).
      const sx = Math.round(window.screenX + r.left + r.width / 2);
      const sy = Math.round(window.screenY
        + (window.outerHeight - window.innerHeight)
        + r.top + r.height / 2);
      return {found: true, label: label.slice(0, 120), point: [sx, sy]};
    }
  }
  return {found: false};
})(%s)
"""

_DO_CLICK_JS = """
(() => {
  const el = document.querySelector('[data-jarvis-click="1"]');
  if (!el) return {clicked: false};
  el.removeAttribute('data-jarvis-click');
  el.click();
  return {clicked: true};
})()
"""

_READ_PAGE_JS = "document.body ? document.body.innerText : ''"


class _CdpPage:
    """One browser tab driven over the DevTools Protocol."""

    def __init__(self, ws_url):
        self._ws_url = ws_url
        self._ws = None
        self._next_id = 0
        self._pending = {}
        self._reader = None

    async def connect(self):
        import websockets
        self._ws = await websockets.connect(self._ws_url,
                                            max_size=16 * 1024 * 1024)
        self._reader = asyncio.ensure_future(self._read_loop())
        await self.call("Page.enable")
        await self.call("Runtime.enable")
        return self

    async def _read_loop(self):
        try:
            async for raw in self._ws:
                try:
                    msg = json.loads(raw)
                except ValueError:
                    continue
                fut = self._pending.pop(msg.get("id"), None)
                if fut is not None and not fut.done():
                    fut.set_result(msg)
        except Exception:  # noqa: BLE001 - connection closed
            for fut in self._pending.values():
                if not fut.done():
                    fut.set_exception(ConnectionError("browser closed"))
            self._pending.clear()

    async def call(self, method, **params):
        if self._ws is None:
            raise ConnectionError("browser not connected")
        self._next_id += 1
        mid = self._next_id
        fut = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        await self._ws.send(json.dumps(
            {"id": mid, "method": method, "params": params}))
        msg = await asyncio.wait_for(fut, timeout=20)
        if "error" in msg:
            raise RuntimeError(str(msg["error"])[:200])
        return msg.get("result") or {}

    async def eval(self, expression):
        result = await self.call(
            "Runtime.evaluate", expression=expression,
            returnByValue=True, awaitPromise=True)
        inner = result.get("result") or {}
        if inner.get("subtype") == "error":
            raise RuntimeError(str(inner.get("description"))[:200])
        return inner.get("value")

    async def navigate(self, url):
        await self.call("Page.navigate", url=url)
        # Wait until the page is usable (max ~4.5 s): readyState
        # interactive/complete, OR real content already on screen -
        # ad/tracker-heavy pages can sit at 'loading' long after
        # the article is readable, and research speed matters.
        deadline = time.monotonic() + 4.5
        while time.monotonic() < deadline:
            try:
                state = await self.eval(
                    "document.readyState + '|' + "
                    "(document.body ? document.body.innerText.length : 0)")
            except Exception:  # noqa: BLE001
                state = None
            if state:
                ready, _, length = str(state).partition("|")
                if ready in ("complete", "interactive"):
                    return
                try:
                    if int(length) > 300:
                        return
                except ValueError:
                    pass
            await asyncio.sleep(0.25)

    async def alive(self):
        try:
            return (await self.eval("1")) == 1
        except Exception:  # noqa: BLE001
            return False


def _fetch_page_ws_url(port):
    """The page target's websocket URL from the /json/list API."""
    with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/json/list", timeout=3) as resp:
        targets = json.loads(resp.read().decode("utf-8", "replace"))
    for target in targets:
        if target.get("type") == "page" and target.get("webSocketDebuggerUrl"):
            return target["webSocketDebuggerUrl"]
    return None


class BrowserAgent:
    def __init__(self, profile_dir=None, popen=None, page_factory=None,
                 browser_finder=None, port=DEBUG_PORT):
        self._profile = (Path(profile_dir) if profile_dir
                         else Path.home() / ".jarvis_browser")
        self._popen = popen or subprocess.Popen
        self._page_factory = page_factory  # async () -> page (tests)
        self._finder = browser_finder or _find_browser
        self._port = port
        self._page = None
        self._proc = None
        self._last_results = []

    # ------------------------------------------------------------------
    async def _ensure_page(self):
        if self._page is not None and await self._page.alive():
            return self._page
        if self._page_factory is not None:
            self._page = await self._page_factory()
            return self._page
        exe = self._finder()
        if not exe:
            raise RuntimeError("Chrome ya Edge nahi mila is PC par")
        self._profile.mkdir(parents=True, exist_ok=True)
        self._popen(
            [exe, f"--remote-debugging-port={self._port}",
             f"--user-data-dir={self._profile}",
             "--no-first-run", "--window-size=1220,860", "about:blank"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        ws_url = None
        deadline = time.monotonic() + 12.0
        while time.monotonic() < deadline and not ws_url:
            try:
                ws_url = await asyncio.to_thread(
                    _fetch_page_ws_url, self._port)
            except Exception:  # noqa: BLE001 - browser still starting
                ws_url = None
            if not ws_url:
                await asyncio.sleep(0.4)
        if not ws_url:
            raise RuntimeError("browser khula par control nahi mila")
        self._page = await _CdpPage(ws_url).connect()
        return self._page

    # ------------------------------------------------------------------
    async def search(self, query):
        query = (query or "").strip()
        if not query:
            return {"status": "error", "message": "kya search karna hai, ye nahi bataya"}
        page = await self._ensure_page()
        await page.navigate(SEARCH_URL + urllib.parse.quote_plus(query))
        raw = await page.eval(_EXTRACT_RESULTS_JS) or []
        results = []
        for item in raw:
            title = (item.get("title") or "").strip()
            href = _unwrap_result_url(item.get("href") or "")
            if title and href.startswith("http"):
                results.append({"title": title[:140], "url": href})
        self._last_results = results
        if not results:
            return {"status": "error",
                    "message": "koi result nahi mila - browser khula hai, "
                               "page par kuch aur ho sakta hai (jaise "
                               "consent ya captcha); Golu se kehna wo "
                               "window me dekh le"}
        listing = [{"number": i + 1, "title": r["title"],
                    "site": urllib.parse.urlparse(r["url"]).netloc}
                   for i, r in enumerate(results)]
        return {"status": "done", "query": query, "results": listing}

    async def open_result(self, number):
        try:
            idx = int(number) - 1
        except (TypeError, ValueError):
            idx = -1
        if idx < 0 or idx >= len(self._last_results):
            return {"status": "error",
                    "message": "pehle browser_search karo, phir number bolo"}
        page = await self._ensure_page()
        target = self._last_results[idx]
        await page.navigate(target["url"])
        title = await page.eval("document.title") or target["title"]
        return {"status": "done", "opened": title,
                "url": target["url"]}

    async def read_page(self, limit=1800):
        page = await self._ensure_page()
        text = await page.eval(_READ_PAGE_JS) or ""
        text = "\n".join(line.strip() for line in str(text).splitlines()
                         if line.strip())
        title = await page.eval("document.title") or ""
        return {"status": "done", "title": title,
                "text": text[:limit],
                "note": "text yahin se padh kar Golu ko apne shabdon "
                        "me summary sunani hai"}

    async def research(self, query):
        found = await self.search(query)
        if found.get("status") != "done":
            return found
        opened = await self.open_result(1)
        if opened.get("status") != "done":
            return opened
        page_text = await self.read_page()
        return {"status": "done", "query": query,
                "source_title": opened.get("opened"),
                "source_url": opened.get("url"),
                "text": page_text.get("text", ""),
                "more_results": found["results"],
                "note": "upar wale text ko padh kar Golu ko chhoti "
                        "si summary apne shabdon me sunao; agar use "
                        "aur chahiye to dusre results bhi hain"}

    async def click_text(self, text, confirm=None):
        """Click the visible link/button whose label contains text.
        confirm: optional async callable(question) -> bool, used
        for risky labels; without approval the click is cancelled."""
        query = _norm_text(text)
        if not query:
            return {"status": "error", "message": "kis par click karna hai, ye nahi bataya"}
        page = await self._ensure_page()
        found = await page.eval(
            _FIND_CLICKABLE_JS % json.dumps(query)) or {}
        if not found.get("found"):
            return {"status": "error",
                    "message": f"'{text}' naam ka koi link/button is "
                               "page par nahi dikha"}
        label = found.get("label") or text
        if is_risky_label(label):
            approved = False
            if confirm is not None:
                approved = bool(await confirm(
                    f"Browser me '{label}' par click karu? "
                    "Ye paisa/send/delete wala button lagta hai."))
            if not approved:
                return {"status": "cancelled",
                        "message": f"'{label}' par click NAHI kiya - "
                                   "confirmation nahi mili"}
        clicked = await page.eval(_DO_CLICK_JS) or {}
        if not clicked.get("clicked"):
            return {"status": "error", "message": "button mila par click nahi ho paya"}
        await asyncio.sleep(0.8)
        new_title = await page.eval("document.title") or ""
        return {"status": "done", "clicked": label, "page_now": new_title,
                "point": found.get("point")}

    async def back(self):
        page = await self._ensure_page()
        await page.eval("history.back()")
        await asyncio.sleep(0.8)
        title = await page.eval("document.title") or ""
        return {"status": "done", "page_now": title}
