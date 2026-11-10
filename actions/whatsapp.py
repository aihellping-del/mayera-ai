"""WhatsApp messaging through JARVIS's own browser (v3.25).

The user's ask: 'use apne WhatsApp se kisi ko message bhi
karwana chahta hu' - he dictates, JARVIS sends from HIS WhatsApp.

Route: WhatsApp Web inside JARVIS's personal browser (its own
tab, its own profile - the login persists there). The one-time
QR scan is done by the USER with his phone (Linked Devices),
exactly like his rulebook demands for logins: JARVIS never sees
or handles his credentials, and the QR is not bypassed.

His rulebook is enforced in code, not just in the prompt:
  * A message is NEVER sent without the confirmation callback
    approving the exact contact + exact text (in main.py that
    callback is the on-screen Haan/Nahi card only he can tap).
    No callback, or a 'no' - the text is cleared, nothing sends.
  * One contact, one message, dictated by him. No lists, no
    bulk, no auto-replies in this module at all.
  * After the send click, delivery is verified against the
    conversation before 'done' is claimed.

WhatsApp Web's page structure changes often, so every step has
fallbacks and every failure returns a specific, speakable reason
(the [tool] log then shows exactly which step needs attention).
"""

import asyncio
import json

WA_URL = "https://web.whatsapp.com/"
WA_PART = "web.whatsapp.com"

_STATE_JS = """
(() => {
  const searchBox = document.querySelector(
    'div[contenteditable="true"][data-tab="3"], '
    + '[aria-label="Search input textbox"], '
    + 'div[contenteditable="true"][data-tab="5"]');
  if (searchBox) return {state: 'logged_in'};
  const qr = document.querySelector('canvas')
    || document.querySelector('[data-testid="qrcode"]');
  const landing = document.body
    && /link a device|scan the qr|use whatsapp on your computer/i
        .test(document.body.innerText || '');
  if (qr || landing) return {state: 'qr'};
  return {state: 'loading'};
})()
"""

_FOCUS_SEARCH_JS = """
(() => {
  const box = document.querySelector(
    'div[contenteditable="true"][data-tab="3"], '
    + '[aria-label="Search input textbox"], '
    + 'div[contenteditable="true"][data-tab="5"]');
  if (!box) return {ok: false};
  box.focus();
  document.execCommand('selectAll', false, null);
  return {ok: true};
})()
"""

_FIND_CHAT_JS = """
((name) => {
  const norm = (s) => (s || '').toLowerCase().replace(/\\s+/g, ' ').trim();
  const want = norm(name);
  const rows = document.querySelectorAll(
    '#pane-side [role="listitem"], #pane-side [role="row"], '
    + '#pane-side > div > div > div');
  for (const row of rows) {
    const titled = row.querySelector('span[title]');
    const label = norm(titled ? titled.getAttribute('title')
                        : row.innerText);
    if (label && label.includes(want)) {
      (row.querySelector('div[role="gridcell"]') || row).click();
      return {found: true, name: (titled
        ? titled.getAttribute('title') : label).slice(0, 80)};
    }
  }
  return {found: false};
})(%s)
"""

_CHAT_OPEN_JS = """
(() => {
  const box = document.querySelector(
    'footer div[contenteditable="true"][data-tab="10"], '
    + 'footer [aria-label="Type a message"], '
    + 'footer div[contenteditable="true"][data-lexical-editor="true"], '
    + 'footer div[contenteditable="true"]');
  if (!box) return {open: false};
  box.focus();
  return {open: true};
})()
"""

_BOX_TEXT_JS = """
(() => {
  const box = document.querySelector(
    'footer div[contenteditable="true"][data-tab="10"], '
    + 'footer [aria-label="Type a message"], '
    + 'footer div[contenteditable="true"][data-lexical-editor="true"], '
    + 'footer div[contenteditable="true"]');
  return box ? (box.innerText || '') : '';
})()
"""

_CLEAR_BOX_JS = """
(() => {
  const box = document.querySelector(
    'footer div[contenteditable="true"][data-tab="10"], '
    + 'footer [aria-label="Type a message"], '
    + 'footer div[contenteditable="true"][data-lexical-editor="true"], '
    + 'footer div[contenteditable="true"]');
  if (!box) return false;
  box.focus();
  document.execCommand('selectAll', false, null);
  document.execCommand('delete', false, null);
  return true;
})()
"""

_SEND_JS = """
(() => {
  const btn = document.querySelector(
    'button[aria-label="Send"], span[data-icon="send"], '
    + 'button[data-testid="compose-btn-send"]');
  const target = btn && btn.closest('button') ? btn.closest('button') : btn;
  if (target) { target.click(); return {sent: true, how: 'button'}; }
  return {sent: false};
})()
"""

