"""Ara altyazinin oynamasini engelleyen kararli onek (LocalAgreement).

Sorun: ara altyazi her ~0,6 sn'de son birkac saniyeyi bastan cozuyor. Ingilizce
hipotez buyudukce Turkce cumle bastan kuruluyor, cunku Turkce kelime dizilimi
farkli. Olculdu: 7 guncellemede Turkce 7 kez tamamen degisti:

    "We need to"                              -> "Buna ihtiyacimiz var."
    "We need to align"                        -> "Uyum saglamaliyiz."
    "We need to align on the scope"           -> "Kapsam konusunda anlasmamiz gerekiyor."
    "... before we commit to a delivery date" -> "Teslimat tarihine karar vermeden once ..."

Cozum: ekranda yalnizca son iki hipotezin ORTAK oneki gosterilir. Boylece metin
yalnizca uzar, geri donup kendini yeniden yazmaz. Turkce ceviri ise cumle
bitince bir kez basilir (bkz. ui.partial_translate).
"""
from __future__ import annotations

_TRIM = ".,?!;:\"'"


def _norm(word: str) -> str:
    return word.strip(_TRIM).lower()


def common_prefix(prev: str, cur: str) -> str:
    """Iki hipotezin ortak kelime onekini dondurur (noktalama yok sayilir)."""
    if not prev or not cur:
        return ""
    prev_words, cur_words = prev.split(), cur.split()
    i = 0
    while i < min(len(prev_words), len(cur_words)) and _norm(prev_words[i]) == _norm(cur_words[i]):
        i += 1
    return " ".join(cur_words[:i])


class StableText:
    """Ardisik hipotezlerden yalnizca uzayan, geri donmeyen metin uretir."""

    def __init__(self, min_words: int = 2) -> None:
        self.min_words = min_words
        self._prev = ""
        self._shown = ""

    def reset(self) -> None:
        self._prev = ""
        self._shown = ""

    def update(self, hypothesis: str) -> str:
        """Yeni hipotezi alir, gosterilecek kararli metni dondurur."""
        stable = common_prefix(self._prev, hypothesis)
        self._prev = hypothesis
        if len(stable.split()) >= self.min_words and len(stable) >= len(self._shown):
            self._shown = stable
        return self._shown
