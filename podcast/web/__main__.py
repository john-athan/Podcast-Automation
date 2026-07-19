"""Launch the console: `python -m podcast.web` (optionally HOST/PORT env)."""
from __future__ import annotations

import os


def main() -> None:
    import uvicorn
    host = os.getenv("WEB_HOST", "127.0.0.1")
    port = int(os.getenv("WEB_PORT", "8000"))
    print(f"Bulletin Desk console -> http://{host}:{port}")
    uvicorn.run("podcast.web.app:app", host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()
