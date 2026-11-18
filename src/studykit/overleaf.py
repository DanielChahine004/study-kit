r"""The paper and its Overleaf project, with the study's markup taken out on the way there
and put back on the way here.

The Overleaf project holds the paper as a collaborator expects to read it: each \fact
printed as its number, each \claim{Key/id} as \citep{Key} (\cite without natbib), each
\claim* gone, and no sources.tex, draft.tex or \input{sources}. This repository keeps the
markup, and nothing in Overleaf has to know about it.

    python -m studykit.overleaf push [paper]             HEAD's paper, plain, onto Overleaf
    python -m studykit.overleaf pull [paper]             Overleaf's edits into the marked-up paper
    python -m studykit.overleaf pull [paper] --accept    the same, taking their text where it
                                                              changed a number or a citation

push adds one commit on top of Overleaf's last, naming the repository commit it was made
from ("Repository-Commit: <sha>"), and refuses while Overleaf holds edits not yet pulled.

pull finds that commit, diffs the plain text pushed then against the plain text there now,
applies the difference to the marked-up text of the same repository commit, and merges
the result into the working tree with git merge-file, so edits made here since are kept.
An Overleaf edit that changes a fact's number, a \claim's citation, or the word a \claim*
follows is not applied: pull lists each one and writes nothing. Undo it in Overleaf, or
take it as written with --accept, which types the number in (sources.py then lists the
sentence as unsourced). Deleting a whole passage that held a fact or a claim is an
ordinary edit, and pull says what went with it. With nothing to resolve, pull commits;
with a merge conflict it leaves the files marked for you to finish and commit.
report/overleaf-sync.json records the Overleaf commit last pulled, which lets the next
push go ahead.

The first push to a project that holds files this repository never pushed needs
--adopt (scripts/overleaf-init.sh passes it).
"""
import difflib
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from pathlib import Path

from studykit.sources import PAPERS, ROOT  # noqa: E402
from studykit.config import paper_dir as P  # noqa: E402  a writeup's folder from its name

LEFT_OUT = {"draft.tex", "sources.tex"}       # at the paper's root; Overleaf never sees them
SYNC = "report/overleaf-sync.json"
TRAILER = "Repository-Commit"


def remote(paper):
    """overleaf for the first paper, overleaf2 for the second, ..."""
    i = PAPERS.index(paper)
    return "overleaf" if i == 0 else f"overleaf{i + 1}"


def git(*args, root=ROOT, data=None, env=None, check=True):
    r = subprocess.run(["git", *args], cwd=root, input=data, capture_output=True, env=env)
    if check and r.returncode:
        raise SystemExit(f"git {' '.join(args)}: {r.stderr.decode(errors='replace').strip()}")
    return r.stdout


def out(*args, **kw):
    return git(*args, **kw).decode().strip()


# --- the markup -------------------------------------------------------------------------

FACTDEF = re.compile(r"^\\factdef\{([^{}]*)\}\{", re.M)
MARKUP = re.compile(r"(?P<input>^[ \t]*\\input\{sources\}[^\n]*\n)"
                    r"|(?P<star>[ \t]*(?:\n[ \t]*)?\\claim\*\{(?P<skeys>[^{}]*)\})"
                    r"|\\claim\{(?P<keys>[^{}]*)\}"
                    r"|\\fact\{(?P<fact>[^{}]*)\}", re.M)
NATBIB = re.compile(r"^[^%\n]*\\usepackage(?:\[[^\]]*\])?\{[^}]*\bnatbib\b", re.M)


