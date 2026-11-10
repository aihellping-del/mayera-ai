JARVIS PLUGINS - nayi skill khud jodo
======================================

Is folder me ek .py file daal do, JARVIS agli baar start hone par
wo skill khud seekh lega. Kuch aur edit nahi karna padta.

Har plugin file me do cheezein honi chahiye:

1) TOOL - ek dict jo batata hai skill ka naam, kaam aur inputs:

    TOOL = {
        "name": "roll_dice",
        "description": "Dice ghumata hai jab user random number mange.",
        "parameters": {"sides": ("integer", "Kitne sides, default 6")},
        "required": [],
    }

2) handle(args) - ek function jo kaam karke dict return kare:

    def handle(args):
        return {"status": "ok", "rolled": 4}

dice_plugin.py isi folder me ek chalta hua example hai - use
copy karke apna plugin banao.

 Dhyaan do:
 - Galat/broken plugin JARVIS ko rok nahi sakta; terminal me
   [plugin] line ke saath skip ho jata hai.
 - Plugin tumhare computer par tumhare hi bharose ka code hai -
   sirf wahi plugin daalo jise tum khud samajhte ho.
 - File ka naam "_" se shuru ho to wo load nahi hoti (band rakhne
   ke liye naam ke aage _ laga do).
