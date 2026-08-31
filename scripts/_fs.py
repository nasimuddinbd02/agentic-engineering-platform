"""Filesystem helpers shared by the scripts.

Git marks objects in ``.git/objects`` read-only, and on Windows that makes a
plain ``shutil.rmtree`` fail with ``PermissionError``.  Every place the POC
deletes a repository or a workspace goes through here.
"""

from __future__ import annotations

import os
import shutil
import stat
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


def _clear_readonly(function: Callable[..., Any], path: str, _exception: Any) -> None:
    try:
        os.chmod(path, stat.S_IWRITE)
        function(path)
    except OSError:
        # Genuinely undeletable (open handle, permissions): leave it rather
        # than crash the caller.
        pass


def force_rmtree(path: Path, *, attempts: int = 3) -> None:
    """Remove a tree, clearing the read-only bit that Git sets on its objects.

    Retries briefly: on Windows a just-terminated worker can still hold a handle
    for a moment.  If the tree survives, this raises rather than letting the
    caller fail later with a confusing error.
    """
    path = Path(path)
    for attempt in range(attempts):
        if not path.exists():
            return
        shutil.rmtree(path, onexc=_clear_readonly)
        if not path.exists():
            return
        if attempt < attempts - 1:
            time.sleep(0.5)

    raise OSError(
        f"could not remove {path}. A worker or editor may still have it open - "
        "stop the API and worker processes and try again."
    )
