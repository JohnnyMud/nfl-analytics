"""``python -m api`` serves the read API with reload for local UI work."""

from __future__ import annotations

import uvicorn


def main() -> None:
    uvicorn.run("api.app:app", host="127.0.0.1", port=8000, reload=True)


if __name__ == "__main__":
    main()
