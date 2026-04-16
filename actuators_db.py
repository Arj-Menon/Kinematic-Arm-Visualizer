"""Tiny on-disk actuator preset database (name -> weight in kg)."""

import json
from pathlib import Path


DB_PATH = Path(__file__).parent / "actuators.json"

DEFAULTS = {
    "Generic Small (0.2kg)": 0.2,
    "Generic Medium (0.5kg)": 0.5,
    "Generic Large (1.0kg)": 1.0,
}


def load() -> dict[str, float]:
    """Load the preset dict. Creates the file with defaults if missing."""
    if not DB_PATH.exists():
        save(DEFAULTS)
        return dict(DEFAULTS)
    try:
        with DB_PATH.open("r", encoding="utf-8") as f:
            raw = json.load(f)
        # Coerce to {str: float} and drop bad entries.
        out: dict[str, float] = {}
        for k, v in raw.items():
            try:
                out[str(k)] = float(v)
            except (TypeError, ValueError):
                continue
        if not out:
            out = dict(DEFAULTS)
            save(out)
        return out
    except (OSError, json.JSONDecodeError):
        return dict(DEFAULTS)


def save(presets: dict[str, float]) -> None:
    """Persist presets dict to disk (sorted by name for stable diffs)."""
    data = {k: float(v) for k, v in presets.items()}
    with DB_PATH.open("w", encoding="utf-8") as f:
        json.dump(dict(sorted(data.items())), f, indent=2)
        f.write("\n")


def add(name: str, weight_kg: float) -> dict[str, float]:
    """Add/overwrite a preset, persist, and return the updated dict."""
    presets = load()
    presets[name] = float(weight_kg)
    save(presets)
    return presets
