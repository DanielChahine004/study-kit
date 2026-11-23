"""python -m studykit status     this repository's kit version against the newest release
python -m studykit rules      copy the installed kit's core rules to kit.toml's [rules] copy
python -m studykit bump       pin pixi.toml to the newest release (then pixi install; `pixi run
                              kit-update` does all three)
python -m studykit sync       before the tests: move to a newer release if one is out (asks GitHub
                              every run, under a second); never fails, and does nothing offline, in CI,
                              or with STUDYKIT_NO_UPDATE=1"""
import json
import os
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
                             text=True, timeout=3).stdout
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
    if newer(new):
        return f"study-kit {mine}; {new} is out: pixi run kit-update"
    return f"study-kit {mine}" + ("" if new else " (could not check for a newer one)")


def copy_rules():
    cfg = config.load()
    dest = cfg["root"] / cfg["rules"]["copy"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(rules.core())
    print(f"wrote {dest.relative_to(cfg['root'])} from study-kit v{__version__}")


def newer(tag):
    return bool(tag) and tuple(map(int, tag[1:].split("."))) > tuple(map(int, __version__.split(".")))


def bump(new=None):
    new = new or latest(max_age=0)
    if not new:
        sys.exit("could not reach GitHub for the newest study-kit release")
    p = config.root() / "pixi.toml"
    t = p.read_text()
    t2 = re.sub(r'(study-kit\s*=\s*\{[^}]*tag\s*=\s*")[^"]*(")', rf"\g<1>{new}\2", t)
    if t2 == t and new not in t:
        sys.exit("no study-kit pin with a tag in pixi.toml")
    p.write_text(t2)
    print(f"pixi.toml pins study-kit {new}")


def sync():
    """Run before the tests (the `test` task), so a study picks up kit fixes when it is worked on.
    The rules are copied by a fresh interpreter, which loads the newly installed kit."""
    if os.environ.get("STUDYKIT_NO_UPDATE") or os.environ.get("CI"):
        return
    new = latest(max_age=0)
    if not newer(new):
        return
    try:
        bump(new)
        root = config.root()
        subprocess.run(["pixi", "install"], cwd=root, check=True)
        subprocess.run(["pixi", "run", "python", "-m", "studykit", "rules"], cwd=root, check=True)
    except (Exception, SystemExit) as e:
        print(f"study-kit: could not move to {new} ({e}); testing against v{__version__}")
        return
    print(f"study-kit updated v{__version__} -> {new}: commit pixi.toml, pixi.lock and the rules copy")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "status"
    {"status": lambda: print(status_line()), "rules": copy_rules, "bump": bump, "sync": sync}[cmd]()
