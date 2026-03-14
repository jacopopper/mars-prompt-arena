"""Local entry point for running the Mars Prompt Arena backend."""

from __future__ import annotations

import os

import uvicorn


def main() -> None:
    """Run the FastAPI application with uvicorn."""

    uvicorn.run(
        "ui.server:app",
        host=os.getenv("HOST", "127.0.0.1"),
        port=int(os.getenv("PORT", "8000")),
        reload=False,
    )


if __name__ == "__main__":
    main()