class Markup:
    r"""What \fact and \claim print in the journal build, from a commit's sources.tex."""

    def __init__(self, sources_tex, natbib):
        self.values = factdefs(sources_tex)
        self.cite = "\\citep" if natbib else "\\cite"

    def plain(self, m):
        if m["input"] is not None or m["star"] is not None:
            return ""
        if m["keys"] is not None:
            keys = []
            for c in m["keys"].split(","):
                k = c.split("/")[0].strip()
                if k and k not in keys:
                    keys.append(k)
            return f"{self.cite}{{{','.join(keys)}}}"
        if m["fact"] not in self.values:
            raise SystemExit(f"no fact `{m['fact']}' in sources.tex: run step3_outputs/sources.py")
        return self.values[m["fact"]]

    def flatten(self, marked):
        """The plain text, and each span (start, end, marked text, what it is) within it."""
        parts, spans, pos, n = [], [], 0, 0
        for m in MARKUP.finditer(marked):
            if m["fact"] is not None and m["fact"] not in self.values and in_comment(marked, m.start()):
                continue
            parts.append(marked[pos:m.start()])
            n += m.start() - pos
            p = self.plain(m)
            spans.append((n, n + len(p), m.group(0), describe(m)))
            parts.append(p)
            n += len(p)
            pos = m.end()
        parts.append(marked[pos:])
        return "".join(parts), spans


def factdefs(sources_tex):
    """{name: printed value} from each \\factdef{name}{value}{anchor}; a value may span lines."""
    res = {}
    for m in FACTDEF.finditer(sources_tex):
        depth, i = 1, m.end()
        while depth and i < len(sources_tex):
            c = sources_tex[i]
            if c == "\\":
                i += 2
                continue
            depth += {"{": 1, "}": -1}.get(c, 0)
            i += 1
        res[m[1]] = sources_tex[m.end():i - 1]
    return res


def in_comment(text, pos):
    line = text[text.rfind("\n", 0, pos) + 1:pos]
    return re.search(r"(?<!\\)%", line) is not None


def describe(m):
    if m["fact"] is not None:
        return f"\\fact{{{m['fact']}}}"
    if m["keys"] is not None:
        return f"\\claim{{{m['keys']}}}"
    if m["skeys"] is not None:
        return f"\\claim*{{{m['skeys']}}}"
    return "\\input{sources}"


# --- putting it back --------------------------------------------------------------------

TOKEN = re.compile(r"\n|[ \t]+|[A-Za-z]+|\d+|.", re.S)


def tokens(s, cuts=()):
    """(start, end) of each token of s, none crossing a position in cuts."""
    res, a = [], 0
    for b in sorted({c for c in cuts if 0 < c < len(s)}) + [len(s)]:
        res += [(a + m.start(), a + m.end()) for m in TOKEN.finditer(s[a:b])]
        a = b
    return res


def opcodes(A, B):
    """Opcodes from token list A to B: whole lines first, then the tokens of changed lines."""
    def lines(T):
        res, start = [], 0
        for i, t in enumerate(T):
            if t == "\n":
                res.append((start, i + 1))
                start = i + 1
        if start < len(T):
            res.append((start, len(T)))
        return res

    la, lb = lines(A), lines(B)
    ka = ["".join(A[i:j]) for i, j in la]
    kb = ["".join(B[i:j]) for i, j in lb]

    def span(L, n, i1, i2):
        a1 = L[i1][0] if i1 < len(L) else n
        return a1, (L[i2 - 1][1] if i2 > i1 else a1)

    ops = []
    for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, ka, kb, autojunk=False).get_opcodes():
        a1, a2 = span(la, len(A), i1, i2)
        b1, b2 = span(lb, len(B), j1, j2)
        if tag == "equal":
            ops.append(["equal", a1, a2, b1, b2])
            continue
        for t, x1, x2, y1, y2 in difflib.SequenceMatcher(None, A[a1:a2], B[b1:b2], autojunk=False).get_opcodes():
            ops.append([t, a1 + x1, a1 + x2, b1 + y1, b1 + y2])
    merged = []
    for op in ops:
        if op[1] == op[2] and op[3] == op[4]:
            continue
        if merged and op[0] == "equal" == merged[-1][0]:
            merged[-1][2], merged[-1][4] = op[2], op[4]
        else:
            merged.append(op)
    return merged


