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
    decls = [
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
            name="recall_memory",
            description=(
                "Search ALL of the user's stored memories by keyword "
                "and bring back matches. Use when he refers to "
                "something older ('maine tumhe pehle bataya tha...', "
                "'meri pasand kya hai?') or when a fact you need is "
                "not in your current context - your prompt only "
                "carries the newest memories, this searches "
                "everything, so never say 'mujhe nahi pata' about his "
                "stored facts without recalling first."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "query": types.Schema(
                        type=types.Type.STRING,
                        description="Keywords to search his memories for.",
                    )
                },
                required=["query"],
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
            name="list_files",
            description=(
                "List files and folders at a place ('desktop par kya "
                "hai?'). Path can be a friendly name (desktop, "
                "documents, downloads, pictures, music, videos, home) "
                "or a folder path inside the user's home."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"path": types.Schema(
                    type=types.Type.STRING,
                    description="Friendly place name or folder path.")},
                required=["path"]),
        ),
        types.FunctionDeclaration(
            name="create_folder",
            description="Create a new folder at a friendly place.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "path": types.Schema(type=types.Type.STRING,
                                         description="Friendly place, e.g. desktop."),
                    "name": types.Schema(type=types.Type.STRING,
                                         description="New folder name.")},
                required=["path", "name"]),
        ),
        types.FunctionDeclaration(
            name="create_file",
            description=(
                "Create a new text file with optional starting "
                "content. Fails honestly if the name already exists."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "path": types.Schema(type=types.Type.STRING,
                                         description="Friendly place, e.g. documents."),
                    "name": types.Schema(type=types.Type.STRING,
                                         description="File name with extension, e.g. note.txt."),
                    "content": types.Schema(type=types.Type.STRING,
                                            description="Starting text (optional).")},
                required=["path", "name"]),
        ),
        types.FunctionDeclaration(
            name="write_file",
            description=(
                "Write text into an existing or new file (overwrite, "
                "or append=true to add at the end). The previous "
                "content is kept on the undo stack."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "path": types.Schema(type=types.Type.STRING,
                                         description="Friendly place."),
                    "name": types.Schema(type=types.Type.STRING,
                                         description="File name."),
                    "content": types.Schema(type=types.Type.STRING,
                                            description="Text to write."),
                    "append": types.Schema(type=types.Type.BOOLEAN,
                                           description="Add at end instead of overwriting.")},
                required=["path", "name", "content"]),
        ),
        types.FunctionDeclaration(
            name="read_file",
            description=(
                "Read a text file's contents (.txt/.md/.log/.json/"
                ".csv) so you can summarise or discuss it."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "path": types.Schema(type=types.Type.STRING,
                                         description="Friendly place."),
                    "name": types.Schema(type=types.Type.STRING,
                                         description="File name.")},
                required=["path", "name"]),
        ),
        types.FunctionDeclaration(
            name="move_file",
            description="Move a file to another friendly place.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "path": types.Schema(type=types.Type.STRING,
                                         description="Where the file is now."),
                    "name": types.Schema(type=types.Type.STRING,
                                         description="File name."),
                    "destination": types.Schema(type=types.Type.STRING,
                                                description="Friendly destination place.")},
                required=["path", "name", "destination"]),
        ),
        types.FunctionDeclaration(
            name="copy_file",
            description="Copy a file to another friendly place.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "path": types.Schema(type=types.Type.STRING,
                                         description="Where the file is now."),
                    "name": types.Schema(type=types.Type.STRING,
                                         description="File name."),
                    "destination": types.Schema(type=types.Type.STRING,
                                                description="Friendly destination place.")},
                required=["path", "name", "destination"]),
        ),
        types.FunctionDeclaration(
            name="rename_file",
            description="Rename a file or folder.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "path": types.Schema(type=types.Type.STRING,
                                         description="Friendly place it is in."),
                    "name": types.Schema(type=types.Type.STRING,
                                         description="Current name."),
                    "new_name": types.Schema(type=types.Type.STRING,
                                             description="New name.")},
                required=["path", "name", "new_name"]),
        ),
        types.FunctionDeclaration(
            name="trash_file",
            description=(
                "Move a file to the recoverable trash (.jarvis_trash "
                "in home). This ALWAYS asks the user first with an "
                "on-screen Haan/Nahi card that only the user can tap "
                "- you cannot approve it yourself, and a timeout "
                "means NO. Use for 'delete kar do' requests."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "path": types.Schema(type=types.Type.STRING,
                                         description="Friendly place."),
                    "name": types.Schema(type=types.Type.STRING,
                                         description="File name.")},
                required=["path", "name"]),
        ),
        types.FunctionDeclaration(
            name="find_files",
            description="Find files by part of their name under a place.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "name_part": types.Schema(type=types.Type.STRING,
                                              description="Part of the file name to search."),
                    "path": types.Schema(type=types.Type.STRING,
                                         description="Friendly place to search under.")},
                required=["name_part"]),
        ),
        types.FunctionDeclaration(
            name="undo_last_action",
            description=(
                "Undo the last reversible change JARVIS made (file "
                "move/rename/create/write/trash, when the user says "
                "'undo kar do', 'galti ho gayi', 'wapas kar do')."
            ),
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="get_weather",
            description=(
                "Live weather for a city ('mausam kaisa hai?'). "
                "Returns current temperature, feels-like, humidity, "
                "wind, condition and today's high/low."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"city": types.Schema(
                    type=types.Type.STRING,
                    description="City name, e.g. Patna, Delhi.")},
                required=["city"]),
        ),
        types.FunctionDeclaration(
            name="set_reminder",
            description=(
                "Set a reminder JARVIS will SPEAK aloud when due "
                "(while JARVIS is running). Give minutes_from_now OR "
                "at_time ('18:30'). Confirm the time back to the user."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={
                    "text": types.Schema(type=types.Type.STRING,
                                         description="What to remind about."),
                    "minutes_from_now": types.Schema(type=types.Type.INTEGER,
                                                     description="Minutes from now (optional)."),
                    "at_time": types.Schema(type=types.Type.STRING,
                                            description="Clock time today/tomorrow, 'HH:MM' (optional).")},
                required=["text"]),
        ),
        types.FunctionDeclaration(
            name="list_reminders",
            description="List the user's pending reminders.",
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="cancel_reminder",
            description="Cancel pending reminders matching some words.",
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"query": types.Schema(
                    type=types.Type.STRING,
                    description="Words matching the reminder text.")},
                required=["query"]),
        ),
        types.FunctionDeclaration(
            name="get_system_info",
            description=(
                "The computer's health: OS, CPU cores, disk space, "
                "and on Windows the battery percent and RAM use "
                "('battery kitni hai?', 'system kaisa hai?')."
            ),
            parameters=types.Schema(type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="browser_search",
            description=(
                "Search the web in JARVIS's OWN personal browser "
                "window (the user watches it happen) and list the "
                "top results with numbers. Use when the user asks "
                "to search/research something on the internet."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"query": types.Schema(
                    type=types.Type.STRING,
                    description="What to search for.")},
                required=["query"]),
        ),
        types.FunctionDeclaration(
            name="browser_research",
            description=(
                "Full research in JARVIS's own browser: search, open "
                "the top result and read its text back. Then speak a "
                "short summary in your own words. Use for 'research "
                "karo', 'iske baare me pata karo' type requests."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"query": types.Schema(
                    type=types.Type.STRING,
                    description="Topic to research.")},
                required=["query"]),
        ),
        types.FunctionDeclaration(
            name="browser_open_result",
            description=(
                "Open result number N from the last browser_search "
                "list in JARVIS's browser ('dusra wala kholo')."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"number": types.Schema(
                    type=types.Type.INTEGER,
                    description="Result number from the last search.")},
                required=["number"]),
        ),
        types.FunctionDeclaration(
            name="browser_click",
            description=(
                "Click a visible link or button on the current page "
                "of JARVIS's browser BY ITS TEXT ('Wikipedia par "
                "click karo'). Buttons about money/sending/deleting "
                "first ask the user on a confirmation card by "
                "themselves - never argue with a 'cancelled' result."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"text": types.Schema(
                    type=types.Type.STRING,
                    description="Text written on the link/button.")},
                required=["text"]),
        ),
        types.FunctionDeclaration(
            name="browser_read_page",
            description=(
                "Read the text of the page currently open in "
                "JARVIS's browser, e.g. to summarise it aloud."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="browser_back",
            description="Go back to the previous page in JARVIS's browser.",
            parameters=types.Schema(
                type=types.Type.OBJECT, properties={}),
        ),
        types.FunctionDeclaration(
            name="click_on_screen",
            description=(
                "Look at the user's screen, FIND the named element "
                "(link, button, tab - in his own Chrome or any app) "
                "and CLICK it. Use when he says 'mere Chrome me "
                "Download par click karo' or names something visible "
                "on screen. Money/send/delete-looking labels first "
                "ask on a confirmation card by themselves."
            ),
            parameters=types.Schema(
                type=types.Type.OBJECT,
                properties={"text": types.Schema(
                    type=types.Type.STRING,
                    description="Text/label of the element to click.")},
                required=["text"]),
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
    # Self-describing plugins (v3.15): whatever skills were dropped
    # into plugins/ are declared alongside the built-in tools.
    try:
        from plugins import loader as plugins_loader
        plugin_decls, _handlers = plugins_loader.discover()
        decls.extend(plugin_decls)
    except Exception:  # noqa: BLE001 - plugins never break the built-ins
        pass
    return decls


_URL_OK = re.compile(r"^(https?://)?[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(/\S*)?$")

# v3.17 (Mark LVI port pack)
_FILE_TOOLS = {"list_files", "create_folder", "create_file",
               "write_file", "read_file", "move_file", "copy_file",
               "rename_file", "trash_file", "find_files"}

# v3.20: JARVIS's own personal browser
_BROWSER_TOOLS = {"browser_search", "browser_research",
                  "browser_open_result", "browser_click",
                  "browser_read_page", "browser_back"}


class ToolExecutor:
    def __init__(self, store, opener=None, pc=None, yt=None, vision=None,
                 plugins=None, files=None, confirm=None, browser=None):
        self._store = store
        self._opener = opener or webbrowser.open
        self._pc = pc  # PcController (v3.1 PC Control pack) or None
        self._yt = yt  # YoutubePlayer (v3.4) or None
        self._vision = vision  # ScreenVision (v3.12) or None
        self._files = files  # FileOps (v3.17) or None
        self._confirm = confirm  # ConfirmGate (v3.17) or None
        self._browser = browser  # BrowserAgent (v3.20) or None
        if plugins is None:
            try:
                from plugins import loader as plugins_loader
                _decls, plugins = plugins_loader.discover()
            except Exception:  # noqa: BLE001
                plugins = {}
        self._plugins = plugins or {}

    async def execute(self, name, args):
        args = args or {}
        try:
            if name == "remember_this":
                return self._remember(args.get("content", ""))
            if name == "recall_memory":
                return self._recall(args.get("query", ""))
            if name in self._plugins:
                # Plugin handlers are plain sync Python - run them
                # in a thread so a slow plugin never stalls audio.
                return await asyncio.to_thread(
                    self._run_plugin, name, args)
            if name == "forget_memory":
                return self._forget(args.get("query", ""))
            if name in _BROWSER_TOOLS:
                # The browser agent is async (DevTools Protocol) -
                # await it directly; tool batches already run as
                # background tasks, so a slow page never stalls audio.
                return await self._browser_action(name, args)
            if name in _FILE_TOOLS or name in ("get_weather",
                                               "get_system_info",
                                               "set_reminder",
                                               "list_reminders",
                                               "cancel_reminder",
                                               "undo_last_action"):
                return await self._v317(name, args)
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
            if name == "click_on_screen":
                # See + locate + click (v3.21): also seconds of
                # vision work - same off-the-loop rule.
                return await asyncio.to_thread(
                    self._screen_click_action, args)
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

    def _screen_click_action(self, args):
        """click_on_screen (v3.21): the vision model points at the
        named element on HIS screen (his Chrome, any app), the
        risky-label gate runs first for money/send/delete labels,
        then the real mouse clicks exactly there."""
        if self._vision is None or self._pc is None:
            return {"status": "error",
                    "message": "screen click unavailable"}
        text = (args.get("text") or "").strip()
        if not text:
            return {"status": "error",
                    "message": "kis par click karna hai, ye nahi bataya"}
        from actions.browser_agent import is_risky_label
        if is_risky_label(text):
            approved = False
            if self._confirm is not None:
                approved = bool(self._confirm.ask(
                    f"Screen par '{text}' par click karu? Ye paisa/"
                    "send/delete wala button lagta hai."))
            if not approved:
                return {"status": "cancelled",
                        "message": f"'{text}' par click NAHI kiya - "
                                   "confirmation nahi mili"}
        located = self._vision.locate(text)
        if located.get("status") != "ok":
            return located
        clicked = self._pc.click(located["x"], located["y"])
        if clicked.get("status") not in ("ok", "clicked", "done"):
            return clicked
        return {"status": "done", "clicked": text,
                "at": [located["x"], located["y"]],
                "note": "screen par dekh kar wahi element click kiya"}

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

    def _recall(self, query):
        if not self._store.memory_enabled():
            return {"status": "disabled",
                    "message": "Memory is switched off in settings."}
        found = self._store.search_memories(query, limit=8)
        return {"status": "ok", "count": len(found),
                "memories": [m["content"] for m in found]}

    def _run_plugin(self, name, args):
        try:
            result = self._plugins[name](args)
            if isinstance(result, dict):
                return result
            return {"status": "ok", "result": result}
        except Exception as exc:  # noqa: BLE001 - reported to the model
            return {"status": "error",
                    "message": f"plugin {name}: {exc.__class__.__name__}"}

    async def _browser_action(self, name, args):
        if self._browser is None:
            return {"status": "error", "message": "browser unavailable"}
        b = self._browser
        if name == "browser_search":
            return await b.search(args.get("query", ""))
        if name == "browser_research":
            return await b.research(args.get("query", ""))
        if name == "browser_open_result":
            return await b.open_result(args.get("number", 0))
        if name == "browser_read_page":
            return await b.read_page()
        if name == "browser_back":
            return await b.back()
        # browser_click: risky labels go through the same Haan/Nahi
        # gate as file trashing (v3.17) - the gate blocks on a
        # thread, so wrap it for the agent's async confirm callback.
        async def _confirm_cb(question):
            if self._confirm is None:
                return False
            return await asyncio.to_thread(self._confirm.ask, question)

        return await b.click_text(args.get("text", ""),
                                  confirm=_confirm_cb)

    async def _v317(self, name, args):
        """v3.17 port pack routing: file kaam, weather, reminders,
        system info, undo. File ops run in a thread (disk IO)."""
        import datetime as _dt

        from actions import sysinfo as sysinfo_mod
        from actions import weather as weather_mod
        from core import undo as undo_mod

        if name == "get_weather":
            return await asyncio.to_thread(
                weather_mod.get_weather, args.get("city", ""))
        if name == "get_system_info":
            return await asyncio.to_thread(sysinfo_mod.get_system_info)
        if name == "set_reminder":
            text = (args.get("text") or "").strip()
            if not text:
                return {"status": "error", "message": "reminder text chahiye"}
            now = _dt.datetime.now()
            due = None
            mins = args.get("minutes_from_now")
            if isinstance(mins, (int, float)) and mins > 0:
                due = now + _dt.timedelta(minutes=float(mins))
            elif args.get("at_time"):
                try:
                    hh, mm = str(args["at_time"]).split(":")[:2]
                    due = now.replace(hour=int(hh), minute=int(mm),
                                      second=0, microsecond=0)
                    if due <= now:
                        due += _dt.timedelta(days=1)
                except (ValueError, TypeError):
                    return {"status": "error",
                            "message": "time samajh nahi aaya (HH:MM do)"}
            if due is None:
                return {"status": "error",
                        "message": "kab yaad dilana hai, woh nahi mila"}
            rid = self._store.add_reminder(text, due.timestamp())
            return {"status": "done", "verified": True, "id": rid,
                    "due_at": due.strftime("%d %b, %I:%M %p")}
        if name == "list_reminders":
            rows = self._store.list_reminders()
            return {"status": "done", "count": len(rows),
                    "reminders": [
                        {"text": r["text"],
                         "due_at": _dt.datetime.fromtimestamp(
                             r["due_at"]).strftime("%d %b, %I:%M %p")}
                        for r in rows]}
        if name == "cancel_reminder":
            n = self._store.cancel_reminder(args.get("query", ""))
            return {"status": "done", "cancelled": n}
        if name == "undo_last_action":
            entry = undo_mod.pop_undo()
            if entry is None:
                return {"status": "error",
                        "message": "undo karne ke liye kuch nahi hai"}
            if self._files is None:
                return {"status": "error",
                        "message": "file system band hai"}
            return await asyncio.to_thread(
                self._files.execute_undo, entry)
        # file tools
        if self._files is None:
            return {"status": "error", "message": "file system band hai"}
        f = self._files
        if name == "trash_file":
            # Mark's rule: the token comes from the UI, not the
            # model. No gate / no tap = no trash, ever.
            if self._confirm is None:
                return {"status": "error",
                        "message": "confirmation gate band hai"}
            label = f"{args.get('path', '')}/{args.get('name', '')}"
            ok = await self._confirm.ask(
                f"Is file ko trash me bhej du? {label}")
            if not ok:
                return {"status": "cancelled",
                        "message": "user ne Haan nahi bola - trash nahi hua"}
        method = getattr(f, name)
        call_args = {k: v for k, v in args.items()}
        return await asyncio.to_thread(
            lambda: method(**call_args))

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
