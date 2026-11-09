"""MAYERA - proactive conversation watcher.

While a voice session is LIVE, if Golu stays silent for a while, MAYERA
gently starts the conversation herself ("Hey, kya kar rahe ho? Sab theek
hai?"). Honest limits, by design:

  * It only works while the app is running and a session is connected.
    A stopped app never "wakes up" on its own - nothing here pretends
    otherwise.
  * It respects the quiet hours and the on/off setting.
  * It never repeats the same line twice in a row, and it waits at
    least the full inactivity period between two check-ins.

The watcher only decides WHEN to nudge and WHAT kind of check-in to ask
for; MAYERA's own brain (Gemini) phrases the actual words, in context.
"""

import time

CHECK_IN_STYLES = [
    "the user has been quiet for a while. Warmly check in on Golu in one "
    "or two natural sentences - ask what he is doing and if everything "
    "is okay. Be soft, not needy.",

    "the user has been silent for some time. Gently restart the "
    "conversation: refer to the last topic you discussed, and ask if he "
    "wants to continue it or talk about something new.",

    "the user has not spoken for a while. In one natural sentence, "
    "lightly wonder how he is feeling right now and invite him to talk. "
    "Keep it fresh - do not repeat your previous check-in.",

    "a long quiet moment has passed. Say something small, warm and "
    "human - a kind observation or a gentle question - so Golu feels "
    "your company, without pressuring him to reply.",
]


def _parse_hhmm(value, fallback):
    try:
        h, m = value.split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return fallback


def in_quiet_hours(now_localtime, start_s, end_s):
    """True if `now` (a struct_time) falls inside quiet hours."""
    cur = now_localtime.tm_hour * 60 + now_localtime.tm_min
    start = _parse_hhmm(start_s, 23 * 60)
    end = _parse_hhmm(end_s, 7 * 60)
    if start == end:
        return False
    if start < end:
        return start <= cur < end
    return cur >= start or cur < end  # wraps past midnight


class ProactiveWatcher:
    def __init__(self, store):
        self._store = store
        self._last_activity = time.monotonic()
        self._last_nudge = 0.0
        self._style_index = 0

    def mark_activity(self):
        self._last_activity = time.monotonic()

    def reset(self):
        self._last_activity = time.monotonic()
        self._last_nudge = 0.0

    def should_nudge(self, now=None, localtime=None):
        """Pure decision function (unit-testable)."""
        if not self._store.proactive_enabled():
            return False
        now = time.monotonic() if now is None else now
        localtime = time.localtime() if localtime is None else localtime
        if in_quiet_hours(
            localtime,
            self._store.get_setting("quiet_start", "23:00"),
            self._store.get_setting("quiet_end", "07:00"),
        ):
            return False
        idle_for = now - self._last_activity
        needed = self._store.inactivity_seconds()
        if idle_for < needed:
            return False
        if self._last_nudge and (now - self._last_nudge) < needed:
            return False  # never nag twice inside one quiet stretch
        return True

    def next_instruction(self, last_topic=""):
        style = CHECK_IN_STYLES[self._style_index % len(CHECK_IN_STYLES)]
        self._style_index += 1
        topic_hint = (
            f" Your last conversation topic was: {last_topic}." if last_topic else ""
        )
        return (
            "[System note - do not read this aloud: " + style + topic_hint + "]"
        )

    def mark_nudged(self, now=None):
        self._last_nudge = time.monotonic() if now is None else now
        self._last_activity = self._last_nudge
