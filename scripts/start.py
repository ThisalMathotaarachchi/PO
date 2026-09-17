"""Windows startup helper. Run from the Po repository root."""

from __future__ import annotations

import os
import sys
from pathlib import Path


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    backend = root / "backend"
    os.chdir(root)
    sys.path.insert(0, str(backend))
    os.environ.setdefault("PYTHONPATH", str(backend))
    import uvicorn

    from app.config.settings import get_settings

    settings = get_settings()
    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=False)


if __name__ == "__main__":
    main()
