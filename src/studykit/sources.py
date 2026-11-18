r"""Where the manuscript's numbers and claims come from, said in the manuscript.

Three commands carry it, and nothing else is needed:

    \cite{Key}        the standard citation: a paper as a whole.
    \claim{Key/id}    this sentence rests on one passage of a paper: an
                      annotation in the paperstore (thesis-papers), whose quote
                      `paperstore check` holds to its page. It prints the
                      citation, as \citep{Key} would (\cite without natbib). \claim*{Key/id} prints
                      nothing, for a sentence that already cites Key; several
                      at once are \claim{A/x,B/y}.
    \fact{name}       a number from this study, printed from the result, input
                      or code it is computed from. It is never typed, so it
                      cannot drift from the study.

A fact is computed by a function in the paper's facts module
(step3_outputs/facts.py) that returns {name: LaTeX}. Every file the function opens while it
runs is recorded as a source of its facts; `code()` adds a constant or default
read from code. This script writes:

    <paper>/sources.tex          the two commands, and every fact's value
    report/sources-<paper>.md    for each fact, its value, where the paper uses
                                 it, the code that computes it and the files it
                                 read, linked at the commit that last changed
                                 them; each claim with its sentence and quote;
                                 and the numbers the paper states with no source
    report/sources-<paper>.json  the same as data, for the paperstore viewer's
                                 study mode (?study=owner/repo)

The journal build prints values and citations and nothing more. The draft
build (<paper>/draft.tex) marks each one and links it: a claim to its quote in
the paperstore viewer, a fact to its entry in the sources sheet.

    python -m studykit.sources            write both files
    python -m studykit.sources --check    and exit 1 on any problem

The checks: every \fact is defined and every fact used; every \claim names an
annotation in the paperstore, not disputed, whose paper is in the paper's
references.bib; a claim whose annotation records a value sits in a sentence
that states it, if the sentence states any number; and a \claim* sits in a
paragraph that cites its paper. Claims are checked where the paperstore is
($PAPERSTORE, else ../thesis-papers) and skipped, with a note, where it is
not (CI).
"""
from __future__ import annotations

import importlib
import inspect
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from studykit import config as _config

_CFG = _config.load()
ROOT = _CFG["root"]                       # the repository using the kit (kit.toml)
sys.path.insert(0, str(ROOT))

VIEWER = "https://danielchahine004.github.io/paperstore/"     # where a \claim's link opens its quote
# the paperstore whose annotations \claim names: $PAPERSTORE, else a checkout beside this one
STORE = Path(os.environ.get("PAPERSTORE", ROOT.parent / "thesis-papers"))


def repo_url():
    """This repository on GitHub, from its origin remote (links in the sources sheet)."""
    r = subprocess.run(["git", "remote", "get-url", "origin"], cwd=ROOT, capture_output=True, text=True)
    url = r.stdout.strip().removesuffix(".git")
    m = re.match(r"(?:git@github\.com:|https://github\.com/)(.+)", url)
    return f"https://github.com/{m.group(1)}" if m else url
FACTS_MODULE = _config.facts_modules(_CFG)   # paper -> facts module, from kit.toml
PAPERS = list(_CFG["papers"])               # every writeup, facts or not


def pdir(paper):
    """The writeup's folder (kit.toml `dir`, else its name)."""
    return ROOT / _config.paper_dir(paper, _CFG)


# --- recording what a fact reads ----------------------------------------------------

_reading: list[set] = []


def _audit(event, args):
    if not _reading or event != "open":
        return
    path = args[0]
    if isinstance(path, int):
        return
    try:
        p = Path(os.fsdecode(path)).resolve()
        rel = p.relative_to(ROOT).as_posix()
    except (ValueError, TypeError, OSError):
        return
    if p.suffix not in (".py", ".pyc"):
        _reading[-1].add(rel)


sys.addaudithook(_audit)


