"""Standalone Notepad test for JARVIS (v3.13) - NO voice needed.

Run on the Windows PC, from the JARVIS folder:

    python test_notepad.py

It uses the exact same code the voice agent uses (PcController):
opens Notepad, waits for its window, focuses it by title, then
types one English line and one Hindi line by clipboard-paste
(so the Hindi must come out perfectly). Watch Notepad: both lines
should appear. The terminal prints every step's result.

--------------------------------------------------------------------
TROUBLESHOOTING CHECKLIST (agar text na aaye)
--------------------------------------------------------------------
1. WINDOW FOCUS: Notepad ki window sabse saamne (foreground) honi
   chahiye. Test ke dauraan mouse/keyboard mat chhuo - koi aur
   window saamne aa gayi to paste wahi chala jayega. Isiliye
   type_text pehle focus_window('Notepad') karta hai aur focus na
   mile to type hi NAHI karta (galat jagah likhne se behtar hai).
2. ADMINISTRATOR: agar Notepad (ya terminal) Administrator mode me
   khula hai aur JARVIS normal mode me hai, to Windows focus/paste
   rok sakta hai (UIPI). Dono ko ek hi level par rakho - aam taur
   par dono normal. Ulta bhi: JARVIS wala terminal "Run as
   administrator" karke chalao agar Notepad elevated hai.
3. WINDOWS 11 NOTEPAD SLOW: naye Win11 Notepad ka pehla open kai
   second le sakta hai. JARVIS ab 8 second tak window ka intezaar
   karta hai (poll). Phir bhi na khule to ek baar khud Notepad
   khol-band karke warm kar lo, phir test chalao.
4. HINDI TEXT: typing hamesha clipboard + Ctrl+V se hoti hai
   (pyautogui.write Hindi nahi likh sakta). Agar Hindi ki jagah
   khaali dabbe (boxes) dikhein to wo font/display ka masla hai,
   text sahi gaya hai - file save karke phone par khol kar dekho.
5. CLIPBOARD: paste se pehle tumhara purana clipboard (agar text
   tha) save karke baad me wapas rakh diya jata hai. Koi clipboard
   manager app beech me aaye to ek baar use band karke try karo.
6. SCREEN PAR VERIFY: voice mode me "JARVIS, screen par kya hai?"
   bolkar poochho - JARVIS look_at_screen se dekh kar batayega ki
   Notepad me text dikh raha hai ya nahi.
--------------------------------------------------------------------
"""

import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from actions.pc_control import PcController  # noqa: E402

ENGLISH_LINE = "Hello Golu, this is JARVIS typing in Notepad."
HINDI_LINE = "आज का काम: gym jaana hai और पानी पीना है।"


def main():
    pc = PcController()
    print("1) Notepad khol raha hu (window aane ka intezaar hoga)...")
    result = pc.open_app("notepad")
    print("   open_app ->", result)
    if result.get("status") != "opened":
        print("   FAIL: Notepad nahi khula. Upar wali checklist dekho.")
        return 1

    print("2) Notepad window ko title se focus kar raha hu...")
    focused = pc.focus_window("Notepad")
    print("   focus_window('Notepad') ->", focused)
    if not focused:
        print("   FAIL: window focus nahi hui - text nahi likhunga.")
        return 1

    print("3) English line likh raha hu...")
    result = pc.type_text(ENGLISH_LINE, window_title="Notepad")
    print("   type_text ->", result)
    if result.get("status") != "typed":
        print("   FAIL:", result.get("message"))
        return 1

    pc.press_key("enter")
    time.sleep(0.3)

    print("4) Hindi line likh raha hu (clipboard paste se)...")
    result = pc.type_text(HINDI_LINE, window_title="Notepad")
    print("   type_text ->", result)
    if result.get("status") != "typed":
        print("   FAIL:", result.get("message"))
        return 1

    print()
    print("PASS ki shart: Notepad me dono line bilkul sahi dikhni")
    print("chahiye - English bhi, aur Hindi (देवनागरी) bhi.")
    print("Dikhi? To voice wala raasta bhi chalega: ab JARVIS ko")
    print("bolo - 'Notepad kholo aur likho: aaj ka kaam gym jaana'.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
