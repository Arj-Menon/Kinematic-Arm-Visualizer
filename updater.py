"""GitHub release auto-updater for the packaged Windows .exe build.

When run from a frozen PyInstaller bundle, downloads the first .exe asset of the
latest release and swaps it in via a self-deleting batch script that waits for
this process to exit. When run from source, only reports the result.
"""

from __future__ import annotations

import re
import subprocess
import sys
import tempfile
from pathlib import Path

import requests
from PyQt6.QtWidgets import QMessageBox, QWidget

GITHUB_RELEASES_API = (
    "https://api.github.com/repos/Arj-Menon/Kinematic-Arm-Visualizer/releases/latest"
)


def _parse_version(tag: str) -> tuple[int, ...]:
    """Strip a leading 'v' and return the leading numeric components."""
    cleaned = tag.strip().lstrip("vV")
    nums: list[int] = []
    for part in re.split(r"[.\-+]", cleaned):
        if part.isdigit():
            nums.append(int(part))
        else:
            break
    return tuple(nums) if nums else (0,)


def _is_newer(remote_tag: str, current_tag: str) -> bool:
    return _parse_version(remote_tag) > _parse_version(current_tag)


def check_for_updates(
    current_version: str,
    parent: QWidget | None = None,
    silent_if_no_update: bool = False,
) -> None:
    """Check GitHub for a newer release; prompt and install if available."""
    try:
        resp = requests.get(GITHUB_RELEASES_API, timeout=5)
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:
        if not silent_if_no_update:
            QMessageBox.warning(
                parent, "Update check failed",
                f"Could not contact GitHub:\n{exc}",
            )
        return

    latest_tag = str(data.get("tag_name", "")).strip()
    if not latest_tag or not _is_newer(latest_tag, current_version):
        if not silent_if_no_update:
            QMessageBox.information(
                parent, "Up to date",
                f"You're on the latest version ({current_version}).",
            )
        return

    assets = data.get("assets") or []
    exe_asset = next(
        (a for a in assets if str(a.get("name", "")).lower().endswith(".exe")),
        None,
    )
    if exe_asset is None:
        if not silent_if_no_update:
            QMessageBox.information(
                parent, "Update available",
                f"Version {latest_tag} is published but ships no .exe asset.",
            )
        return

    answer = QMessageBox.question(
        parent, "Update available",
        f"A new version ({latest_tag}) is available.\n"
        f"You're currently on {current_version}.\n\n"
        "Download and install now? The app will restart.",
    )
    if answer != QMessageBox.StandardButton.Yes:
        return

    if not getattr(sys, "frozen", False):
        QMessageBox.information(
            parent, "Source build",
            "Auto-update only swaps the packaged .exe. Grab the new release "
            "manually from GitHub when running from source.",
        )
        return

    exe_path = Path(sys.executable).resolve()
    new_exe = exe_path.with_name("app_new.exe")
    download_url = exe_asset.get("browser_download_url")
    try:
        with requests.get(download_url, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(new_exe, "wb") as f:
                for chunk in r.iter_content(chunk_size=64 * 1024):
                    if chunk:
                        f.write(chunk)
    except Exception as exc:
        try:
            new_exe.unlink(missing_ok=True)
        except Exception:
            pass
        QMessageBox.critical(
            parent, "Download failed",
            f"Could not download the update:\n{exc}",
        )
        return

    bat_path = _write_updater_bat(exe_path, new_exe)
    subprocess.Popen(
        ["cmd", "/c", str(bat_path)],
        close_fds=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )
    sys.exit(0)


def _write_updater_bat(original: Path, replacement: Path) -> Path:
    """Write a .bat that waits, swaps the .exe, relaunches, and self-deletes."""
    bat_path = Path(tempfile.gettempdir()) / "arm_gui_update.bat"
    bat_path.write_text(
        "@echo off\r\n"
        "timeout /t 2 /nobreak >nul\r\n"
        f'del /f /q "{original}"\r\n'
        f'ren "{replacement}" "{original.name}"\r\n'
        f'start "" "{original}"\r\n'
        'del "%~f0"\r\n',
        encoding="utf-8",
    )
    return bat_path
