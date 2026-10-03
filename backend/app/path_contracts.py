from __future__ import annotations

import os
from pathlib import Path, PurePath, PurePosixPath, PureWindowsPath


def portable_absolute_path(
    value: str | os.PathLike[str],
    label: str,
) -> PurePath:
    """Validate an absolute path without applying host path semantics.

    Planning code may intentionally describe paths for another runtime, such as
    Linux container paths while the API itself runs on Windows. Pure path
    classes keep those contracts stable across hosts.
    """

    raw = os.fspath(value)
    if not isinstance(raw, str) or not raw:
        raise ValueError(f"{label} must be an absolute path.")

    posix = PurePosixPath(raw)
    if posix.is_absolute():
        return posix

    windows = PureWindowsPath(raw)
    if windows.is_absolute():
        return windows

    native = Path(raw)
    if native.is_absolute():
        return native

    raise ValueError(f"{label} must be an absolute path.")
