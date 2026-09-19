"""Ses akisini cumlelere (utterance) boler.

Enerji tabanli, adaptif gurultu tabanli bir VAD kullanilir: loopback sesi dijital
oldugu icin (oda gurultusu yok) bu yaklasim yeterli ve ek bir model/bagimlilik
gerektirmez. Whisper'in kendi vad_filter'i KAPALI (bu VAD'in uzerine binince kisik
sesli gercek konusmayi siliyordu); uydurma cumleleri asr.py'deki skor filtresi tutar.
"""
from __future__ import annotations

import queue
import threading
import time
from dataclasses import dataclass

import numpy as np

SAMPLE_RATE = 16000
FRAME_MS = 30
FRAME_LEN = SAMPLE_RATE * FRAME_MS // 1000
SPLIT_SEARCH_MS = 1500   # zorunlu kesmede geriye dogru bakilacak pencere
TAIL_KEEP_FRAMES = 5     # segment sonunda birakilan sessizlik (~150 ms)
PARTIAL_TRIM_FRAMES = 5  # ara altyazida sondan kirpilan yarim kelime (~150 ms)


@dataclass
class Utterance:
    audio: np.ndarray
    start_s: float      # oturum basindan itibaren gecen sure
    duration_s: float
    captured_at: float  # monotonic; uctan uca gecikme olcumu icin
    partial: bool = False  # True: cumle bitmedi, ara altyazi (loga yazilmaz)


