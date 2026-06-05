"""COMSOL Clippy — local RAG over COMSOL manuals with an MCP search server."""

import os
from pathlib import Path


def _load_dotenv() -> None:
    """Load KEY=VALUE pairs from the project-root .env into os.environ.

    Dependency-free and runs before huggingface_hub is imported, so secrets like
    HUGGING_FACE_HUB_TOKEN live in the untracked .env (gitignored) rather than in
    tracked source. setdefault: an already-set environment variable still wins.
    """
    env_path = Path(__file__).resolve().parent.parent / ".env"
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


_load_dotenv()

# Route Hugging Face downloads through the plain HTTPS path instead of Xet. This keeps
# downloads on the simpler code path across Linux/WSL/Windows and avoids Xet-specific
# transport failures while the setup scripts fetch the embedding model. setdefault so
# an explicit user setting still wins. Must run before huggingface_hub is imported.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

__version__ = "0.1.0"
