"""Windows WASAPI loopback ile sistem ses cikisini yakalar.

Loopback, hoparlore/kulaklima giden sesi dinler; yani Zoom/Teams'te karsi tarafin
sesini alir, kullanicinin mikrofonunu ALMAZ. Sanal ses kablosu kurmak gerekmez.
"""
from __future__ import annotations

import queue
import threading
import time

import numpy as np
import pyaudiowpatch as pyaudio

TARGET_RATE = 16000
BLOCK_MS = 100  # okuma blogu; VAD bunu 30 ms'lik cerceve lere boler


def _find_loopback_device(pa: pyaudio.PyAudio, wanted: str | None) -> dict:
    """Varsayilan cikis cihazinin loopback girisini bulur.

    wanted: cihaz adindan bir parca ("auto"/None ise varsayilan cihaz kullanilir).
    """
    if wanted and wanted != "auto":
        for info in pa.get_loopback_device_info_generator():
            if wanted.lower() in info["name"].lower():
                return info
        raise RuntimeError(f"'{wanted}' adini iceren loopback cihazi bulunamadi")

    # PyAudioWPatch >= 0.2.12.6 dogrudan varsayilani verebiliyor.
    try:
        return pa.get_default_wasapi_loopback()
    except Exception:
        pass

    default_out = pa.get_default_wasapi_device(d_out=True)
    for info in pa.get_loopback_device_info_generator():
        if default_out["name"] in info["name"]:
            return info
    raise RuntimeError(
        "Varsayilan cikis cihazinin loopback'i bulunamadi. "
        "Ses cikis cihazini degistirip tekrar dene."
    )


def _to_mono_16k(block: np.ndarray, channels: int, src_rate: int) -> np.ndarray:
    """int16 interleaved bloku -> float32 mono 16 kHz."""
    audio = block.astype(np.float32) / 32768.0
    if channels > 1:
        audio = audio.reshape(-1, channels).mean(axis=1)

    if src_rate == TARGET_RATE:
        return audio
    if src_rate % TARGET_RATE == 0:
        # Tam kat (48k/32k -> 16k): ortalama alarak hem alcak geciren filtre
        # hem de asagi ornekleme yapar.
        factor = src_rate // TARGET_RATE
        usable = (len(audio) // factor) * factor
        if usable == 0:
            return np.zeros(0, dtype=np.float32)
        return audio[:usable].reshape(-1, factor).mean(axis=1)

    # 44.1 kHz gibi tam kat olmayan oranlar icin dogrusal interpolasyon.
    out_len = int(round(len(audio) * TARGET_RATE / src_rate))
    if out_len == 0:
        return np.zeros(0, dtype=np.float32)
    src_idx = np.linspace(0, len(audio) - 1, num=out_len, dtype=np.float32)
    return np.interp(src_idx, np.arange(len(audio), dtype=np.float32), audio).astype(np.float32)


class AudioCapture(threading.Thread):
    """Loopback sesini float32 mono 16 kHz bloklar halinde kuyruga yazar."""

    daemon = True

    def __init__(self, out_queue: "queue.Queue[np.ndarray]", device: str = "auto") -> None:
        super().__init__(name="audio-capture")
        self.out_queue = out_queue
        self.device = device
        self._stop = threading.Event()
        self.device_name: str | None = None
        self.last_error: str | None = None
        self.last_block_ts: float = 0.0
        self.silence_filled_s: float = 0.0  # teshis: uretilen yapay sessizlik
        self._timeline: float = 0.0         # pusha edilen sesin bittigi an (monotonic)

    def stop(self) -> None:
        self._stop.set()

    def run(self) -> None:
        while not self._stop.is_set():
            try:
                self._capture_once()
            except Exception as exc:  # cihaz degisimi, kulaklik takma/cikarma vs.
                self.last_error = str(exc)
                if self._stop.is_set():
                    break
                # Cihaz kaybolduysa 1 sn sonra yeni varsayilanla tekrar bagla.
                time.sleep(1.0)

    def _push(self, audio: np.ndarray) -> None:
        try:
            self.out_queue.put_nowait(audio)
        except queue.Full:
            # Segmenter yetismiyorsa en eskiyi dusur, lag birikmesin.
            try:
                self.out_queue.get_nowait()
                self.out_queue.put_nowait(audio)
            except queue.Empty:
                pass

    def _capture_once(self) -> None:
        with pyaudio.PyAudio() as pa:
            info = _find_loopback_device(pa, self.device)
            self.device_name = info["name"]
            src_rate = int(info["defaultSampleRate"])
            channels = min(int(info["maxInputChannels"]), 2)
            frames = max(256, int(src_rate * BLOCK_MS / 1000))

            stream = pa.open(
                format=pyaudio.paInt16,
                channels=channels,
                rate=src_rate,
                input=True,
                input_device_index=int(info["index"]),
                frames_per_buffer=frames,
            )
            try:
                self.last_error = None
                self._timeline = time.monotonic()
                while not self._stop.is_set():
                    avail = stream.get_read_available()
                    if avail > 0:
                        # Ne kadar hazirsa onu oku: tam blok bekleyince kismi veri
                        # cihazda kaliyor ve zaman cizgisi geride kaliyordu.
                        raw = stream.read(min(avail, frames * 4), exception_on_overflow=False)
                        block = np.frombuffer(raw, dtype=np.int16)
                        if block.size == 0:
                            continue
                        audio = _to_mono_16k(block, channels, src_rate)
                        if audio.size:
                            self.last_block_ts = time.monotonic()
                            # Zaman cizgisi pushlanan her sesle (gercek + yapay)
                            # ilerler; boylece ayni wall-clock suresi iki kez dolmaz.
                            self._timeline += audio.size / TARGET_RATE
                            self._push(audio)
                        continue

                    # WASAPI loopback, cikis cihazi bostayken HIC veri uretmez.
                    # Bu durumda zaman cizgisi kayar ve "sessizlik = cumle bitti"
                    # kurali hic tetiklenmez; eksik sureyi yapay sessizlikle doldur.
                    time.sleep(0.02)
                    deficit = time.monotonic() - self._timeline
                    if deficit >= 0.12:
                        n = min(int(deficit * TARGET_RATE), TARGET_RATE * 5)
                        self.silence_filled_s += n / TARGET_RATE
                        self._timeline += n / TARGET_RATE
                        self._push(np.zeros(n, dtype=np.float32))
            finally:
                stream.stop_stream()
                stream.close()
