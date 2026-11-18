"""The checks every writeup shares, as pytest tests. A repository collects them with

    # tests/test_kit.py
    from studykit.testing import *  # noqa: F401,F403

and configures them in kit.toml (papers, venue limits, exempt names, sizes). Each test is
parametrised over the papers kit.toml lists. A repository's own tests sit beside this file
and can add to these; a check a repository needs to relax is relaxed in kit.toml, not by
editing the kit.

- sources:  every \\fact and \\claim holds, sources.tex is current (writing rules E1, E3, E4)
- figures:  vector PDF, the papers' faces, drawn at the width it prints at
- build:    no undefined or doubled reference, no line into the margin; venue limits
- prose:    abbreviations spelled out at first use (S1), units joined by a thin space
- structure: floats before the references, every figure and table referred to, every appendix reached
- rules:    the repository's copy of the core writing rules is the kit's
"""
import re
import subprocess
import tempfile
from pathlib import Path

import pytest

from studykit import config, rules

_CFG = config.load()
ROOT = _CFG["root"]
PAPERS = sorted(_CFG["papers"])
_ids = dict(ids=str)
TECTONIC = ROOT / ".pixi" / "envs" / "paper" / "bin" / "tectonic"
FACES = re.compile(r"^(LMRoman\d+-\w+|Cm[a-z]+\d+|CM[A-Z]+\d+)$")      # Latin Modern text, Computer Modern math
ACRONYM = re.compile(r"(?<!\w)([A-Za-z]*[A-Z][A-Za-z]*[A-Z][A-Za-z0-9]*?)s?(?!\w)")
UNIT = re.compile(r"\d( ?)(mm|cm|nm|um|m|ps|ns|keV|MeV|GeV|eV|kHz|MHz|GHz|Hz|MBq|Bq)(?!\w)")
REF = re.compile(r"\\(?:ref|eqref|autoref|cref|Cref|pageref)\{([^}]*)\}")
_logs = {}


# --- reading a paper -------------------------------------------------------------------

def tex_files(paper):
    """{name: text, comments stripped} for main.tex and every section it inputs."""
    d = ROOT / paper
    main = (d / "main.tex").read_text()
    out = {"main.tex": main, **{f"sections/{m}.tex": (d / "sections" / f"{m}.tex").read_text()
                                for m in re.findall(r"\\input\{sections/([^}]+)\}", main)}}
    return {f: re.sub(r"(?<!\\)%.*", "", t) for f, t in out.items()}


def plain(tex):
    """Prose only: no comments, references, citations, facts, math or commands."""
    tex = re.sub(r"(?<!\\)%.*", "", tex)
    tex = re.sub(r"\\(?:cite[a-z]*|claim\*?|ref|eqref|label|fact|studyfig|input|includegraphics|begin|end)\*?"
                 r"(?:\[[^\]]*\])*\{[^}]*\}", " ", tex)
    tex = re.sub(r"\$[^$]*\$", " ", tex)
    return re.sub(r"\\[a-zA-Z]+\*?", " ", tex)


def abstract(paper):
    m = re.search(r"\\begin\{abstract\}(.*?)\\end\{abstract\}", (ROOT / paper / "main.tex").read_text(), re.S)
    return m.group(1) if m else ""


def introduction(paper):
    return next((f.read_text() for f in sorted((ROOT / paper / "sections").glob("*.tex"))
                 if re.search(r"\\section\{Introduction\}", f.read_text())), "")


def built(paper):
    """The paper's build log, from one tectonic build into a temporary folder (seconds)."""
    if paper not in _logs:
        if not TECTONIC.exists():
            pytest.skip("no paper environment here (pixi install -e paper)")
        out = Path(tempfile.mkdtemp())
        subprocess.run([str(TECTONIC), "--keep-logs", "--outdir", str(out), str(ROOT / paper / "main.tex")],
                       check=True, capture_output=True)
        _logs[paper] = (out / "main.log").read_text(errors="replace")
    return _logs[paper]


def referred(texts):
    return {k.strip() for t in texts for g in REF.findall(t) for k in g.split(",")}


# --- sources: E1, E3, E4 ---------------------------------------------------------------

