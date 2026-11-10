"""JARVIS - self-describing plugins (v3.15, user's feature list).

Drop ONE .py file into the `plugins/` folder next to main.py and
JARVIS learns a new skill at the next launch - no other file needs
editing. A plugin file declares:

    TOOL = {
        "name": "roll_dice",
        "description": "Roll a dice when the user asks for a random "
                       "number / dice / toss.",
        # simple form: property -> (type, description)
        "parameters": {"sides": ("integer", "How many sides, default 6")},
        "required": [],          # optional
    }

    def handle(args):
        ...                      # returns a JSON-able dict

or the full parameter form: "parameters": {"type": "object",
"properties": {...}, "required": [...]} as plain JSON-schema dicts.

Discovery runs once (cached). A broken plugin is reported in the
terminal as [plugin] and SKIPPED - it can never stop JARVIS from
starting. Handlers run in a worker thread via the ToolExecutor, so
a slow plugin cannot stall live audio.
"""

import importlib.util
import sys
import threading
from pathlib import Path

from google.genai import types

_TYPE_MAP = {
    "string": types.Type.STRING,
    "integer": types.Type.INTEGER,
    "number": types.Type.NUMBER,
    "boolean": types.Type.BOOLEAN,
}

_cache = {"loaded": False, "declarations": [], "handlers": {}}
_lock = threading.Lock()


def default_plugins_dir():
    return Path(__file__).resolve().parent  # loader lives IN plugins/


def _schema_from_simple(params):
    props = {}
    for name, spec in (params or {}).items():
        if isinstance(spec, (tuple, list)) and len(spec) == 2:
            ptype, desc = spec
        elif isinstance(spec, dict):
            ptype, desc = spec.get("type", "string"), spec.get("description", "")
        else:
            ptype, desc = "string", str(spec)
        props[name] = types.Schema(
            type=_TYPE_MAP.get(str(ptype).lower(), types.Type.STRING),
            description=str(desc))
    return props


def _declaration_from_tool(tool):
    name = str(tool["name"])
    params = tool.get("parameters") or {}
    if isinstance(params, dict) and params.get("type") == "object":
        props = {}
        for pname, pspec in (params.get("properties") or {}).items():
            props[pname] = types.Schema(
                type=_TYPE_MAP.get(str(pspec.get("type", "string")).lower(),
                                   types.Type.STRING),
                description=str(pspec.get("description", "")))
        required = list(params.get("required") or [])
    else:
        props = _schema_from_simple(params)
        required = list(tool.get("required") or [])
    return types.FunctionDeclaration(
        name=name,
        description=str(tool.get("description", "")),
        parameters=types.Schema(
            type=types.Type.OBJECT, properties=props, required=required),
    )


def discover(base_dir=None, force=False):
    """Load plugins once; returns (declarations, handlers dict)."""
    with _lock:
        if _cache["loaded"] and not force:
            return _cache["declarations"], _cache["handlers"]
        declarations, handlers = [], {}
        folder = Path(base_dir) if base_dir else default_plugins_dir()
        if folder.is_dir():
            for path in sorted(folder.glob("*.py")):
                if path.name.startswith("_"):
                    continue
                try:
                    mod_name = f"jarvis_plugin_{path.stem}"
                    spec = importlib.util.spec_from_file_location(
                        mod_name, str(path))
                    module = importlib.util.module_from_spec(spec)
                    sys.modules[mod_name] = module
                    spec.loader.exec_module(module)
                    tool = getattr(module, "TOOL", None)
                    handle = getattr(module, "handle", None)
                    if not isinstance(tool, dict) or not callable(handle):
                        print(f"  [plugin] {path.name}: TOOL dict ya "
                              f"handle() nahi mila - skip", flush=True)
                        continue
                    decl = _declaration_from_tool(tool)
                    if decl.name in handlers:
                        print(f"  [plugin] {path.name}: tool "
                              f"'{decl.name}' pehle se hai - skip",
                              flush=True)
                        continue
                    declarations.append(decl)
                    handlers[decl.name] = handle
                    print(f"  [plugin] naya skill mila: {decl.name} "
                          f"({path.name})", flush=True)
                except Exception as exc:  # noqa: BLE001 - never fatal
                    print(f"  [plugin] {path.name} load nahi hua "
                          f"({exc.__class__.__name__}) - skip", flush=True)
        _cache.update({"loaded": True, "declarations": declarations,
                       "handlers": handlers})
        return declarations, handlers