def unflatten(plain, spans, theirs):
    """theirs (Overleaf's plain text, edited from plain) with the markup of spans put back.

    Returns (text, lost, gone): lost holds (what, line in theirs) for markup an edit changed,
    whose place the text takes; gone holds what was deleted with the passage around it."""
    ta = tokens(plain, [c for s in spans for c in s[:2]])
    A = [plain[a:b] for a, b in ta]
    tb = tokens(theirs)
    B = [theirs[a:b] for a, b in tb]
    ops = opcodes(A, B)
    op_of = [0] * len(A)
    for k, op in enumerate(ops):
        for i in range(op[1], op[2]):
            op_of[i] = k
    first = {a: i for i, (a, _) in enumerate(ta)}
    last = {b: i for i, (_, b) in enumerate(ta)}

    def line(i):
        j = ops[op_of[i]][3] if A else 0
        pos = tb[j][0] if j < len(tb) else len(theirs)
        return theirs.count("\n", 0, pos) + 1

    put, skip, after, lost, gone = {}, set(), defaultdict(list), [], []
    for s, e, marked, what in spans:
        if e > s:
            i, j = first[s], last[e]
            if all(op_of[k] == op_of[i] for k in range(i, j + 1)) and ops[op_of[i]][0] == "equal":
                put[i] = marked
                skip.update(range(i + 1, j + 1))
            elif all(ops[op_of[k]][0] == "delete" for k in range(i, j + 1)):
                gone.append(what)
            else:
                k = next((k for k in range(i, j + 1) if op_of[k] != op_of[i] or ops[op_of[k]][0] != "equal"), i)
                lost.append((what, line(k)))
        elif s == 0 or not A:
            after[-1].append(marked)
        else:
            i = last[s]
            tag = ops[op_of[i]][0]
            if tag == "equal":
                after[i].append(marked)
            elif tag == "delete" and (i + 1 >= len(A) or ops[op_of[i + 1]][0] == "delete"):
                gone.append(what)
            else:
                lost.append((what, line(i)))

    res = list(after[-1])
    for tag, i1, i2, j1, j2 in ops:
        if tag == "equal":
            for i in range(i1, i2):
                if i in put:
                    res.append(put[i])
                elif i not in skip:
                    res.append(A[i])
                res += after.get(i, [])
        else:
            res += B[j1:j2]
    if not A:
        res += B
    return "".join(res), lost, gone


# --- the repository and the project -----------------------------------------------------

def files(treeish, root=ROOT):
    """{path: (mode, blob)} of every file under a tree."""
    res = {}
    for e in git("ls-tree", "-r", "-z", treeish, root=root).decode().split("\0"):
        if e:
            meta, path = e.split("\t", 1)
            mode, _, sha = meta.split()
            res[path] = (mode, sha)
    return res


def blob(spec, root=ROOT):
    r = subprocess.run(["git", "cat-file", "blob", spec], cwd=root, capture_output=True)
    return r.stdout if r.returncode == 0 else None


def markup_at(rev, paper, root=ROOT):
    main = (blob(f"{rev}:{P(paper)}/main.tex", root) or b"").decode()
    return Markup((blob(f"{rev}:{P(paper)}/sources.tex", root) or b"").decode(), bool(NATBIB.search(main)))


def plain_tree(rev, paper, root=ROOT):
    """The tree Overleaf gets for the paper as it is at rev."""
    mk = markup_at(rev, paper, root)
    entries = []
    for path, (mode, sha) in sorted(files(f"{rev}:{P(paper)}", root).items()):
        if path in LEFT_OUT:
            continue
        if path.endswith(".tex"):
            text, _ = mk.flatten(blob(sha, root).decode())
            sha = out("hash-object", "-w", "--stdin", root=root, data=text.encode())
        entries.append(f"{mode} {sha}\t{path}")
    with tempfile.TemporaryDirectory() as d:
        env = {**os.environ, "GIT_INDEX_FILE": str(Path(d) / "index")}
        git("update-index", "--index-info", root=root, env=env, data=("\n".join(entries) + "\n").encode())
        return out("write-tree", root=root, env=env)