def code(obj, name=None):
    """A value read from code: a module constant (`code(study, "REF")`) or a
    function's default (`code(crlb.evaluate, "fom_inset_mm")`). Recorded as a
    source, at the line that sets it."""
    if inspect.ismodule(obj):
        value = getattr(obj, name)
        src = inspect.getsourcefile(obj)
        lines = Path(src).read_text().splitlines()
        line = next((i for i, l in enumerate(lines, 1) if re.match(rf"{re.escape(name)}\s*[:=]", l)), 1)
    else:
        value = inspect.signature(obj).parameters[name].default
        src = inspect.getsourcefile(obj)
        first = inspect.getsourcelines(obj)[1]
        lines = inspect.getsourcelines(obj)[0]
        line = first + next((i for i, l in enumerate(lines) if re.search(rf"\b{re.escape(name)}\b", l)), 0)
    if _reading:
        _reading[-1].add(f"{Path(src).resolve().relative_to(ROOT).as_posix()}#L{line}")
    return value


@dataclass
class Fact:
    name: str
    value: str          # LaTeX, as the paper prints it
    code: str           # path#Lnn of the function that computes it
    reads: list = field(default_factory=list)


class Facts:
    """A paper's facts: `@F` on a function returning {name: LaTeX}."""

    def __init__(self):
        self.makers = []

    def __call__(self, fn):
        self.makers.append(fn)
        return fn

    def compute(self) -> dict[str, Fact]:
        out = {}
        for fn in self.makers:
            _reading.append(set())
            try:
                values = fn()
            finally:
                reads = _reading.pop()
            where = f"{Path(inspect.getsourcefile(fn)).resolve().relative_to(ROOT).as_posix()}#L{inspect.getsourcelines(fn)[1]}"
            for name, value in values.items():
                if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9 .\-]*", name):
                    raise ValueError(f"fact name {name!r}: letters, digits, spaces, dots and hyphens only")
                if name in out:
                    raise ValueError(f"fact {name!r} is made twice ({out[name].code}, {where})")
                out[name] = Fact(name, str(value), where, sorted(reads))
        return out


def facts(paper) -> dict[str, Fact]:
    """The paper's facts; none for a writeup with no facts module (claims only, as the thesis)."""
    if paper not in FACTS_MODULE:
        return {}
    return importlib.import_module(FACTS_MODULE[paper]).F.compute()


# --- reading the manuscript ---------------------------------------------------------

COMMAND = re.compile(r"\\(fact|claim)(\*?)\{([^}]*)\}")
CITE = re.compile(r"\\cite[a-zA-Z]*\*?(?:\[[^\]]*\])*\{([^}]*)\}")


def strip_comments(line):
    return re.sub(r"(?<!\\)%.*", "", line)


def files(paper):
    """main.tex and the sections (a paper) or chapters (a thesis) it is made of."""
    d = pdir(paper)
    return [d / "main.tex"] + sorted((d / "sections").glob("*.tex")) + sorted((d / "chapters").glob("*.tex"))


@dataclass
class Use:
    kind: str           # fact | claim
    star: bool
    arg: str
    file: str
    line: int
    paragraph: str      # the paragraph it sits in, comments removed, on one line
    sentence: str


def paragraphs(text):
    """(start line, paragraph text) for each blank-line-separated block."""
    out, cur, start = [], [], 1
    for i, raw in enumerate(text.splitlines(), 1):
        line = strip_comments(raw)
        if line.strip():
            if not cur:
                start = i
            cur.append(line.strip())
        elif cur:
            out.append((start, cur)); cur = []
    if cur:
        out.append((start, cur))
    return out


SENTENCE_END = re.compile(r"(?<=[.!?])\s+(?=[A-Z\\$(])")


