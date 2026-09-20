"""Toplanti deyimlerini cevirmeden once sadelestirir.

opus-mt is deyimlerini birebir cevirip anlamsiz Turkce uretiyor (olculdu):

    "Let's take this offline."      -> "Bunu devre disi birakalim."        (yanlis)
    "I'll circle back on that."     -> "Bunun uzerine tekrar cember cizecegim."
    "Let's touch base tomorrow."    -> "Yarin usse dokunalim."
    "We need to move the needle."   -> "Igneyi buraya tasimamiz lazim."
    "Let's park that item."         -> "O esyayi park edelim."

Ayni cumleler sade Ingilizce'ye cevrilip modele verildiginde dogru Turkce cikiyor:

    "Let's discuss this separately later."  -> "Bunu daha sonra ayri ayri tartisalim."
    "I will come back to that later."       -> "O konuya daha sonra gelecegim."
    "Let's talk briefly tomorrow."          -> "Yarin kisaca konusalim."
    "We need to make real progress."        -> "Gercek bir ilerleme kaydetmeliyiz."
    "Let's postpone that item."             -> "O maddeyi erteleyelim."

Bu yuzden ceviriden ONCE metin sadelestirilir. Ekranda ve transkriptte gosterilen
Ingilizce metin DEGISMEZ; sadelestirme yalnizca ceviri motoruna giden kopyada olur.
"""
from __future__ import annotations

import re

# Deyim -> sade Ingilizce karsiligi. Uzun kaliplar once denenir.
DEFAULT_PHRASES: dict[str, str] = {
    # Toplanti / is jargonu
    "take this offline": "discuss this separately later",
    "take it offline": "discuss it separately later",
    "circle back": "come back to this later",
    "touch base": "talk briefly",
    "park that": "postpone that",
    "park this": "postpone this",
    "put a pin in it": "postpone it",
    "move the needle": "make real progress",
    "double-click on": "explain in more detail",
    "double click on": "explain in more detail",
    "drill down into": "examine in detail",
    "loop in": "include",
    "loop me in": "include me",
    "reach out to": "contact",
    "ping me": "message me",
    "give you a heads-up": "warn you in advance",
    "heads-up": "advance notice",
    "low-hanging fruit": "the easiest tasks",
    "boil the ocean": "attempt something too large",
    "move forward with": "continue with",
    "align on": "agree on",
    "sync up": "meet briefly",
    "deep dive": "detailed examination",
    "push back on": "disagree with",
    "run it by": "ask the opinion of",
    "run by you": "ask your opinion",
    "wrap up": "finish",
    "kick off": "start",
    "on the same page": "in agreement",
    "out of scope": "not included in the project",
    "nice to have": "optional",
    "blocker": "obstacle",
    "showstopper": "critical problem",
    "quick win": "easy improvement",
    "bandwidth": "available time",
    "ballpark": "approximate",
    "eod": "end of day",
    "eow": "end of week",
    "asap": "as soon as possible",
    "fyi": "for your information",
    # Toplantida sik gecen diger kaliplar
    "trade-offs": "advantages and disadvantages",
    "trade-off": "advantage and disadvantage",
    "pros and cons": "advantages and disadvantages",
    "get the ball rolling": "start the work",
    "touch on": "briefly mention",
    "walk me through": "explain to me step by step",
    "walk us through": "explain to us step by step",
    "take a stab at": "attempt",
    "back to the drawing board": "start the design again",
    "in the weeds": "too deep in details",
    "table this": "postpone this discussion",
    "ramp up": "increase",
    "ramp down": "decrease",
    "head start": "early advantage",
    "workaround": "temporary solution",
    "edge case": "rare situation",
    "happy path": "normal successful flow",
    "shipped": "released",
    "ship it": "release it",
    "roll out": "release gradually",
    "roll back": "undo the change",
    "go live": "start using in production",
    "smoke test": "quick basic test",
    "gut feeling": "intuition",
    "off the top of my head": "from memory, approximately",
    "as-is": "without changes",
    "nail down": "decide precisely",
    "scope creep": "uncontrolled growth of project scope",
    "over-engineer": "make unnecessarily complex",
    # "deployment" tek basina "gorevlendirme" (askeri anlam) olarak cevriliyordu
    "deployment": "software release",
    "deployments": "software releases",
    # Fiil bicimleri bilerek yok: "We deployed the fix to prod" cumlesinde
    # "prod" ile ust uste binip "uretime gecen fix'i urettik" gibi bozuk
    # cikti veriyordu (olculdu).
    "rollout": "gradual release",
    # Yazilim/teknik kisaltmalar
    "prod": "production",
    "repo": "repository",
    # "pr" bilerek listede degil: hem "pull request" hem "halkla iliskiler"
    # olabiliyor ve yazilimcilar Turkce konusurken de "PR" diyor.
}


def build_pattern(extra: dict[str, str] | None = None) -> tuple[re.Pattern | None, dict[str, str]]:
    """Tek bir regex derler; uzun kaliplar once eslesir."""
    table = dict(DEFAULT_PHRASES)
    for key, value in (extra or {}).items():
        table[str(key).lower()] = str(value)
    if not table:
        return None, table
    keys = sorted(table, key=len, reverse=True)
    pattern = re.compile(
        r"(?<![\w-])(" + "|".join(re.escape(k) for k in keys) + r")(?![\w-])",
        re.IGNORECASE,
    )
    return pattern, table


def paraphrase(text: str, pattern: re.Pattern | None, table: dict[str, str]) -> str:
    if not pattern or not text:
        return text
    return pattern.sub(lambda m: table[m.group(0).lower()], text)