def last_push(paper, rem, root=ROOT):
    """(Overleaf commit, repository commit) of the last push, or (None, None)."""
    log = out("log", "--first-parent", "--format=%H%x00%B%x01", f"{rem}/main", root=root)
    for entry in log.split("\x01"):
        if "\x00" in entry:
            h, body = entry.strip().split("\x00", 1)
            m = re.search(rf"^{TRAILER}: ([0-9a-f]{{40}})\s*$", body, re.M)
            if m:
                return h, m[1]
    # pushed before this script: the project held exactly a commit's paper folder
    commits = out("log", "--format=%H", "-n", "500", "HEAD", "--", P(paper), root=root).split()
    trees = out("rev-parse", *[f"{h}:{P(paper)}" for h in commits], root=root).split() if commits else []
    by_tree = {}
    for h, t in zip(commits, trees):
        by_tree.setdefault(t, h)
    for line in out("log", "--first-parent", "--format=%H %T", f"{rem}/main", root=root).splitlines():
        h, t = line.split()
        if t in by_tree:
            return h, by_tree[t]
    return None, None


def synced(root=ROOT, rev=None):
    """report/overleaf-sync.json, from rev or from the working tree."""
    raw = blob(f"{rev}:{SYNC}", root) if rev else ((root / SYNC).read_bytes() if (root / SYNC).exists() else None)
    return json.loads(raw) if raw else {}


def push(paper, rem=None, root=ROOT, adopt=False):
    rem = rem or remote(paper)
    git("fetch", "-q", rem, root=root)
    tip = out("rev-parse", f"{rem}/main", root=root)
    pushed, _ = last_push(paper, rem, root)
    if pushed is None and not adopt and out("ls-tree", tip, root=root):
        raise SystemExit(f"{rem} holds files this repository never pushed: check it, then push with --adopt")
    if pushed is not None and tip != pushed and synced(root, "HEAD").get(paper) != tip:
        n = out("rev-list", "--count", f"{pushed}..{tip}", root=root)
        raise SystemExit(f"{rem} has {n} commit(s) of edits since the last push: pull them first")
    if out("status", "--porcelain", "--", P(paper), root=root):
        print(f"note: uncommitted changes in {P(paper)}/ are not pushed; this pushes HEAD")
    head = out("rev-parse", "HEAD", root=root)
    tree = plain_tree(head, paper, root)
    if tree == out("rev-parse", f"{tip}^{{tree}}", root=root):
        print(f"{paper}: {rem} already has it")
        return 0
    msg = f"{out('log', '-1', '--format=%s', head, root=root)}\n\n{TRAILER}: {head}\n"
    commit = out("commit-tree", tree, "-p", tip, "-m", msg, root=root)
    git("push", "-q", rem, f"{commit}:refs/heads/main", root=root)
    git("fetch", "-q", rem, root=root)
    print(f"{paper}: pushed {head[:7]} to {rem} as {commit[:7]}")
    return 0


def merge_file(ours, base, theirs):
    with tempfile.TemporaryDirectory() as d:
        paths = []
        for name, data in (("ours", ours), ("base", base), ("theirs", theirs)):
            p = Path(d) / name
            p.write_bytes(data)
            paths.append(str(p))
        r = subprocess.run(["git", "merge-file", "-p", "-L", "here", "-L", "pushed", "-L", "overleaf", *paths],
                           capture_output=True)
        if r.returncode < 0:
            raise SystemExit(f"git merge-file failed: {r.stderr.decode()}")
        return r.stdout, r.returncode