def uses(paper) -> list[Use]:
    found = []
    for f in files(paper):
        for start, lines in paragraphs(f.read_text()):
            para = " ".join(lines)
            sentences = SENTENCE_END.split(para)
            for k, line in enumerate(lines):
                for m in COMMAND.finditer(line):
                    # the sentence holding it: the one whose text contains this occurrence
                    pos = len(" ".join(lines[:k])) + (1 if k else 0) + m.start()
                    acc, sent = 0, para
                    for s in sentences:
                        i = para.find(s, acc)
                        if i <= pos <= i + len(s):
                            sent = s; break
                        acc = i + len(s)
                    found.append(Use(m.group(1), bool(m.group(2)), m.group(3).strip(),
                                     f.relative_to(ROOT).as_posix(), start + k, para, sent))
    return found


def expand(text, fx):
    return re.sub(r"\\fact\{([^}]*)\}", lambda m: fx[m.group(1)].value if m.group(1) in fx else "??", text)


NUMBER = re.compile(r"(?<![A-Za-z\\\d.])\d+(?:\.\d+)?")


def numbers(text):
    """The numbers a sentence states, with commands' arguments that are names removed."""
    text = re.sub(r"\\(?:claim\*?|cite[a-zA-Z]*|ref|eqref|label|input|studyfig|figsrc|begin|end|section|subsection)(?:\[[^\]]*\])*\{[^}]*\}", " ", text)
    text = re.sub(r"\\[A-Za-z]+", " ", text)      # \times50 is 50
    return [float(n) for n in NUMBER.findall(text)]


# --- the paperstore -----------------------------------------------------------------

def annotations():
    """{"Key/id": annotation} from the paperstore, or None where there is none."""
    d = STORE / "annotations"
    if not d.is_dir():
        return None
    out = {}
    for f in d.glob("*.json"):
        doc = json.loads(f.read_text(encoding="utf-8"))
        for a in doc.get("annotations", []):
            out[f"{doc.get('paper', f.stem)}/{a['id']}"] = a
    return out


def bib_keys(paper):
    bib = pdir(paper) / "references.bib"
    return set(re.findall(r"^@\w+\{([^,\s]+)", bib.read_text(), re.M)) if bib.exists() else set()


def _bib_dois(bib):
    """{key: doi} of a .bib file, DOIs lower-cased."""
    if not bib.exists():
        return {}
    out = {}
    for m in re.finditer(r"^@\w+\{([^,\s]+),(.*?)^\}", bib.read_text(), re.M | re.S):
        d = re.search(r"\bdoi\s*=\s*[{\"]([^}\"]+)", m.group(2), re.I)
        if d:
            out[m.group(1)] = d.group(1).strip().lower()
    return out


def aliases(paper):
    """{paperstore key: this paper's key for the same paper}, matched by DOI, for a writeup whose
    citation keys follow another convention than the store's (johnson2024celeritas, Johnson2024)."""
    mine = {d: k for k, d in _bib_dois(pdir(paper) / "references.bib").items()}
    return {sk: mine[d] for sk, d in _bib_dois(STORE / "references.bib").items() if d in mine and mine[d] != sk}


def unclaimable(paper):
    """Keys whose entry cannot carry a \\claim: a book or unpublished work, with no PDF to quote."""
    bib = pdir(paper) / "references.bib"
    return set(re.findall(r"^@(?:book|unpublished|misc)\{([^,\s]+)", bib.read_text(), re.M | re.I)) if bib.exists() else set()


def unclaimed(paper):
    """(file, line, sentence, keys) for each sentence citing a paper that no \\claim in it names: a
    citation the reader cannot follow to the passage it rests on."""
    out, skip, alias = [], unclaimable(paper), aliases(paper)
    for f in files(paper):
        for start, lines in paragraphs(f.read_text()):
            for s in SENTENCE_END.split(" ".join(lines)):
                named = {alias.get(c.strip().split("/")[0], c.strip().split("/")[0])
                         for g in re.findall(r"\\claim\*?\{([^}]*)\}", s) for c in g.split(",")}
                keys = [k.strip() for m in CITE.finditer(s) for k in m.group(1).split(",")]
                keys = [k for k in dict.fromkeys(keys) if k and k not in named and k not in skip]
                if keys:
                    line = start + next((k for k, l in enumerate(lines) if s[:30] in l), 0)
                    out.append((f.relative_to(ROOT).as_posix(), line, s, keys))
    return out


