"""python -m studykit status     this repository's kit version against the newest release
python -m studykit rules      copy the installed kit's core rules to kit.toml's [rules] copy
python -m studykit bump       pin pixi.toml to the newest release (then pixi install; `pixi run
                              kit-update` does all three)"""
import json
import re
import subprocess
import sys
import time
from pathlib import Path

from studykit import REPO, __version__, config, rules

CACHE = Path.home() / ".cache" / "study-kit" / "latest.json"


def latest(max_age=86400):
    """The newest release tag, from GitHub at most once a day; None when it cannot be reached."""
    try:
        c = json.loads(CACHE.read_text())
        if time.time() - c["at"] < max_age:
            return c["tag"]
    except Exception:
        pass
    try:
        out = subprocess.run(["git", "ls-remote", "--tags", "--refs", REPO + ".git"], capture_output=True,
                             text=True, timeout=5).stdout
    except Exception:
        return None
    tags = sorted(re.findall(r"refs/tags/v(\d+)\.(\d+)\.(\d+)", out), key=lambda v: tuple(map(int, v)))
    if not tags:
        return None
    tag = "v" + ".".join(tags[-1])
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    CACHE.write_text(json.dumps({"tag": tag, "at": time.time()}))
    return tag


def status_line():
    new = latest()
    mine = "v" + __version__
    if new and tuple(map(int, new[1:].split("."))) > tuple(map(int, __version__.split("."))):
        return f"study-kit {mine}; {new} is out: pixi run kit-update"
    return f"study-kit {mine}" + ("" if new else " (could not check for a newer one)")


def copy_rules():
    cfg = config.load()
    dest = cfg["root"] / cfg["rules"]["copy"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(rules.core())
    print(f"wrote {dest.relative_to(cfg['root'])} from study-kit v{__version__}")


def bump():
    new = latest(max_age=0)
    if not new:
        sys.exit("could not reach GitHub for the newest study-kit release")
    p = config.root() / "pixi.toml"
    t = p.read_text()
    t2 = re.sub(r'(study-kit\s*=\s*\{[^}]*tag\s*=\s*")[^"]*(")', rf"\g<1>{new}\2", t)
    if t2 == t and new not in t:
        sys.exit("no study-kit pin with a tag in pixi.toml")
    p.write_text(t2)
    print(f"pixi.toml pins study-kit {new}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"status": lambda: print(status_line()), "rules": copy_rules, "bump": bump}[cmd]()
