"""COMSOL Clippy — local RAG over COMSOL manuals with an MCP search server."""

import os

# Route Hugging Face downloads through the plain HTTPS path instead of Xet. The
# embedding model is pinned to an old transformers (its trust_remote_code reads
# config.rope_theta, removed in transformers 5.x), which in turn caps
# huggingface_hub < 1.0 — and that old hub still calls the deprecated
# hf_xet.download_files(), emitting a DeprecationWarning on every model fetch.
# Disabling Xet sidesteps that code path entirely (regular download, no warning)
# without changing any pins. setdefault so an explicit user setting still wins.
# Must run before huggingface_hub is imported, hence here at package import.
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")

__version__ = "0.1.0"