def value(a):
    """(number, unit) an annotation records, or (None, '')."""
    v = a.get("value")
    if isinstance(v, dict):
        return v.get("number"), v.get("unit") or ""
    return v, a.get("unit") or ""


def claim_refs(use):
    return [c.strip() for c in use.arg.split(",") if c.strip()]


# --- checking -----------------------------------------------------------------------

def check(paper, fx=None, ann=...):
    """(problems, notes): what is wrong, and what could not be checked."""
    fx = facts(paper) if fx is None else fx
    ann = annotations() if ann is ... else ann
    us = uses(paper)
    problems, notes = [], []
    used = {u.arg for u in us if u.kind == "fact"}
    for u in us:
        at = f"{u.file}:{u.line}"
        if u.kind == "fact":
            if u.arg not in fx:
                problems.append(f"{at}: \\fact{{{u.arg}}}: no such fact in {FACTS_MODULE[paper]}")
            continue
        refs = claim_refs(u)
        if not refs:
            problems.append(f"{at}: \\claim with nothing in it")
        alias = aliases(paper)
        keys = bib_keys(paper) | set(alias)
        for ref in refs:
            if not re.fullmatch(r"[^/\s]+/[^/\s]+", ref):
                problems.append(f"{at}: \\claim{{{ref}}}: write Key/id, as the paperstore names an annotation")
                continue
            key = ref.split("/")[0]
            if key not in keys:
                problems.append(f"{at}: \\claim{{{ref}}}: {key} is not in {paper}/references.bib")
            if u.star:
                cited = {k.strip() for m in CITE.finditer(u.paragraph) for k in m.group(1).split(",")}
                cited |= {c.split("/")[0] for m in COMMAND.finditer(u.paragraph) if m.group(1) == "claim" and not m.group(2)
                          for c in m.group(3).split(",")}
                if key not in cited and alias.get(key) not in cited:
                    problems.append(f"{at}: \\claim*{{{ref}}}: the paragraph does not cite {key}; use \\claim to cite it")
            if ann is None:
                continue
            a = ann.get(ref)
            if a is None:
                problems.append(f"{at}: \\claim{{{ref}}}: no such annotation in {STORE.name}")
                continue
            if a.get("status") == "disputed":
                problems.append(f"{at}: \\claim{{{ref}}}: the annotation is marked disputed")
            v, unit = value(a)
            if v is not None:
                said = numbers(expand(u.sentence, fx))
                try:
                    v = float(v)
                except (TypeError, ValueError):
                    continue
                if said and not any(abs(n - v) <= 1e-9 * max(1, abs(v)) for n in said):
                    problems.append(f"{at}: \\claim{{{ref}}}: the paper says {v:g}{(' ' + unit) if unit else ''}, "
                                    f"the sentence says {', '.join(f'{n:g}' for n in said)}")
    for name in sorted(set(fx) - used):
        problems.append(f"{FACTS_MODULE[paper]}: fact {name!r} is not used by {paper}: use it with \\fact{{{name}}} or remove it")
    if ann is None and any(u.kind == "claim" for u in us):
        notes.append(f"claims not checked against annotations: no paperstore at {STORE} (set PAPERSTORE)")
    return problems, notes


# --- writing ------------------------------------------------------------------------

def slug(name):
    """GitHub's anchor for a heading."""
    return re.sub(r"[^a-z0-9 _-]", "", name.lower()).replace(" ", "-")


def sheet_url(paper):
    return f"{repo_url()}/blob/main/report/sources-{paper}.md"


