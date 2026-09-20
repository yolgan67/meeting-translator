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
        "initial_prompt": "",
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
        "beam_size": 4,
        "partial_beam_size": 1,
        "simplify_idioms": True,
        "phrase_map": {},
        "post_map": {},
    },
    "ui": {
        "mode": "bilingual",
        "show_partial": True,
        "max_lines": 4,
        "auto_height": True,
        "max_height_ratio": 0.7,
        "opacity": 0.85,
        "font_size_tr": 22,
        "font_size_en": 12,
        "color_tr": "#ffffff",
        "color_en": "#8b98a5",
        "color_bg": "#0f1216",
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


def save_ui_settings(values: dict[str, Any], path: str | Path | None = None) -> Path:
    """ui: blogundaki ayarlari config.yaml'a geri yazar.

    PyYAML ile yeniden serilestirmek dosyadaki tum yorumlari silecegi icin
    sadece ilgili satirlar yerinde degistirilir; satir sonu yorumlari korunur.
    """
    cfg_path = Path(path) if path else PROJECT_ROOT / "config.yaml"
    lines = cfg_path.read_text(encoding="utf-8").split("\n")

    start = next((i for i, ln in enumerate(lines) if ln.rstrip() == "ui:"), None)
    if start is None:
        raise ValueError("config.yaml icinde 'ui:' blogu bulunamadi")
    end = next(
        (i for i in range(start + 1, len(lines))
         if lines[i].strip() and not lines[i].startswith((" ", "\t"))),
        len(lines),
    )

    remaining = dict(values)
    for i in range(start + 1, end):
        stripped = lines[i].strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key = stripped.split(":", 1)[0].strip()
        if key not in remaining:
            continue
        indent = lines[i][: len(lines[i]) - len(lines[i].lstrip())]
        comment = _trailing_comment(lines[i].split(":", 1)[1])
        lines[i] = f"{indent}{key}: {_yaml_scalar(remaining.pop(key))}{comment}"

    # Dosyada hic olmayan ayarlar blogun sonuna eklenir.
    for key, value in remaining.items():
        lines.insert(end, f"  {key}: {_yaml_scalar(value)}")
        end += 1

    cfg_path.write_text("\n".join(lines), encoding="utf-8")
    return cfg_path


def _trailing_comment(after_colon: str) -> str:
    """Satir sonu yorumunu dondurur.

    Tirnak icindeki '#' (ornegin renk kodu "#ffffff") yorum baslangici sayilmaz.
    """
    quote = ""
    for idx, ch in enumerate(after_colon):
        if quote:
            if ch == quote:
                quote = ""
        elif ch in "\"'":
            quote = ch
        elif ch == "#":
            return "   " + after_colon[idx:].rstrip()
    return ""


def _yaml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, str):
        # Renk kodlari (#ffffff) yorum sanilmamasi icin tirnaklanir.
        return f'"{value}"' if value.startswith("#") or value == "" else value
    return str(value)


def resolve_path(value: str | Path) -> Path:
    """Goreli yollari proje kokune gore cozer."""
    p = Path(value)
    return p if p.is_absolute() else PROJECT_ROOT / p
