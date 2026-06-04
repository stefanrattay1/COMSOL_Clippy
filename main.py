#!/usr/bin/env python3
"""Entry point launched by the MCP client and the setup scripts.

Usage:
    python main.py serve              # start the MCP server over stdio
    python main.py ingest             # build/repair the vectorstore (incremental)
    python main.py query "..."        # standalone search from the CLI
    python main.py status             # environment + store health check
"""
from comsol_clippy.cli import app

if __name__ == "__main__":
    app()
