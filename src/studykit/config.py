"""A repository's study-kit settings: kit.toml at its root.

    [papers.paper1]                       # one table per writeup, by name
    facts = "step3_outputs.facts1"        # its facts module (studykit.sources); none for claims only
    dir = "paper1"                        # its folder, if not the name (a thesis: "src/thesis")
    pages = 28                            # venue limits, if any (studykit.testing)
    abstract_words = 300

    [checks]                              # optional; these are the defaults
    names = ["GATE"]                      # named, not abbreviated: exempt from S1
    overfull_pt = 1.0
    min_text_pt = 6.5

    [rules]
    copy = "report/writing-rules.md"      # where `python -m studykit update` puts the core rules

The root is the nearest directory at or above the working directory that holds kit.toml.
"""
import tomllib
from pathlib import Path

DEFAULTS = {"names": ["GATE"], "overfull_pt": 1.0, "min_text_pt": 6.5}


def root(start=None):
    here = Path(start or Path.cwd()).resolve()
    for d in (here, *here.parents):
        if (d / "kit.toml").exists():
            return d
    return here


def load(start=None):
    r = root(start)
    f = r / "kit.toml"
    cfg = tomllib.loads(f.read_text()) if f.exists() else {}
    cfg.setdefault("papers", {})
    cfg["checks"] = {**DEFAULTS, **cfg.get("checks", {})}
    cfg.setdefault("rules", {}).setdefault("copy", "report/writing-rules.md")
    cfg["root"] = r
    return cfg


def facts_modules(cfg=None):
    cfg = cfg or load()
    return {p: v["facts"] for p, v in cfg["papers"].items() if "facts" in v}


def paper_dir(name, cfg=None):
    """The writeup's folder, relative to the root: its `dir`, else its name."""
    cfg = cfg or load()
    return cfg["papers"].get(name, {}).get("dir", name)