def render_tex(paper, fx):
    L = [
        "% Generated by step3_outputs/sources.py from the facts in "
        f"{FACTS_MODULE[paper].replace('.', '/')}.py -- do not edit." if paper in FACTS_MODULE else
        "% Generated by study-kit (studykit.sources): the \\claim commands -- do not edit.",
        "%   \\fact{name}      a number from this study, printed from what computes it",
        "%   \\claim{Key/id}   this sentence rests on that annotation in the paperstore; prints \\citep{Key}",
        "%   \\claim*{Key/id}  the same, printing nothing (the sentence cites Key already)",
        "% The draft build (draft.tex, which sets \\sourcesdraft to 1) marks and links each: a claim by a link on a",
        "% white mark after its sentence (a link on blank space is dropped), from which the paperstore viewer highlights the sentence.",
        "\\makeatletter",
        "\\providecommand\\sourcesdraft{0}",
        "% in the draft, citations are coloured like the facts; references to sections, figures and equations stay black",
        "\\ifnum\\sourcesdraft=1 \\hypersetup{colorlinks,citecolor=violet,linkcolor=black,urlcolor=black,filecolor=black}\\fi",
        f"\\newcommand\\sourcesheet{{{sheet_url(paper)}}}",
        f"\\newcommand\\claimviewer{{{VIEWER}}}",
        "\\newcommand\\factdef[3]{\\@namedef{src@f@#1}{#2}\\@namedef{src@a@#1}{#3}}",
        "\\newcommand\\fact[1]{\\@ifundefined{src@f@#1}%",
        "  {\\textbf{\\textcolor{red}{[#1?]}}\\PackageWarning{sources}{no fact `#1': run step3_outputs/sources.py}}%",
        "  {\\ifnum\\sourcesdraft=1 \\ifmmode\\mbox{\\href{\\sourcesheet\\#\\@nameuse{src@a@#1}}{\\textcolor{teal}{$\\@nameuse{src@f@#1}$}}}%",
        "   \\else\\href{\\sourcesheet\\#\\@nameuse{src@a@#1}}{\\textcolor{teal}{\\@nameuse{src@f@#1}}}\\fi%",
        "   \\else\\@nameuse{src@f@#1}\\fi}}",
        "\\newcommand\\claim{\\@ifstar{\\src@claim0}{\\src@claim1}}",
        "\\def\\src@claim#1#2{\\def\\src@keys{}\\def\\src@marks{}%",
        "  \\@for\\src@c:=#2\\do{\\expandafter\\src@one\\src@c\\@nil}%",
        "  \\ifnum#1=1 \\@ifundefined{citep}{\\expandafter\\cite}{\\expandafter\\citep}\\expandafter{\\src@keys}\\else\\ifnum\\sourcesdraft=0 \\unskip\\fi\\fi",
        "  \\ifnum\\sourcesdraft=1 \\src@marks\\fi}",
        "\\def\\src@one#1/#2\\@nil{\\edef\\src@k{\\zap@space#1 \\@empty}%",
        "  \\@expandtwoargs\\in@{,\\src@k,}{,\\src@keys,}%",
        "  \\ifin@\\else\\ifx\\src@keys\\@empty\\edef\\src@keys{\\src@k}\\else\\edef\\src@keys{\\src@keys,\\src@k}\\fi\\fi",
        "  \\ifx\\src@marks\\@empty\\def\\src@marks{\\textsuperscript{\\href{\\claimviewer\\#/#1/#2}{\\textcolor{white}{\\tiny$\\blacktriangleright$}}}}\\fi}",
        "\\makeatother",
        "",
    ]
    for name in sorted(fx):
        L.append(f"\\factdef{{{name}}}{{{fx[name].value}}}{{{slug(name)}}}")
    return "\n".join(L) + "\n"


def last_commit(paths):
    """{path: short commit that last changed it}, '' where it is uncommitted."""
    out = {}
    for p in paths:
        r = subprocess.run(["git", "log", "-1", "--format=%h", "--", p], cwd=ROOT, capture_output=True, text=True)
        out[p] = r.stdout.strip()
    return out


