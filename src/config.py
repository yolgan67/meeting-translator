"""config.yaml okuma ve varsayilanlarla birlestirme."""
from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parent.parent

DEFAULTS: dict[str, Any] = {
    "audio": {"device": "auto", "sample_rate": 16000},
    "asr": {
        "model": "base.en",
        "partial_model": "tiny.en",
        "compute_type": "int8",
        "cpu_threads": 3,
        "beam_size": 1,
        "language": "en",
        "min_avg_logprob": -0.85,
        "partial_min_avg_logprob": -0.6,
        "max_no_speech_prob": 0.5,
        "vad_filter": False,
    },
    "segmenter": {
        "silence_ms": 700,
        "min_speech_ms": 400,
        "max_segment_s": 8,
        "preroll_ms": 500,
        "vad_multiplier": 1.8,
        "vad_release_ratio": 0.4,
        "vad_abs_floor": 0.0015,
        "merge_below_s": 2.0,
        "carry_wait_ms": 1200,
        "partial_every_ms": 600,
        "partial_window_s": 4.0,
    },
    "translate": {
        "engine": "local",
        "model_dir": "models/opus-mt-en-tr-ct2",
        "source_prefix": "",
        "deepl_api_key": "",
    },
    "ui": {
        "mode": "bilingual",
        "show_partial": True,
        "max_lines": 4,
        "opacity": 0.85,
        "font_size_tr": 22,
        "font_size_en": 12,
        "width": 900,
        "height": 260,
        "margin_bottom": 80,
    },
    "log": {"dir": "logs"},
}


def _deep_merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = value
    return out


def load_config(path: str | Path | None = None) -> dict[str, Any]:
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    user_cfg: dict[str, Any] = {}
    if cfg_path.is_file():
        with cfg_path.open("r", encoding="utf-8") as fh:
            user_cfg = yaml.safe_load(fh) or {}
    return _deep_merge(DEFAULTS, user_cfg)


def resolve_path(value: str | Path) -> Path:
    """Goreli yollari proje kokune gore cozer."""
    p = Path(value)
    return p if p.is_absolute() else PROJECT_ROOT / p
