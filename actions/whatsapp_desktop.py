"""WhatsApp through the DESKTOP APP already on his PC (v3.27).

The user's correction: 'mere PC me already WhatsApp hai, usko
use nahi karta hai' - the web route (v3.25) opened a second
WhatsApp in JARVIS's browser and ignored the app he already has
installed and logged in. This module drives THAT app instead:
JARVIS opens/focuses it and works like a person would - eyes
(screen vision) find each element, the visible mouse arrow
clicks it, typing goes through the keyboard path, Enter sends.

Same rulebook enforcement as the web route:
  * The exact contact + exact message are approved on the
    Haan/Nahi card BEFORE Enter is ever pressed. No approver or
    a 'no' = the typed text is erased (backspaces) and NOTHING
    is sent.
  * One contact, one dictated message. No bulk machinery.
  * After Enter, the sent text is looked for on screen before
    'done' is claimed as verified.

Every step is eyes-verified, so a changed layout or a still-
loading app fails with a specific reason instead of a wrong
click. This class is synchronous (vision + PC calls are
blocking); the executor runs it on a thread.
"""

import time


class WhatsAppDesktop:
    SEARCH_TARGET = "search box (Search or start new chat)"
    BOX_TARGET = "message box (Type a message)"

    def __init__(self, pc, vision, sleeper=None):
        self._pc = pc
        self._vision = vision
        self._sleep = sleeper or time.sleep

    # -- helpers ---------------------------------------------------
    def _locate(self, target, tries=1):
        """Vision-locate with retries; returns (x, y) or None."""
        for attempt in range(tries):
            out = self._vision.locate(target)
            if out.get("status") == "ok":
                return out["x"], out["y"]
            if attempt + 1 < tries:
                self._sleep(1.2)
        return None

    def _clear_box(self, presses):
        for _ in range(max(1, min(300, presses))):
            self._pc.press_key("backspace")

    # -- the flow --------------------------------------------------
    def send_message(self, contact, message, confirm=None):
        contact = " ".join((contact or "").split())
        message = " ".join((message or "").split())
        if not contact or not message:
            return {"status": "error",
                    "message": "contact ka naam ya message khaali hai"}
        pc = self._pc

        opened = pc.open_app("whatsapp")
        if opened.get("status") == "error":
            return {"status": "needs_app",
                    "message": "WhatsApp app khul nahi paya - "
                               + opened.get("message", "")}
        if not opened.get("focused"):
            if not pc.focus_window("WhatsApp"):
                # The window never came up - the app is most
                # likely not installed/opening; let the caller
                # fall back to the browser route.
                return {"status": "needs_app",
                        "message": "WhatsApp app ki window saamne "
                                   "nahi aayi"}

        point = self._locate(self.SEARCH_TARGET, tries=3)
        if point is None:
            return {"status": "error",
                    "message": "WhatsApp app khula par search box "
                               "nahi dikha - app abhi load ho raha "
                               "ho to ek minute ruk kar phir bolo"}
        pc.click(point[0], point[1])
        typed = pc.type_text(contact, window_title="WhatsApp")
        if typed.get("status") == "error":
            return typed

        point = self._locate(contact, tries=3)
        if point is None:
            return {"status": "error",
                    "message": f"'{contact}' naam ki chat list me "
                               "nahi dikhi - naam bilkul waisa likho "
                               "jaisa WhatsApp me saved hai"}
        pc.click(point[0], point[1])
        self._sleep(0.6)

        point = self._locate(self.BOX_TARGET, tries=3)
        if point is None:
            return {"status": "error",
                    "message": "chat khuli par message likhne ki "
                               "jagah (Type a message) nahi dikhi"}
        pc.click(point[0], point[1])
        typed = pc.type_text(message, window_title="WhatsApp")
        if typed.get("status") == "error":
            return typed

        # Rulebook: the card approves the exact contact + text
        # BEFORE Enter. No approver wired = never send.
        approved = False
        if confirm is not None:
            approved = bool(confirm(
                f"{contact} ko WhatsApp (app) par ye message "
                f"bheju?\n\"{message}\""))
        if not approved:
            self._clear_box(len(message) + 4)
            return {"status": "cancelled",
                    "message": "message NAHI bheja - confirmation "
                               "nahi mili; likha hua text hata diya"}

        pressed = pc.press_key("enter")
        if pressed.get("status") == "error":
            return {"status": "error",
                    "message": "Enter dab nahi paya - message box "
                               "me likha pada hai, khud bhej sakte ho"}
        self._sleep(0.8)
        verified = self._locate(message[:24], tries=1) is not None
        return {"status": "done", "via": "whatsapp_app",
                "contact": contact, "verified": verified,
                "note": "verified True ho tabhi 'message gaya' pakka "
                        "bolo; False ho to kehna bhej diya hai, chat "
                        "me ek nazar dekh lena"}
