"""Intentionally imperfect implementation for the TwinCheck demonstration."""

import sys

# BUG: only ordinary spaces are removed; tabs and line breaks remain.
sys.stdout.write(sys.stdin.read().strip(" ") + "\n")
