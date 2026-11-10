"""Example JARVIS plugin: a dice roller (v3.15).

This single file is the whole skill - JARVIS discovered it at
launch because it sits in the plugins/ folder and declares a TOOL
dict plus a handle() function. Copy this file as a starting point
for your own plugins; JARVIS learns them on the next start.
"""

import random

TOOL = {
    "name": "roll_dice",
    "description": (
        "Roll a dice for the user ('dice ghumao', 'ek random number "
        "batao', 'toss karo'). Returns the rolled number - report "
        "exactly that number, never invent one."
    ),
    "parameters": {
        "sides": ("integer", "How many sides the dice has. Default 6."),
    },
    "required": [],
}


def handle(args):
    try:
        sides = int((args or {}).get("sides") or 6)
    except (TypeError, ValueError):
        sides = 6
    sides = max(2, min(1000, sides))
    return {"status": "ok", "sides": sides,
            "rolled": random.randint(1, sides)}