def link(ref, commits):
    path, _, line = ref.partition("#")
    c = commits.get(path, "")
    url = f"{repo_url()}/blob/{c or 'main'}/{path}" + (f"#{line}" if line else "")
    return f"[`{ref}`]({url})" + (f" @ `{c}`" if c else " (uncommitted)")


def unsourced(paper):
    """(file, line, sentence) for each sentence with a number and no \\fact, \\claim or \\cite."""
    out = []
    for f in files(paper):
        for start, lines in paragraphs(f.read_text()):
            para = " ".join(lines)
            if para.startswith("\\") and not re.search(r"[a-z]{3,} [a-z]{3,} [a-z]{3,}", para):
                continue    # preamble and float boilerplate, not prose
            for s in SENTENCE_END.split(para):
                if re.search(r"\\(fact|claim|cite)", s) or not numbers(s):
                    continue
                if re.match(r"\\(usepackage|newcommand|renewcommand|documentclass|setcitestyle|input|DeclareMath|def|counterwithin)", s):
                    continue
                line = start + next((k for k, l in enumerate(lines) if s[:30] in l), 0)
                out.append((f.relative_to(ROOT).as_posix(), line, s))
    return out


def given(paper):
    """The sentences marked as stating given numbers (a design input, a label, a threshold),
    one per line of report/given-<paper>.txt, as unsourced() prints them. The paperstore
    viewer's "given" button adds a line; an edit to the sentence brings it back to the list."""
    p = ROOT / "report" / f"given-{paper}.txt"
    lines = p.read_text(encoding="utf-8").splitlines() if p.exists() else []
    return {" ".join(x.split()) for x in lines if x.strip() and not x.startswith("#")}


def split_unsourced(paper):
    """unsourced(paper) as (still to look at, marked given)."""
    marked, loose, ok = given(paper), [], []
    for f, line, s in unsourced(paper):
        (ok if " ".join(s.split()) in marked else loose).append((f, line, s))
    return loose, ok


def render_sheet(paper, fx, us, ann):
    commits = last_commit(sorted({r.split("#")[0] for f in fx.values() for r in f.reads + [f.code]}))
    where = {}
    for u in us:
        if u.kind == "fact":
            where.setdefault(u.arg, []).append(f"{u.file}:{u.line}")
    L = [f"# Sources of {paper}", "",
         "*Generated by `step3_outputs/sources.py` -- do not edit. Every `\\claim` in the manuscript with "
         "the passage it rests on, every `\\fact` with the code that computes it and the files it read "
         "(at the commit that last changed each), and the sentences that state a number with no source. "
         "The draft PDF links each claim and fact here.*", ""]
    claims = [u for u in us if u.kind == "claim"]
    L += ["## Claims", ""]
    if not claims:
        L += ["None yet.", ""]
    for u in claims:
        L += [f"**{u.file}:{u.line}** {'(`\\claim*`) ' if u.star else ''}{u.sentence}", ""]
        for ref in claim_refs(u):
            a = (ann or {}).get(ref)
            head = f"[`{ref}`]({VIEWER}#/{ref})"
            if a is None:
                L += [f"- {head}: " + ("not found" if ann is not None else "paperstore not available here")]
                continue
            q = a.get("quote", {}).get("exact") if a.get("kind") == "quote" else f"(a box: {a.get('note', 'figure')})"
            v, unit = value(a)
            val = f" · value {v:g}{(' ' + unit) if unit else ''}" if isinstance(v, (int, float)) else ""
            L += [f"- {head}, p. {a.get('page', '?')}, {a.get('status', 'unchecked')}{val}: \"{q}\""]
        L += [""]
    L += ["## Facts", ""]
    for name in sorted(fx):
        f = fx[name]
        L += [f"### {name}", "",
              f"`{f.value}` · used at {', '.join(where.get(name, [])) or 'nowhere'}", "",
              f"- computed by {link(f.code, commits)}"]
        L += [f"- reads {link(r, commits)}" for r in f.reads]
        L += [""]
    loose, ok = split_unsourced(paper)
    L += ["## Numbers with no source", "",
          f"{len(loose)} sentences state a number with no `\\fact`, `\\claim` or `\\cite`, and {len(ok)} more "
          f"are marked as stating given numbers (report/given-{paper}.txt). Some are names "
          "(a design, an equation); the rest are typed numbers to turn into facts or claims.", "",
          "<details><summary>the sentences</summary>", ""]
    L += [f"- {f}:{line}: {s[:240]}" for f, line, s in loose]
    L += ["", "</details>", ""]
    return "\n".join(L)


