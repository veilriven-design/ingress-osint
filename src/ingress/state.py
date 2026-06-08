"""
User-state paths for Ingress.

State is intentionally small and local: target focus, cases, and other operator
preferences. The path can be redirected with INGRESS_STATE_DIR for sandboxes,
CI, or portable installs.
"""

from __future__ import annotations

import os
from pathlib import Path


def get_state_dir() -> Path:
    configured = os.environ.get("INGRESS_STATE_DIR")
    if configured:
        return Path(configured).expanduser()

    xdg_data_home = os.environ.get("XDG_DATA_HOME")
    if xdg_data_home:
        return Path(xdg_data_home).expanduser() / "ingress"

    return Path.home() / ".local" / "share" / "ingress"


def get_fallback_state_dir() -> Path:
    return Path.cwd() / ".ingress"


def ensure_state_dir() -> Path:
    state_dir = get_state_dir()
    try:
        state_dir.mkdir(parents=True, exist_ok=True)
        return state_dir
    except OSError:
        fallback = get_fallback_state_dir()
        fallback.mkdir(parents=True, exist_ok=True)
        return fallback


def target_state_file() -> Path:
    return get_state_dir() / "current_target.json"


def fallback_target_state_file() -> Path:
    return get_fallback_state_dir() / "current_target.json"


def cases_file() -> Path:
    return get_state_dir() / "cases.json"


def state_dir_writable() -> bool:
    try:
        state_dir = ensure_state_dir()
        probe = state_dir / ".write-test"
        probe.write_text("ok")
        probe.unlink(missing_ok=True)
        return True
    except OSError:
        return False
