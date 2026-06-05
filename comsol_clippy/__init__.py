"""COMSOL Clippy — local RAG over COMSOL manuals with an MCP search server."""

import os

# Route Hugging Face downloads through the plain HTTPS path instead of Xet. This keeps
# downloads on the simpler code path across Linux/WSL/Windows and avoids Xet-specific
# transport failures while the setup scripts fetch the embedding model. setdefault so
# an explicit user setting still wins. Must run before huggingface_hub is imported.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

__version__ = "0.1.0"
