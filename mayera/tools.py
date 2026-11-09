"""MAYERA - voice tools (Gemini function calling).

MAYERA can act, not just talk. Declared tools:

  * remember_this(content)  - save something to long-term memory
  * forget_memory(query)    - delete memories matching a topic
  * get_current_time()      - the user's local date/time
  * open_website(url)       - open a web page in the user's browser
                              (http/https only, on the user's own PC)

Plus Google Search grounding is declared in the Live config itself
(see gemini_live.py), so MAYERA can look up fresh information.

The executor is plain Python and fully unit-testable: every function
returns a JSON-able dict that is reported back to the model.
"""

import datetime
import re
import webbrowser

from google.genai import types


def function_declarations():
    return [
        types.FunctionDeclaration(
            name="remember_this",
            description=(
                "Save an important fact, preference, plan or decision about "
                "the user to long-term memory, so you remember it in future "
                "conversations. Use when the user says 'remember this', "
                "'yaad rakho', or shares something clearly worth keeping."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "content": types.Schema(
                        type=types.Type.STRING,
                        description="The fact to remember, in one clear sentence.",
                    )
                },
                required=["content"],
            ),
        ),
        types.FunctionDeclaration(
            name="forget_memory",
            description=(
                "Delete saved memories about a topic. Use when the user "
                "says 'forget this' or 'bhool jao' about something."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description="Topic/keyword of the memory to delete.",
                    )
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="get_current_time",
            description="Get the current local date and time on the user's PC.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="open_website",
            description=(
                "Open a website in the user's default browser, e.g. when "
                "the user says 'open YouTube' or 'Chrome kholo' with a site. "
                "Give a domain like 'youtube.com' or a full https URL."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "url": types.Schema(
                        type=types.Type.STRING,
                        description="Domain or full URL to open.",
                    )
                },
                required=["url"],
            ),
        ),
    ]


_URL_OK = re.compile(r"^(https?://)?[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(/\S*)?$")


class ToolExecutor:
    def __init__(self, store, opener=None):
        self._store = store
        self._opener = opener or webbrowser.open

    async def execute(self, name, args):
        args = args or {}
        try:
            if name == "remember_this":
                return self._remember(args.get("content", ""))
            if name == "forget_memory":
                return self._forget(args.get("query", ""))
            if name == "get_current_time":
                now = datetime.datetime.now()
                return {
                    "status": "ok",
                    "datetime": now.strftime("%A, %d %B %Y, %I:%M %p"),
                }
            if name == "open_website":
                return self._open(args.get("url", ""))
            return {"status": "error", "message": f"unknown tool {name}"}
        except Exception as exc:  # noqa: BLE001 - reported to the model
            return {"status": "error", "message": exc.__class__.__name__}

    # ------------------------------------------------------------------
    def _remember(self, content):
        if not self._store.memory_enabled():
            return {"status": "disabled",
                    "message": "Memory is switched off in settings."}
        result = self._store.add_memory(content, source="voice")
        if result == "refused_secret":
            return {"status": "refused",
                    "message": "Secrets and passwords are never saved."}
        if result is None:
            return {"status": "error", "message": "empty content"}
        return {"status": "saved", "id": result}

    def _forget(self, query):
        count = self._store.delete_matching(query)
        return {"status": "deleted", "count": count}

    def _open(self, url):
        url = (url or "").strip()
        if not url or not _URL_OK.match(url):
            return {"status": "error", "message": "invalid url"}
        if not url.startswith(("http://", "https://")):
            url = "https://" + url
        self._opener(url)
        return {"status": "opened", "url": url}
