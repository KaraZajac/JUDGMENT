"""Load repo-root .env into os.environ (no override). Imported for side effect.

Keeps secrets like COURTLISTENER_TOKEN out of the repo and out of shell
profiles; CI provides the same variables via Actions secrets instead.
"""

import os
from pathlib import Path

_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    for line in _env_path.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, _, value = line.partition("=")
            os.environ.setdefault(key.strip(), value.strip())
