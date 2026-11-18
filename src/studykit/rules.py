"""The core writing rules shipped with this version of the kit."""
from pathlib import Path

PATH = Path(__file__).resolve().parent / "rules" / "writing-rules.md"


def core():
    return PATH.read_text()
