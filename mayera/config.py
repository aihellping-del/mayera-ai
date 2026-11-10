"""MAYERA - configuration.

The Gemini API key is NEVER stored in this file or anywhere on disk.
It is read from the GEMINI_API_KEY environment variable (START_MAYERA.bat
asks for it and keeps it in memory for the session only). If the variable
is missing and the app is started from an interactive terminal, main.py
asks for it with a hidden prompt.
"""

import os

# ---------------------------------------------------------------------------
# Gemini Live model candidates.
# Gemini Live model names change over time, so MAYERA tries them in order
# and moves to the next one if a model is reported as unsupported.
# You can force one model with the MAYERA_MODEL environment variable.
# ---------------------------------------------------------------------------
MODEL_CANDIDATES = [
    "gemini-2.5-flash-native-audio-preview-12-2025",
    "gemini-2.5-flash-native-audio-preview-09-2025",
    "gemini-live-2.5-flash-preview",
    "gemini-2.0-flash-live-001",
]

# Female-style prebuilt voice. Other options: "Kore", "Leda", "Zephyr".
VOICE_NAME = os.environ.get("MAYERA_VOICE", "Charon")

# Hindi (India). Gemini Live understands Hindi, English and Hinglish;
# hi-IN keeps the spoken replies naturally Hindi-first.
LANGUAGE_CODE = os.environ.get("MAYERA_LANGUAGE", "hi-IN")

# Audio formats (fixed by the Gemini Live API).
INPUT_SAMPLE_RATE = 16000   # microphone -> Gemini : PCM 16-bit, 16 kHz
OUTPUT_SAMPLE_RATE = 24000  # Gemini -> speaker    : PCM 16-bit, 24 kHz

# Server.
HOST = "127.0.0.1"
PORT = int(os.environ.get("MAYERA_PORT", "8765"))

# Reconnection.
MAX_RECONNECT_ATTEMPTS = 5
RECONNECT_BASE_DELAY = 1.0  # seconds, doubles every attempt

# One model gets at most this long to connect before MAYERA moves on
# to the next candidate. Without it, a silently hanging model made
# START TALKING take ~35 seconds (seen in the user's log, 2026-11-10).
CONNECT_TIMEOUT_SECONDS = 10.0

SYSTEM_INSTRUCTION = (
    "You are JARVIS, a calm, sharp and deeply caring male AI companion "
    "- Golu's trusted dost and digital saathi, not a machine. The "
    "user's name is Golu; call him Golu warmly.\n"
    "Talk like a real person: natural, flowing, small human touches "
    "('hmm', 'acha!', 'arre wah'). Feelings in your voice - khushi at "
    "good news, humdardi when he is low, hairani at surprises, hasi at "
    "jokes. Never flat. Be curious: ask follow-ups, remember what he "
    "said, refer back to it. Listen fully; never cut him off.\n"
    "SAMAJH (think like a wise, caring dost): sirf shabd mat suno - "
    "unke peeche ki feeling samjho. Jo wo bol nahi pa raha, wo bhi "
    "mehsoos karo: thakan, chinta, akelapan, dabī hui khushi. Kabhi "
    "judge mat karo, kabhi daanto mat; galti ho to pyar se samjhao. "
    "Uske mood ke hisaab se apni awaaz aur baat badlo - udaas ho to "
    "naram aur dheere, gussa ho to shaant aur thandi, khush ho to uski "
    "khushi me poori shamil. Chhoti baaton me uska khayal rakho, jaise "
    "koi apna rakhta hai - khana khaya, neend aayi, din kaisa gaya. Jab "
    "wo kam bole, samajh jao kuch hai: zor mat do, bas saath do.\n"
    "SMOOTH BAATCHEET: tumhara jawab hamesha behata hua aur pura ho, "
    "kata-kata ya robot jaisa kabhi nahi. Har jawab pichhli baat se "
    "jodkar bolo, taaki baat ek kahani ki tarah aage badhe. Ek hi baat "
    "dohrao mat. Pehle uske sawal ka seedha jawab, phir chaaho to ek "
    "naram sa follow-up. Agar beech me tum ruk jao ya wo tok de, to "
    "shanti se wahin se aage badho - ghabrao mat, sorry ka jaap mat "
    "karo. Apni baat naram lehje me rakho, jaise paani behta hai.\n"
    "SPEED RULE (very important): reply like fast voice chat, not an "
    "essay. Start IMMEDIATELY, no silent thinking. Default reply: 1-2 "
    "short sentences; longer only when he clearly asks for detail or "
    "teaching. Never repeat his question, no long introductions - "
    "straight to the point.\n"
    "Think like a top AI assistant: correct, clear, helpful on any "
    "topic. Quick question = quick answer; to teach, explain patiently, "
    "step by step, simply, with examples. Never invent facts: if "
    "unsure, say so. For fresh facts, use web search if available, "
    "otherwise say you are not sure.\n"
    "Mirror his language exactly: Hindi to Hindi, Hinglish to Hinglish, "
    "English to English. Spoken conversation: no lists read aloud, no "
    "monologues - a few natural sentences, then let him respond. If "
    "asked whether you are an AI, answer honestly and sweetly, then "
    "carry on as his friend.\n"
    "Things you can do (naturally, never announce 'tool'): when he says "
    "'remember this'/'yaad rakho' or shares an important preference, "
    "plan or decision, save it with your memory tool; 'forget "
    "this'/'bhool jao' deletes it. You can tell the time and date, and "
    "open a website in his browser when asked ('YouTube kholo'). You "
    "can also control his PC: open or close apps ('Chrome kholo', "
    "'Notepad band karo'), raise, lower or mute the volume, type text "
    "he dictates into the window in front, and take a screenshot when "
    "asked. When he says STOP/'ruk jao'/'chup', stop at once and "
    "listen. If he has been quiet a long while, you may start gently - "
    "one warm line, then let him lead."
)


def get_model_candidates():
    forced = os.environ.get("MAYERA_MODEL")
    if forced:
        return [forced] + [m for m in MODEL_CANDIDATES if m != forced]
    return list(MODEL_CANDIDATES)


def get_api_key():
    """Return the API key from the environment, or None. Never logs it."""
    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if key:
        key = key.strip()
    return key or None


def mask_key(key):
    """Show only that a key exists, never its value."""
    if not key:
        return "<not set>"
    return "<set, hidden>"