@pytest.mark.parametrize("paper", [p for p in PAPERS if "facts" in _CFG["papers"][p]], **_ids)
def test_sources_are_current(paper):
    from studykit import sources as S
    assert (ROOT / paper / "sources.tex").read_text() == S.render_tex(paper, S.facts(paper)), \
        f"{paper}/sources.tex is stale: run step3_outputs/sources.py {paper}"


@pytest.mark.parametrize("paper", [p for p in PAPERS if "facts" in _CFG["papers"][p]], **_ids)
def test_every_fact_and_claim_holds(paper):
    """Every \\fact is defined and used, and every \\claim names a real, undisputed annotation
    whose paper is in the bibliography and whose value its sentence states."""
    from studykit import sources as S
    problems, _ = S.check(paper, S.facts(paper))
    assert not problems, "\n".join(problems)


# --- structure -------------------------------------------------------------------------

@pytest.mark.parametrize("paper", PAPERS, **_ids)
def test_floats_stay_before_the_references(paper):
    """placeins keeps floats in their section and a FloatBarrier flushes them before the bibliography."""
    main = (ROOT / paper / "main.tex").read_text()
    assert re.search(r"\\usepackage\[[^]]*section[^]]*\]\{placeins\}", main), f"{paper}/main.tex lacks \\usepackage[section]{{placeins}}"
    bib = main.index("\\bibliography{")
    assert "\\FloatBarrier" in main[:bib], f"{paper}/main.tex needs \\FloatBarrier before \\bibliography"


@pytest.mark.parametrize("paper", PAPERS, **_ids)
def test_every_table_and_figure_is_referred_to(paper):
    fs = tex_files(paper)
    labels = re.findall(r"\\label\{((?:fig|tab):[^}]*)\}", "\n".join(fs.values()))
    lost = sorted(set(labels) - referred(fs.values()))
    assert not lost, f"{paper}: tables or figures nothing refers to: {lost}"


@pytest.mark.parametrize("paper", PAPERS, **_ids)
def test_every_appendix_is_reached_from_the_main_text(paper):
    fs = tex_files(paper)
    body = referred(t for f, t in fs.items() if "appendix" not in f)
    lost = [f for f, t in fs.items() if "appendix" in f and not set(re.findall(r"\\label\{([^}]*)\}", t)) & body]
    assert not lost, f"{paper}: appendices the main text never points into: {lost}"


# --- figures ---------------------------------------------------------------------------

def _text_width_in(paper):
    m = re.search(r"\\usepackage\[margin=([\d.]+)cm\]\{geometry\}", (ROOT / paper / "main.tex").read_text())
    assert m, f"{paper}: no a4 margin=...cm geometry to take the text width from"
    return 210 / 25.4 - 2 * float(m.group(1)) / 2.54


def _printed(paper):
    tex = "".join(tex_files(paper).values())
    for opt, name in re.findall(r"\\(?:studyfig|includegraphics)(?:\[([^\]]*)\])?\{([^}#]+)\}", tex):
        w = re.search(r"([\d.]*)\\(?:linewidth|textwidth)", opt or "")
        yield (ROOT / paper / "figures" / (name if Path(name).suffix else name + ".pdf"),
               float(w.group(1) or 1) if w else 1.0)


@pytest.mark.parametrize("paper", PAPERS, **_ids)
def test_figures_are_vector_pdf_in_the_papers_faces_at_print_size(paper):
    """A PNG, a fallback font or a figure scaled to fit fails here (studykit.figures makes them right)."""
    width = _text_width_in(paper)
    for f, frac in _printed(paper):
        rel = f.relative_to(ROOT)
        assert f.suffix == ".pdf", f"{rel}: figures are vector PDF, not {f.suffix}"
        assert f.exists(), f"{rel}: missing; run step3_outputs/figures.py"
        pdf = f.read_bytes()
        box = re.search(rb"/MediaBox \[\s*([\d.]+) [\d.]+ ([\d.]+) [\d.]+", pdf)
        drawn = (float(box.group(2)) - float(box.group(1))) / 72
        assert abs(drawn - frac * width) <= 0.03 * width, (
            f"{rel}: drawn {drawn:.2f} in wide but printed at {frac * width:.2f} in; draw it at the width it prints at")
        faces = {n.decode().split("+")[-1] for n in re.findall(rb"/BaseFont /([\w+-]+)", pdf)}
        stray = sorted(n for n in faces if not FACES.match(n))
        assert not stray, f"{rel}: letters in {stray}; use studykit.figures"
    for f in (ROOT / paper / "figures").glob("[!.]*"):
        assert f.suffix == ".pdf", f"{f.relative_to(ROOT)}: figures are vector PDF"


