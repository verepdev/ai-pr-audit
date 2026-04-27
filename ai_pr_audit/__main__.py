"""Entrypoint — run with `python -m ai_pr_audit` for local development."""

import uvicorn

from ai_pr_audit.app import app


def main() -> None:
    uvicorn.run(app, host="127.0.0.1", port=8000)


if __name__ == "__main__":
    main()
