"""Plugin template - copy this file, rename it (without the leading
underscore), and JARVIS learns your skill at the next launch.

The loader skips files whose name starts with "_", which is how
this template stays a template. Adapted from Mark LVI's
plugins/_template.py idea (by FatihMakes, CC BY-NC 4.0) to
JARVIS's own TOOL format.

A plugin is exactly two things:

1) TOOL - a dict describing the skill for the model.
2) handle(args) - a function that does the work and returns a
   JSON-able dict. Results should carry "status": "done"/"ok" only
   when the work really happened (verify first), or
   "status": "error" with a "message".
"""

TOOL = {
    "name": "mera_tool",  # unique, snake_case - this is what the model calls
    "description": (
        "Kab use karna hai ye saaf likho - model yahi padh kar "
        "faisla karta hai. Example: 'Jab user X mange to is tool "
        "se X karo. Asli result hamesha isi tool se aayega, khud "
        "mat banana.'"
    ),
    # simple form: argument name -> (type, description)
    # types: "string", "integer", "number", "boolean"
    "parameters": {
        "example_input": ("string", "Example argument ki description."),
    },
    "required": ["example_input"],
}


def handle(args):
    value = (args or {}).get("example_input", "")
    # ... yahan apna kaam karo ...
    return {"status": "done", "echo": value}
