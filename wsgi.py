"""Vercel's native Flask entry point. No schema or migration work at import."""
from app import create_app
# This deployment entry point always fails closed, even if Vercel system variables are hidden.
# Local SQLite development continues through `python -m app` / run.sh.
app = create_app({'PRODUCTION': True})
