"""Reference implementation for the TwinCheck demonstration."""

import sys

# This implementation strips all leading/trailing Unicode whitespace.
sys.stdout.write(sys.stdin.read().strip() + "\n")