class Segmenter(threading.Thread):
    """Ses bloklarini alir, konusma parcalarini ASR kuyruguna yazar."""

    daemon = True

    def __init__(
        self,
        in_queue: "queue.Queue[np.ndarray]",
        out_queue: "queue.Queue[Utterance]",
        cfg: dict,
        session_start: float,
        partial_queue: "queue.Queue[Utterance] | None" = None,
    ) -> None:
        super().__init__(name="segmenter")
        self.in_queue = in_queue
        self.out_queue = out_queue
        self.partial_queue = partial_queue
        self.session_start = session_start

        # Ara altyazi: cumle bitmeden, birikmis sesi periyodik olarak cozup gosterir.
        # Olcum: konusmalar ortalama 5,3 sn surdugu icin cumle sonunu beklemek
        # 5-8 sn'lik algilanan gecikme yaratiyordu; ara altyazi bunu ~1,5 sn'ye indirir.
        partial_every_ms = float(cfg.get("partial_every_ms", 600))
        self.partial_every = int(partial_every_ms / FRAME_MS)
        # Ilk ara altyaziyi gereksiz geciktirmemek icin birikme esigi araliktan buyuk olmaz.
        self.partial_min_frames = max(1, int(min(600.0, partial_every_ms) / FRAME_MS))
        # Kayan pencere: uzun cumlede her ara altyazida tum tamponu yeniden cozmek
        # CPU'yu cumle uzadikca arttiriyordu. Sadece son N saniye cozulur; tam cumle
        # zaten sonunda kesin altyazi olarak gelir.
        self.partial_window_frames = max(
            self.partial_min_frames, int(float(cfg.get("partial_window_s", 4.0)) * 1000 / FRAME_MS)
        )
        self._frames_since_partial = 0

        self.silence_frames = max(1, int(cfg["silence_ms"] / FRAME_MS))
        self.min_speech_samples = int(SAMPLE_RATE * cfg["min_speech_ms"] / 1000)
        self.max_frames = max(10, int(cfg["max_segment_s"] * 1000 / FRAME_MS))
        self.preroll_samples = int(SAMPLE_RATE * cfg["preroll_ms"] / 1000)
        self.vad_multiplier = float(cfg["vad_multiplier"])
        self.vad_abs_floor = float(cfg["vad_abs_floor"])
        # Histerezis: konusma basladiktan sonra esik dusurulur, boylece cumle ici
        # kisa duraklamalar ve sonu yumusayan kelimeler cumleyi bolmez.
        self.vad_release_ratio = float(cfg.get("vad_release_ratio", 0.55))

        self._stop = threading.Event()
        self._tail = np.zeros(0, dtype=np.float32)      # cerceveye bolunmeyen artik
        self._lead = np.zeros(0, dtype=np.float32)      # konusma oncesi on tampon
        self._preroll = np.zeros(0, dtype=np.float32)
        self._frames: list[np.ndarray] = []             # hepsi FRAME_LEN uzunlugunda
        self._rms: list[float] = []
        self._silence_run = 0
        self._noise_floor = 0.003
        self._threshold = self.vad_abs_floor
        self.current_rms = 0.0

        # Cumle birlestirme: cok kisa parcalar ("as not.") tek basina hem kotu
        # cevrilir hem ekrani mesgul eder; kisa sure beklenip sonraki parcaya eklenir.
        self.merge_below_samples = int(SAMPLE_RATE * float(cfg.get("merge_below_s", 1.5)))
        self.carry_wait_frames = max(1, int(float(cfg.get("carry_wait_ms", 1200)) / FRAME_MS))
        self._carry: list[np.ndarray] = []
        self._carry_rms: list[float] = []
        self._carry_silence = 0

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                block = self.in_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            self._feed(block)
        self._emit()  # kapanista yarim kalan cumleyi de gonder

    # ------------------------------------------------------------------ input
    def _feed(self, block: np.ndarray) -> None:
        data = np.concatenate((self._tail, block)) if self._tail.size else block
        n_frames = len(data) // FRAME_LEN
        self._tail = data[n_frames * FRAME_LEN :].copy()
        for i in range(n_frames):
            self._process_frame(data[i * FRAME_LEN : (i + 1) * FRAME_LEN])

    def _process_frame(self, frame: np.ndarray) -> None:
        rms = float(np.sqrt(np.mean(frame.astype(np.float32) ** 2)))
        self.current_rms = rms
        self._threshold = max(self._noise_floor * self.vad_multiplier, self.vad_abs_floor)
        limit = self._threshold * (self.vad_release_ratio if self._frames else 1.0)

        if rms > limit:
            if not self._frames:
                if self._carry:
                    # Bekleyen kisa parca varsa yeni cumlenin basina eklenir.
                    self._frames = self._carry
                    self._rms = self._carry_rms
                    self._carry, self._carry_rms, self._carry_silence = [], [], 0
                elif self._preroll.size:
                    # Ilk hecenin kacmamasi icin on tamponu basa al.
                    self._lead = self._preroll.copy()
                    self._preroll = np.zeros(0, dtype=np.float32)
            self._append(frame, rms)
            self._silence_run = 0
            self._frames_since_partial += 1
            if (
                self.partial_queue is not None
                and self.partial_every > 0
                and self._frames_since_partial >= self.partial_every
                and len(self._frames) >= self.partial_min_frames
            ):
                self._emit_partial()
            if len(self._frames) >= self.max_frames:
                # Uzun monolog: kelime ortasindan degil, son 1.5 sn icindeki en
                # sessiz noktadan (mikro duraklama) kes.
                self._emit(split_at=self._best_split())
            return

        # Sessiz cerceve: gurultu tabanini yavasca guncelle (EMA).
        self._noise_floor = 0.97 * self._noise_floor + 0.03 * rms

        if self._frames:
            self._append(frame, rms)
            self._silence_run += 1
            if self._silence_run >= self.silence_frames:
                self._emit()
        elif self._carry:
            # Bekleyen kisa parca: yeni konusma gelmezse tek basina gonderilir.
            self._carry_silence += 1
            if self._carry_silence >= self.carry_wait_frames:
                self._frames, self._rms = self._carry, self._carry_rms
                self._carry, self._carry_rms, self._carry_silence = [], [], 0
                self._emit(allow_merge=False)
        else:
            self._preroll = np.concatenate((self._preroll, frame))[-self.preroll_samples :]

    def _append(self, frame: np.ndarray, rms: float) -> None:
        self._frames.append(frame.copy())
        self._rms.append(rms)

    # ------------------------------------------------------------------ split
    def _best_split(self) -> int:
        """Son SPLIT_SEARCH_MS icindeki en dusuk enerjili cerceveyi bulur."""
        n = len(self._frames)
        window = min(n - 1, SPLIT_SEARCH_MS // FRAME_MS)
        if window <= 2:
            return n
        start = n - window
        quietest = min(range(start, n - 1), key=lambda i: self._rms[i])
        return quietest + 1

    def _trim_tail(self, frames: list[np.ndarray], rms: list[float]) -> list[np.ndarray]:
        """Sondaki uzun sessizligi kirpar: Whisper bos sese cumle uydurabiliyor."""
        end = len(frames)
        while end > 1 and rms[end - 1] <= self._threshold:
            end -= 1
        return frames[: min(len(frames), end + TAIL_KEEP_FRAMES)]

    # ------------------------------------------------------------------ emit
    def _emit_partial(self) -> None:
        """Devam eden cumlenin o ana kadarki halini gonderir (loga yazilmaz)."""
        self._frames_since_partial = 0
        if not self._frames or self.partial_queue is None:
            return
        # Son cerceveler kelimenin ortasinda kesiliyor; yarim kelime Whisper'a
        # sacma tahminler urettiriyor, bu yuzden kirpiliyor.
        frames = self._frames[:-PARTIAL_TRIM_FRAMES] if len(self._frames) > PARTIAL_TRIM_FRAMES * 2 else self._frames
        if len(frames) > self.partial_window_frames:
            audio = np.concatenate(frames[-self.partial_window_frames :])
        else:
            parts = ([self._lead] if self._lead.size else []) + frames
            audio = np.concatenate(parts)
        now = time.monotonic()
        utt = Utterance(
            audio=audio,
            start_s=max(0.0, now - self.session_start - audio.size / SAMPLE_RATE),
            duration_s=audio.size / SAMPLE_RATE,
            captured_at=now,
            partial=True,
        )
        # Sadece en yeni ara altyazi ilgilendirir; eskisini dusur.
        try:
            self.partial_queue.put_nowait(utt)
        except queue.Full:
            try:
                self.partial_queue.get_nowait()
                self.partial_queue.put_nowait(utt)
            except queue.Empty:
                pass

    def _emit(self, split_at: int | None = None, allow_merge: bool = True) -> None:
        if not self._frames:
            return

        if split_at is None or split_at >= len(self._frames):
            head, head_rms = self._frames, self._rms
            rest, rest_rms = [], []
        else:
            head, head_rms = self._frames[:split_at], self._rms[:split_at]
            rest, rest_rms = self._frames[split_at:], self._rms[split_at:]

        lead = self._lead
        head = self._trim_tail(head, head_rms)

        # Kalan parca yeni cumlenin basi olur; on tampon tuketildi.
        self._frames, self._rms = rest, rest_rms
        self._lead = np.zeros(0, dtype=np.float32)
        self._silence_run = 0
        self._frames_since_partial = 0

        if not head:
            return
        audio = np.concatenate([lead, *head]) if lead.size else np.concatenate(head)
        if audio.size < self.min_speech_samples:
            return  # tik sesi, bildirim, kisa gurultu

        if allow_merge and split_at is None and audio.size < self.merge_below_samples:
            # Cok kisa: hemen gonderme, sonraki parcayla birlesmesi icin beklet.
            self._carry = list(head)
            self._carry_rms = list(head_rms[: len(head)])
            self._carry_silence = 0
            if lead.size:
                self._carry.insert(0, lead)
                self._carry_rms.insert(0, 0.0)
            return

        duration = audio.size / SAMPLE_RATE
        now = time.monotonic()
        utt = Utterance(
            audio=audio,
            start_s=max(0.0, now - self.session_start - duration),
            duration_s=duration,
            captured_at=now,
        )
        try:
            self.out_queue.put_nowait(utt)
        except queue.Full:
            # ASR yetismiyor: en eski cumleyi dusur ki altyazi gercek zamana yakin kalsin.
            try:
                self.out_queue.get_nowait()
                self.out_queue.put_nowait(utt)
            except queue.Empty:
                pass