# --- build and venue -------------------------------------------------------------------

@pytest.mark.parametrize("paper", PAPERS, **_ids)
def test_build_is_clean(paper):
    log = built(paper)
    bad = re.findall(r"LaTeX Warning: (?:Reference|Citation) `[^']+' (?:on page \d+ )?undefined[^\n]*"
                     r"|LaTeX Warning: Label `[^']+' multiply defined", log)
    assert not bad, f"{paper}: " + "; ".join(sorted(set(bad)))
    limit = _CFG["checks"]["overfull_pt"]
    over = [(float(w), where) for w, where in re.findall(r"Overfull \\hbox \(([\d.]+)pt too wide\) (in [^\n]*)", log)
            if float(w) > limit]
    assert not over, f"{paper}: lines into the margin: " + "; ".join(f"{w:.1f} pt {where}" for w, where in over)


@pytest.mark.parametrize("paper", PAPERS, **_ids)
def test_within_venue_limits(paper):
    lim = _CFG["papers"][paper]
    if "abstract_words" in lim:
        n = len(re.findall(r"[A-Za-z0-9][\w.'’–-]*", plain(re.sub(r"\\fact\{[^}]*\}", " 0 ", abstract(paper)))))
        assert n <= lim["abstract_words"], f"{paper}: abstract is {n} words, the limit is {lim['abstract_words']}"
    if "pages" in lim:
        pages = int(re.findall(r"\((\d+) pages?", built(paper))[-1])
        assert pages <= lim["pages"], f"{paper}: {pages} pages, the limit is {lim['pages']}"


# --- prose -----------------------------------------------------------------------------

@pytest.mark.parametrize("paper", PAPERS, **_ids)
def test_abbreviations_spelled_out_at_first_use(paper):
    """Writing rule S1: in the abstract and again in the introduction, an abbreviation's first
    use sits inside its expansion; kit.toml [checks] names lists what is named, not abbreviated."""
    names, bad = set(_CFG["checks"]["names"]), []
    for part, tex in (("abstract", abstract(paper)), ("introduction", introduction(paper))):
        text, seen = plain(tex), set()
        for m in ACRONYM.finditer(text):
            a = m.group(1)
            if a in seen or a in names:
                continue
            seen.add(a)
            if text[m.start() - 1:m.start()] != "(":
                bad.append(f"{part}: {a} ({' '.join(text[max(0, m.start() - 40):m.end()].split())})")
    assert not bad, f"{paper}: first use not inside its expansion: " + "; ".join(bad)


@pytest.mark.parametrize("paper", PAPERS, **_ids)
def test_units_joined_by_a_thin_space(paper):
    """511\\,keV, not 511 keV or 511keV: the thin space keeps a number and its unit on one line."""
    bad = []
    body = (ROOT / paper / "main.tex").read_text().split("\\begin{document}")[-1]
    for name, tex in [("main.tex", body), *((f.name, f.read_text()) for f in sorted((ROOT / paper / "sections").glob("*.tex")))]:
        for i, line in enumerate(tex.split("\n"), 1):
            line = re.sub(r"(?<!\\)%.*", "", line)
            line = re.sub(r"\\(?:fact|cite[a-z]*|claim\*?|ref|label)\*?\{[^}]*\}", "0", line)   # names, not numbers
            line = re.sub(r"\$[^$]*\$", " ", line)
            bad += [f"{name}:{i}: {line[max(0, m.start() - 20):m.end()]}" for m in UNIT.finditer(line)]
    assert not bad, f"{paper}: units not joined by \\,: " + "; ".join(bad)


# --- the rules -------------------------------------------------------------------------

def test_writing_rules_copy_is_the_kits():
    """The repository's copy of the core rules is the installed kit's; `python -m studykit update` refreshes it."""
    copy = ROOT / _CFG["rules"]["copy"]
    assert copy.exists() and copy.read_text() == rules.core(), \
        f"{copy.relative_to(ROOT)} is not the kit's core rules: run `pixi run kit-update`"
