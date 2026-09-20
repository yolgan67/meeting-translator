"""faster-whisper sarmalayicisi (CPU, int8 - PyTorch gerektirmez)."""
from __future__ import annotations

import os
import re

# CTranslate2/OpenMP thread sayisi model olusmadan ONCE ayarlanmali.
def configure_threads(cpu_threads: int) -> None:
    os.environ.setdefault("OMP_NUM_THREADS", str(cpu_threads))


# Whisper sessizlik veya muzikte bu kaliplari "halusinasyon" olarak uretir.
_HALLUCINATIONS = {
    "thank you.", "thank you", "thanks for watching!", "thanks for watching.",
    "you", "bye.", "bye", "[blank_audio]", "(silence)", "subtitles by the amara.org community",
    "please subscribe to my channel.", "okay.", "uh", "um", ".", "...",
}


def _looks_like_noise(text: str) -> bool:
    t = text.strip().lower()
    if not t or t in _HALLUCINATIONS:
        return True
    if not re.search(r"[a-zA-Z]", t):
        return True
    # Ayni kelimenin ust uste tekrari (klasik Whisper dongusu)
    words = re.findall(r"[a-z']+", t)
    if len(words) >= 6 and len(set(words)) <= 2:
        return True
    return False


class Transcriber:
    def __init__(self, cfg: dict, download_root: str | None = None) -> None:
        from faster_whisper import WhisperModel

        configure_threads(int(cfg["cpu_threads"]))
        self.beam_size = int(cfg["beam_size"])
        self.language = cfg.get("language") or "en"
        # Olculen degerler: gercek konusma -0.07..-0.40, halusinasyon -1.03..-1.61
        self.min_avg_logprob = float(cfg.get("min_avg_logprob", -0.85))
        self.max_no_speech_prob = float(cfg.get("max_no_speech_prob", 0.5))
        self.vad_filter = bool(cfg.get("vad_filter", False))
        # Alan sozlugu: Whisper'a jargon/ozel isim ipucu verir (ornegin urun
        # adlari, kisaltmalar). Bos birakilabilir.
        self.initial_prompt = (cfg.get("initial_prompt") or "").strip() or None
        self.model = WhisperModel(
            cfg["model"],
            device="cpu",
            compute_type=cfg["compute_type"],
            cpu_threads=int(cfg["cpu_threads"]),
            num_workers=1,
            download_root=download_root,
        )

    def transcribe(self, audio, min_avg_logprob: float | None = None) -> str:
        segments, _info = self.model.transcribe(
            audio,
            language=self.language,
            beam_size=self.beam_size,
            condition_on_previous_text=False,  # hata zincirini kirar, hizlandirir
            vad_filter=self.vad_filter,
            without_timestamps=True,
            no_speech_threshold=0.6,
            initial_prompt=self.initial_prompt,
        )
        parts: list[str] = []
        for seg in segments:
            text_part = (seg.text or "").strip()
            if not text_part:
                continue
            # Dusuk guvenli segmentler = sessizlik/gurultu uzerine uydurulmus cumleler.
            if getattr(seg, "no_speech_prob", 0.0) > self.max_no_speech_prob:
                continue
            floor = self.min_avg_logprob if min_avg_logprob is None else min_avg_logprob
            if getattr(seg, "avg_logprob", 0.0) < floor:
                continue
            parts.append(text_part)
        text = " ".join(parts).strip()
        text = re.sub(r"\s+", " ", text)
        if _looks_like_noise(text):
            return ""
        return text
