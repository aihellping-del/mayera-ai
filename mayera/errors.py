"""MAYERA - friendly error handling.

Every failure the user can hit (bad key, no network, unsupported model,
microphone problems...) is converted into a short, understandable message.
Raw tracebacks stay in the server console for debugging; the UI only ever
shows the friendly text.
"""


class MayeraError(Exception):
    """An error whose message is safe and friendly for the UI."""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def friendly_error(exc):
    """Map any exception to a (code, friendly message) pair."""
    text = str(exc) or exc.__class__.__name__
    low = text.lower()

    if isinstance(exc, MayeraError):
        return exc.code, exc.message

    # --- Gemini authentication / permission -------------------------------
    if (any(s in low for s in ("api key", "api_key", "unauthenticated",
                                "401", "403", "permission_denied"))
            or ("invalid argument" in low and "key" in low)):
        return ("auth_error",
                "Gemini API key galat hai ya kaam nahi kar rahi. "
                "START_MAYERA.bat dobara chalakar sahi key daalein.")

    # --- Model problems ----------------------------------------------------
    if (any(s in low for s in ("not_found", "not found", "404",
                                "unsupported model"))
            or ("model" in low and "not" in low)):
        return ("model_error",
                "Ye Gemini model ab uplabdh nahi hai. MAYERA doosra "
                "model khud try karegi.")

    # --- Network ------------------------------------------------------------
    if any(s in low for s in ("connect", "network", "timeout", "dns",
                              "ssl", "unreachable", "reset by peer")):
        return ("network_error",
                "Internet connection me dikkat hai. MAYERA dobara "
                "connect karne ki koshish kar rahi hai...")

    # --- Quota ---------------------------------------------------------------
    if "429" in low or "quota" in low or "resource_exhausted" in low:
        return ("quota_error",
                "Gemini ki free limit khatm ho gayi hai (quota). "
                "Kuch der baad fir try karein.")

    # --- WebSocket / session --------------------------------------------------
    if "websocket" in low or "1011" in low or "1006" in low:
        return ("session_error",
                "Voice session toot gaya. MAYERA dobara connect "
                "kar rahi hai...")

    return ("unknown_error",
            "Kuch gadbad ho gayi (" + exc.__class__.__name__ + "). "
            "MAYERA sambhalne ki koshish kar rahi hai...")
