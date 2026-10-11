"""Make the agent/ package root importable when running pytest from agent/."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