def title(paper):
    """The manuscript's \\title{...}, braces balanced, or ''."""
    text = (pdir(paper) / "main.tex").read_text()
    i = text.find("\\title{")
    if i < 0:
        return ""
    i, depth, out = i + len("\\title{"), 1, ""
    while i < len(text) and depth:
        c = text[i]
        depth += c == "{"
        depth -= c == "}"
        if depth:
            out += c
        i += 1
    return " ".join(out.replace("\\\\", " ").split())


def render_json(paper, fx, us):
    """The sheet as data, for the paperstore viewer's study mode (?study=owner/repo): every
    fact with where its code and files are, every claim with the numbers its sentence
    states (the viewer checks them against the annotations it reads), the sentences with
    no source, and the problems found without the paperstore."""
    refs = {r for f in fx.values() for r in f.reads + [f.code]}
    commits = last_commit(sorted({r.split("#")[0] for r in refs}))

    def at(ref):
        path, _, line = ref.partition("#")
        return {"path": path, "line": int(line[1:]) if line.startswith("L") else None, "commit": commits.get(path, "")}

    where = {}
    for u in us:
        if u.kind == "fact":
            where.setdefault(u.arg, []).append(f"{u.file}:{u.line}")
    problems, _ = check(paper, fx, ann=None)
    return json.dumps({
        "paper": paper,
        "title": title(paper),
        "repo": repo_url(),
        "draft": f"{_config.paper_dir(paper, _CFG)}/draft.pdf",
        "facts": {name: {"value": f.value, "slug": slug(name), "code": at(f.code), "reads": [at(r) for r in f.reads],
                         "used": where.get(name, [])} for name, f in sorted(fx.items())},
        "claims": [{"file": u.file, "line": u.line, "star": u.star, "sentence": u.sentence, "refs": claim_refs(u),
                    "said": numbers(expand(u.sentence, fx))} for u in us if u.kind == "claim"],
        "unsourced": [{"file": f, "line": line, "sentence": s} for f, line, s in split_unsourced(paper)[0]],
        "given": [{"file": f, "line": line, "sentence": s} for f, line, s in split_unsourced(paper)[1]],
        "given_file": f"report/given-{paper}.txt",
        "unclaimed": [{"file": f, "line": line, "sentence": s, "keys": keys} for f, line, s, keys in unclaimed(paper)],
        "problems": problems,
    }, indent=1, ensure_ascii=False) + "\n"


def write(paper):
    fx = facts(paper)
    (pdir(paper) / "sources.tex").write_text(render_tex(paper, fx))
    us = uses(paper)
    (ROOT / "report" / f"sources-{paper}.md").write_text(render_sheet(paper, fx, us, annotations()))
    (ROOT / "report" / f"sources-{paper}.json").write_text(render_json(paper, fx, us), encoding="utf-8")
    return fx


def main(argv):
    paper = next((a for a in argv if not a.startswith("-")), next(iter(PAPERS), "paper"))
    fx = write(paper)
    print(f"wrote {_config.paper_dir(paper, _CFG)}/sources.tex and report/sources-{paper}.md, .json: {len(fx)} facts")
    problems, notes = check(paper, fx)
    for n in notes:
        print("note:", n)
    for p in problems:
        print("problem:", p)
    if "--check" in argv and problems:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
