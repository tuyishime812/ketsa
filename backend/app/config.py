"""Environment loading for the Ketsa backend.

Loads ``backend/.env`` into the process environment at import time so local
development can keep secrets (Supabase URL + service-role key, PayChangu keys)
out of version control. The file is gitignored (see ``backend/.gitignore``).

Values already present in the environment win — a deployment that injects real
env vars (Railway/Render/etc.) is unaffected by a local ``.env`` file.
"""

from __future__ import annotations

import os
from pathlib import Path

_BACKEND_ENV = Path(__file__).resolve().parent.parent / ".env"


def load_env_file(path: os.PathLike[str] | str | None = None) -> bool:
    """Load KEY=VALUE pairs from a .env file into ``os.environ``.

    Existing environment variables are never overridden, so this is safe to
    call unconditionally at startup. Returns True when a file was read.
    """
    env_path = Path(path) if path is not None else _BACKEND_ENV
    if not env_path.is_file():
        return False

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith(("export ", "set ")):
            line = line.split(None, 1)[1].strip()
        if "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if (len(value) >= 2 and value[0] == value[-1]
                and value[0] in ("'", '"', "`")):
            value = value[1:-1]
        if key and key not in os.environ:
            os.environ[key] = value
    return True