#!/usr/bin/env python3
"""User-initiated screen capture for Fabric Vision.

This module intentionally has no scheduler and no persistent store. A caller asks
for one frame; the endpoint captures one frame, returns bytes/metadata, and deletes
the temporary files. Repeated observation belongs to the requesting client.
"""
from __future__ import annotations

import base64
import hashlib
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

MAX_FRAME_BYTES = 6 * 1024 * 1024
DEFAULT_MAX_WIDTH = 1600
DEFAULT_QUALITY = 72


def _which(*names: str) -> str | None:
    for name in names:
        if os.path.isabs(name) and os.access(name, os.X_OK):
            return name
        found = shutil.which(name)
        if found:
            return found
    return None


def capture_provider() -> dict:
    """Return the first native screen-capture provider available on this node."""
    system = platform.system().lower()
    if system == "darwin":
        tool = _which("/usr/sbin/screencapture", "screencapture")
        if tool:
            return {"name": "screencapture", "tool": tool, "platform": "macos"}
        return {"name": "", "tool": "", "platform": "macos", "error": "screencapture not found"}

    if system == "linux":
        # Prefer desktop-aware tools before generic X11 capture. They understand
        # Wayland/compositor semantics and fail more legibly when capture is denied.
        candidates = (
            ("grim", "grim"),
            ("gnome-screenshot", "gnome-screenshot"),
            ("spectacle", "spectacle"),
            ("scrot", "scrot"),
            ("imagemagick-import", "import"),
        )
        for name, binary in candidates:
            tool = _which(binary)
            if tool:
                return {"name": name, "tool": tool, "platform": "linux"}
        return {"name": "", "tool": "", "platform": "linux", "error": "no supported screen capture tool found"}

    return {"name": "", "tool": "", "platform": system or "unknown", "error": "screen capture is not supported on this platform"}


def _capture_command(provider: dict, output: Path) -> list[str]:
    name = provider.get("name")
    tool = str(provider.get("tool") or "")
    if name == "screencapture":
        return [tool, "-x", "-t", "png", str(output)]
    if name == "grim":
        return [tool, str(output)]
    if name == "gnome-screenshot":
        return [tool, "-f", str(output)]
    if name == "spectacle":
        return [tool, "-b", "-n", "-o", str(output)]
    if name == "scrot":
        return [tool, str(output)]
    if name == "imagemagick-import":
        return [tool, "-window", "root", str(output)]
    raise RuntimeError("no screen capture provider")


def _compress(source: Path, dest: Path, max_width: int, quality: int) -> tuple[Path, str]:
    """Compress to WebP when ffmpeg is available; otherwise return the PNG."""
    ffmpeg = _which("ffmpeg", "/opt/homebrew/bin/ffmpeg", "/usr/local/bin/ffmpeg", "/home/linuxbrew/.linuxbrew/bin/ffmpeg")
    if not ffmpeg:
        return source, "image/png"
    width = max(320, min(3840, int(max_width or DEFAULT_MAX_WIDTH)))
    q = max(20, min(95, int(quality or DEFAULT_QUALITY)))
    # libwebp quality maps naturally to q:v for ffmpeg. Preserve aspect ratio and
    # never upscale a smaller desktop.
    vf = f"scale='min({width},iw)':-2"
    cmd = [ffmpeg, "-hide_banner", "-loglevel", "error", "-y", "-i", str(source), "-vf", vf, "-c:v", "libwebp", "-q:v", str(q), "-frames:v", "1", str(dest)]
    try:
        run = subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=12)
        if run.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return dest, "image/webp"
    except (OSError, subprocess.TimeoutExpired):
        pass
    return source, "image/png"


def capture_screen(*, previous_hash: str = "", max_width: int = DEFAULT_MAX_WIDTH, quality: int = DEFAULT_QUALITY) -> dict:
    """Capture one screen frame and return a transport-ready ephemeral payload."""
    provider = capture_provider()
    if not provider.get("tool"):
        return {"ok": False, "available": False, "error": provider.get("error") or "screen capture unavailable", "provider": provider}

    with tempfile.TemporaryDirectory(prefix="fabric-vision-") as temp:
        root = Path(temp)
        raw = root / "screen.png"
        encoded = root / "screen.webp"
        try:
            proc = subprocess.run(_capture_command(provider, raw), stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, timeout=12)
        except subprocess.TimeoutExpired:
            return {"ok": False, "available": True, "error": "screen capture timed out", "provider": provider}
        except OSError as exc:
            return {"ok": False, "available": True, "error": str(exc), "provider": provider}

        if proc.returncode != 0 or not raw.exists() or raw.stat().st_size == 0:
            detail = proc.stderr.decode("utf-8", "replace").strip()[:600]
            return {"ok": False, "available": True, "error": detail or f"{provider['name']} failed", "provider": provider}

        frame, mime = _compress(raw, encoded, max_width, quality)
        try:
            data = frame.read_bytes()
        except OSError as exc:
            return {"ok": False, "available": True, "error": str(exc), "provider": provider}

        if len(data) > MAX_FRAME_BYTES:
            return {"ok": False, "available": True, "error": f"captured frame exceeds {MAX_FRAME_BYTES // (1024*1024)} MiB transport limit", "provider": provider, "bytes": len(data)}

        digest = hashlib.sha256(data).hexdigest()
        unchanged = bool(previous_hash and previous_hash == digest)
        payload = {
            "ok": True,
            "available": True,
            "changed": not unchanged,
            "hash": digest,
            "mime": mime,
            "bytes": len(data),
            "provider": {k: provider.get(k) for k in ("name", "platform")},
            "ephemeral": True,
            "stored": False,
        }
        if not unchanged:
            payload["image_base64"] = base64.b64encode(data).decode("ascii")
        return payload