def pull(paper, rem=None, root=ROOT, accept=False):
    rem = rem or remote(paper)
    git("fetch", "-q", rem, root=root)
    tip = out("rev-parse", f"{rem}/main", root=root)
    pushed, made = last_push(paper, rem, root)
    if pushed is None:
        raise SystemExit(f"{rem} holds nothing this repository pushed: nothing to pull from")
    if tip == pushed or synced(root).get(paper) == tip:
        print(f"{paper}: nothing new on {rem}")
        return 0
    if plain_tree(made, paper, root) != out("rev-parse", f"{pushed}^{{tree}}", root=root):
        raise SystemExit(f"{rem}'s commit {pushed[:7]} is not the plain paper of {made[:7]}; pull by hand")
    mk = markup_at(made, paper, root)
    base, theirs = files(pushed, root), files(tip, root)
    plan, lost, gone, conflicts = {}, [], [], []
    for path in sorted(set(base) | set(theirs)):
        b, t = base.get(path), theirs.get(path)
        if b == t:
            continue
        dest = root / P(paper) / path
        ours = dest.read_bytes() if dest.exists() else None
        marked = blob(f"{made}:{P(paper)}/{path}", root)
        if t is None:
            if ours == marked or ours is None:
                plan[path] = None
            else:
                conflicts.append(f"{P(paper)}/{path}: deleted in Overleaf, changed here (kept)")
            continue
        new = blob(t[1], root)
        if path.endswith(".tex") and marked is not None:
            plain, spans = mk.flatten(marked.decode())
            text, l, g = unflatten(plain, spans, new.decode())
            lines = new.decode().splitlines()
            lost += [f"{P(paper)}/{path}:{n}  {what} -> Overleaf reads: {lines[n - 1].strip() if n <= len(lines) else ''}"
                     for what, n in l]
            gone += [f"{P(paper)}/{path}: {what}" for what in g]
            new = text.encode()
        if ours == marked:
            plan[path] = new
        elif ours == new:
            continue
        elif ours is None or marked is None or b"\0" in ours + new:
            conflicts.append(f"{P(paper)}/{path}: changed here and in Overleaf (kept this repository's)")
        else:
            merged, n = merge_file(ours, marked, new)
            plan[path] = merged
            if n:
                conflicts.append(f"{P(paper)}/{path}: {n} conflict(s), marked in the file")
    if lost and not accept:
        print(f"{paper}: Overleaf edits that change what the study prints; nothing was written.")
        print("Undo each in Overleaf and pull again, or pull with --accept to take the text as written:")
        print("\n".join("  " + x for x in lost))
        return 1
    for path, data in plan.items():
        dest = root / P(paper) / path
        if data is None:
            dest.unlink(missing_ok=True)
        else:
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
    sync = synced(root)
    sync[paper] = tip
    (root / SYNC).parent.mkdir(parents=True, exist_ok=True)
    (root / SYNC).write_text(json.dumps(sync, indent=1, sort_keys=True) + "\n")
    for x in gone:
        print(f"note: deleted in Overleaf with the passage around it: {x}")
    for x in lost:
        print(f"accepted as written: {x}")
    if conflicts:
        print("\n".join(conflicts))
        print(f"Resolve, then commit {P(paper)}/ and {SYNC}.")
        return 1
    paths = [f"{P(paper)}/{p}" for p in plan] + [SYNC]
    git("add", "-A", "--", *paths, root=root)
    git("commit", "-q", "-m", f"Pull {paper} edits from Overleaf ({tip[:7]})", "--", *paths, root=root)
    print(f"{paper}: pulled {len(plan)} file(s) from {rem}, committed")
    return 0


def main(argv):
    args = [a for a in argv if not a.startswith("-")]
    if not args or args[0] not in ("push", "pull"):
        print(__doc__)
        return 2
    paper = args[1] if len(args) > 1 else next(iter(PAPERS))
    if args[0] == "push":
        return push(paper, adopt="--adopt" in argv)
    return pull(paper, accept="--accept" in argv)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