_VERIFY_JS = """
((snippet) => {
  const bubbles = document.querySelectorAll(
    '.message-out, [data-testid="msg-container"] .msg-container');
  const nodes = bubbles.length ? bubbles
    : document.querySelectorAll('div.message-out');
  for (let i = nodes.length - 1; i >= 0; i--) {
    if ((nodes[i].innerText || '').includes(snippet)) return true;
  }
  return false;
})(%s)
"""


class WhatsAppMessenger:
    def __init__(self, browser):
        self._browser = browser  # BrowserAgent (owns the CDP tabs)
        self._page = None

    async def _ensure_page(self):
        if self._page is not None and await self._page.alive():
            return self._page
        self._page = await self._browser.open_tab(WA_URL, WA_PART)
        return self._page

    async def _wait_state(self, page, seconds=10.0):
        import time
        deadline = time.monotonic() + seconds
        state = "loading"
        while time.monotonic() < deadline:
            try:
                out = await page.eval(_STATE_JS) or {}
                state = out.get("state", "loading")
            except Exception:  # noqa: BLE001 - page still loading
                state = "loading"
            if state in ("logged_in", "qr"):
                return state
            await asyncio.sleep(0.7)
        return state

    async def send_message(self, contact, message, confirm=None):
        contact = " ".join((contact or "").split())
        message = " ".join((message or "").split())
        if not contact or not message:
            return {"status": "error",
                    "message": "contact ka naam ya message khaali hai"}
        page = await self._ensure_page()
        state = await self._wait_state(page)
        if state == "qr":
            return {"status": "needs_login",
                    "message": "WhatsApp abhi login nahi hai. Golu ko "
                               "bolo: JARVIS wale browser me QR code "
                               "dikh raha hai - phone ke WhatsApp me "
                               "Settings > Linked Devices > Link a "
                               "Device se scan kar dein. Ye ek baar "
                               "hi karna hai, phir hamesha chalega."}
        if state != "logged_in":
            return {"status": "error",
                    "message": "WhatsApp Web khul nahi paya - browser "
                               "window me dekhna padega"}

        focused = await page.eval(_FOCUS_SEARCH_JS) or {}
        if not focused.get("ok"):
            return {"status": "error",
                    "message": "WhatsApp ka search box nahi mila"}
        await page.call("Input.insertText", text=contact)
        await asyncio.sleep(1.4)
        found = await page.eval(_FIND_CHAT_JS % json.dumps(
            contact.lower())) or {}
        if not found.get("found"):
            return {"status": "error",
                    "message": f"'{contact}' naam ki chat WhatsApp "
                               "par nahi mili - naam check karo"}
        await asyncio.sleep(1.0)
        opened = await page.eval(_CHAT_OPEN_JS) or {}
        if not opened.get("open"):
            return {"status": "error",
                    "message": "chat khuli par message likhne ki "
                               "jagah nahi mili"}

        await page.call("Input.insertText", text=message)
        await asyncio.sleep(0.4)
        typed = await page.eval(_BOX_TEXT_JS) or ""
        if message[:24].lower() not in str(typed).lower():
            await page.eval(_CLEAR_BOX_JS)
            return {"status": "error",
                    "message": "message box me sahi text nahi gaya - "
                               "kuch bheja NAHI gaya"}

        # His rulebook, enforced: the exact contact + exact text
        # must be approved (the Haan/Nahi card) before anything is
        # sent. No approver wired = never send.
        approved = False
        if confirm is not None:
            approved = bool(await confirm(
                f"{contact} ko WhatsApp par ye message bheju?\n"
                f"\"{message}\""))
        if not approved:
            await page.eval(_CLEAR_BOX_JS)
            return {"status": "cancelled",
                    "message": "message NAHI bheja - confirmation "
                               "nahi mili; likha hua text hata diya"}

        sent = await page.eval(_SEND_JS) or {}
        if not sent.get("sent"):
            # Fallback: Enter key sends on WhatsApp Web.
            await page.call("Input.dispatchKeyEvent",
                            type="keyDown", key="Enter",
                            windowsVirtualKeyCode=13)
            await page.call("Input.dispatchKeyEvent",
                            type="keyUp", key="Enter",
                            windowsVirtualKeyCode=13)
            sent = {"sent": True, "how": "enter"}
        await asyncio.sleep(1.0)
        verified = bool(await page.eval(
            _VERIFY_JS % json.dumps(message[:30])) or False)
        return {"status": "done", "contact": found.get("name") or contact,
                "sent_via": sent.get("how"), "verified": verified,
                "note": "verified True ho tabhi 'message gaya' "
                        "pakka bolo; False ho to kehna bhej diya "
                        "hai, chat me ek nazar dekh lena"}
