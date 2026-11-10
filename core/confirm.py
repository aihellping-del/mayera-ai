"""JARVIS - real confirmation gate (concept ported from Mark LVI's
core/confirm.py by FatihMakes, CC BY-NC 4.0).

The rule from Mark: for genuinely irreversible actions, the token
must be issued by the UI, not by the model. The model can ASK, but
only the user's own button press in the JARVIS page can APPROVE.

Flow: a tool calls gate.ask(question) -> main.py shows a Haan/Nahi
card in the page over the WebSocket -> the user taps -> the page
POSTs /api/confirm -> the waiting tool wakes with True/False.
No answer within the timeout counts as NO.
"""

import asyncio
import itertools


class ConfirmGate:
    def __init__(self):
        self._pending = {}  # id -> asyncio.Future
        self._ids = itertools.count(1)
        self.notify = None  # async callable(cid, question) set by main

    async def ask(self, question, timeout=60.0):
        if self.notify is None:
            return False  # no UI attached: never self-approve
        cid = f"c{next(self._ids)}"
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        self._pending[cid] = future
        try:
            await self.notify(cid, question)
            return bool(await asyncio.wait_for(future, timeout))
        except (asyncio.TimeoutError, asyncio.CancelledError):
            return False
        finally:
            self._pending.pop(cid, None)

    def resolve(self, cid, approved):
        future = self._pending.get(cid)
        if future is not None and not future.done():
            future.set_result(bool(approved))
            return True
        return False

    def pending_count(self):
        return len(self._pending)
