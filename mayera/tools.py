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

import asyncio
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
            name="open_app",
            description=(
                "Open an app on the user's Windows PC. Use when the user "
                "says 'Chrome kholo', 'open Notepad', 'Calculator kholo'. "
                "Known apps: chrome, edge, firefox, notepad, calculator, "
                "paint, explorer (files), wordpad, task manager, settings, "
                "control panel, snipping tool, camera."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "app": types.Schema(
                        type=types.Type.STRING,
                        description="The app name the user asked for.",
                    )
                },
                required=["app"],
            ),
        ),
        types.FunctionDeclaration(
            name="close_app",
            description=(
                "Close an app on the user's PC ('Notepad band karo'). "
                "Same app names as open_app, except explorer/files can "
                "never be closed. Never close apps the user did not name."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "app": types.Schema(
                        type=types.Type.STRING,
                        description="The app name the user asked to close.",
                    )
                },
                required=["app"],
            ),
        ),
        types.FunctionDeclaration(
            name="set_volume",
            description=(
                "Change the PC volume: action 'up' (awaz badhao), 'down' "
                "(awaz kam karo) or 'mute' (awaz band). steps = how many "
                "volume steps, usually 3; use more when he says 'bahut "
                "badhao' (e.g. 8)."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "action": types.Schema(
                        type=types.Type.STRING,
                        description="'up', 'down' or 'mute'.",
                    ),
                    "steps": types.Schema(
                        type=types.Type.INTEGER,
                        description="Volume steps, 1-20. Default 3.",
                    ),
                },
                required=["action"],
            ),
        ),
        types.FunctionDeclaration(
            name="type_text",
            description=(
                "Type text the user dictates into a window on his PC "
                "(e.g. he opened Notepad and says 'likho: ...'). Pass "
                "the exact text. window_title names the target window "
                "(e.g. 'Notepad'): that window is focused FIRST, and "
                "if it cannot be focused the text is NOT typed at all "
                "(an error comes back) - so text can never land in "
                "the wrong window. For Notepad, always pass "
                "window_title='Notepad'."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "text": types.Schema(
                        type=types.Type.STRING,
                        description="The exact text to type.",
                    ),
                    "window_title": types.Schema(
                        type=types.Type.STRING,
                        description="Target window title, e.g. "
                                    "'Notepad'. Omit only when typing "
                                    "into whatever window is in front.",
                    ),
                },
                required=["text"],
            ),
        ),
        types.FunctionDeclaration(
            name="take_screenshot",
            description=(
                "Take a screenshot of the user's PC screen. It is saved "
                "in his Pictures folder and opened for him. Use when he "
                "says 'screenshot lo'."
            ),
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="mouse_move",
            description=(
                "Move the mouse pointer on his screen by voice: "
                "direction up/down/left/right (percent of the screen, "
                "default 20) or 'center'. Use when he says 'mouse upar "
                "le jao', 'thoda right karo', 'beech me le jao'."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "direction": types.Schema(
                        type=types.Type.STRING,
                        description="'up', 'down', 'left', 'right' or 'center'.",
                    ),
                    "percent": types.Schema(
                        type=types.Type.INTEGER,
                        description="How far, percent of screen. Small "
                                    "adjustment 5-10, big move 40-60. Default 20.",
                    ),
                },
                required=["direction"],
            ),
        ),
        types.FunctionDeclaration(
            name="mouse_click",
            description=(
                "Click the mouse at its current position. button 'left' "
                "(default) or 'right'; double=true for a double click "
                "('double click karo', 'video par click karo' after "
                "moving the mouse onto it)."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "button": types.Schema(
                        type=types.Type.STRING,
                        description="'left' or 'right'.",
                    ),
                    "double": types.Schema(
                        type=types.Type.BOOLEAN,
                        description="True for double click.",
                    ),
                },
            ),
        ),
        types.FunctionDeclaration(
            name="mouse_scroll",
            description=(
                "Scroll the page under the mouse: direction 'down' "
                "('neeche karo/scroll karo') or 'up', amount 1-20 "
                "(default 3; 'bahut neeche' = 10+)."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "direction": types.Schema(
                        type=types.Type.STRING,
                        description="'up' or 'down'.",
                    ),
                    "amount": types.Schema(
                        type=types.Type.INTEGER,
                        description="Scroll amount 1-20. Default 3.",
                    ),
                },
                required=["direction"],
            ),
        ),
        types.FunctionDeclaration(
            name="click",
            description=(
                "Move the mouse to an exact screen point (x, y in "
                "pixels) and click there. Use ONLY with coordinates "
                "you got from look_at_screen - never guess a point. "
                "button 'left' (default) or 'right'; double=true for "
                "a double click."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "x": types.Schema(
                        type=types.Type.INTEGER,
                        description="Horizontal pixel position.",
                    ),
                    "y": types.Schema(
                        type=types.Type.INTEGER,
                        description="Vertical pixel position.",
                    ),
                    "button": types.Schema(
                        type=types.Type.STRING,
                        description="'left' or 'right'.",
                    ),
                    "double": types.Schema(
                        type=types.Type.BOOLEAN,
                        description="True for a double click.",
                    ),
                },
                required=["x", "y"],
            ),
        ),
        types.FunctionDeclaration(
            name="scroll",
            description=(
                "Scroll the page under the mouse by a signed amount: "
                "positive scrolls DOWN, negative scrolls UP "
                "(1-20 steps, e.g. 5 = a bit down, -5 = a bit up)."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "amount": types.Schema(
                        type=types.Type.INTEGER,
                        description="Signed scroll amount, -20 to 20.",
                    )
                },
                required=["amount"],
            ),
        ),
        types.FunctionDeclaration(
            name="press_key",
            description=(
                "Press a keyboard key. Keys: enter, space, esc, tab, "
                "backspace, arrow keys (up/down/left/right). On YouTube "
                "these mean: k = play/pause ('pause karo'/'chalao'), "
                "f = fullscreen, m = mute, j = 10s peeche, l = 10s aage, "
                "space = play/pause too."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "key": types.Schema(
                        type=types.Type.STRING,
                        description="The key name, e.g. 'k', 'f', 'enter'.",
                    )
                },
                required=["key"],
            ),
        ),
        types.FunctionDeclaration(
            name="youtube_search",
            description=(
                "Search YouTube and list the top 5 videos (number + "
                "title) WITHOUT playing, so the user can choose. Use "
                "when he asks 'kaun kaun si videos hain' or seems to "
                "want a choice. Then call youtube_play with the same "
                "query and the number he picks ('dusri wali')."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description="What to search on YouTube.",
                    )
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="youtube_play",
            description=(
                "Play a YouTube video in his browser right away. Give "
                "the video/song name as query; number = which search "
                "result (1 = pehli/top, default 1). Use when he names "
                "a video or song ('Arijit ka gana chalao', 'Hanuman "
                "Chalisa lagao') or picks a number from a list you "
                "read out."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description="The video/song name to search.",
                    ),
                    "number": types.Schema(
                        type=types.Type.INTEGER,
                        description="Which result to play, 1-5. Default 1.",
                    ),
                },
                required=["query"],
            ),
        ),
        types.FunctionDeclaration(
            name="look_at_screen",
            description=(
                "LOOK at his PC screen yourself and get a short "
                "description of what is on it. Use when he asks 'main "
                "kya kar raha hu', 'ye kya hai', 'ye error kya hai', "
                "'screen par kya hai', 'padho kya likha hai' - and to "
                "CHECK the result after opening an app, typing, or "
                "before clicking (never click blindly). question = "
                "what he wants to know about the screen, if specific. "
                "Answer ONLY from the returned description; if it "
                "says something is not visible, say so honestly. "
                "Sensitive things (passwords, OTPs) are deliberately "
                "never described - do not ask for them."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "question": types.Schema(
                        type=types.Type.STRING,
                        description="What he wants to know about the "
                                    "screen, e.g. 'ye error kya hai'. "
                                    "Empty = general description.",
                    )
                },
            ),
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
    def __init__(self, store, opener=None, pc=None, yt=None, vision=None):
        self._store = store
        self._opener = opener or webbrowser.open
        self._pc = pc  # PcController (v3.1 PC Control pack) or None
        self._yt = yt  # YoutubePlayer (v3.4) or None
        self._vision = vision  # ScreenVision (v3.12) or None

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
            if name in ("open_app", "close_app", "set_volume",
                        "type_text", "take_screenshot", "mouse_move",
                        "mouse_click", "mouse_scroll", "press_key",
                        "click", "scroll"):
                # PC actions can block briefly (process start, a
                # PowerShell screenshot) - keep them off the event
                # loop so live audio never stalls.
                return await asyncio.to_thread(self._pc_action, name, args)
            if name in ("youtube_search", "youtube_play"):
                # A web fetch can take a second or two - same rule.
                return await asyncio.to_thread(self._yt_action, name, args)
            if name == "look_at_screen":
                # Capture + a vision-model call takes seconds - it
                # must never stall live audio either (v3.12).
                return await asyncio.to_thread(self._vision_action, args)
            if name == "open_website":
                # webbrowser.open() blocks; run it off the event loop
                # so it can never stall live audio forwarding (v3.0).
                return await asyncio.to_thread(self._open, args.get("url", ""))
            return {"status": "error", "message": f"unknown tool {name}"}
        except Exception as exc:  # noqa: BLE001 - reported to the model
            return {"status": "error", "message": exc.__class__.__name__}

    # ------------------------------------------------------------------
    def _pc_action(self, name, args):
        if self._pc is None:
            return {"status": "error", "message": "pc control unavailable"}
        if name == "open_app":
            return self._pc.open_app(args.get("app", ""))
        if name == "close_app":
            return self._pc.close_app(args.get("app", ""))
        if name == "set_volume":
            return self._pc.set_volume(args.get("action", ""),
                                       args.get("steps", 3))
        if name == "type_text":
            return self._pc.type_text(args.get("text", ""),
                                      args.get("window_title") or None)
        if name == "click":
            return self._pc.click(args.get("x", -1), args.get("y", -1),
                                  args.get("button", "left"),
                                  args.get("double", False))
        if name == "scroll":
            return self._pc.scroll(args.get("amount", 0))
        if name == "mouse_move":
            return self._pc.mouse_move(args.get("direction", ""),
                                       args.get("percent", 20))
        if name == "mouse_click":
            return self._pc.mouse_click(args.get("button", "left"),
                                        args.get("double", False))
        if name == "mouse_scroll":
            return self._pc.mouse_scroll(args.get("direction", "down"),
                                         args.get("amount", 3))
        if name == "press_key":
            return self._pc.press_key(args.get("key", ""))
        return self._pc.take_screenshot()

    def _vision_action(self, args):
        if self._vision is None:
            return {"status": "error", "message": "screen vision unavailable"}
        return self._vision.look(args.get("question", ""))

    def _yt_action(self, name, args):
        if self._yt is None:
            return {"status": "error", "message": "youtube unavailable"}
        if name == "youtube_search":
            return self._yt.search(args.get("query", ""))
        return self._yt.play(args.get("query", ""), args.get("number", 1))

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
