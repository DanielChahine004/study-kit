# study-kit

What every writeup shares, in one place, so the study repositories, the paper
repositories and the thesis hold the same rules and checks:

- **writing rules** (`studykit/rules/writing-rules.md`), the core rubric every
  writeup follows; each repository adds an annex, `writing-terms.md`, that can
  override a rule by id or add its own (L1, L2, ...);
- **figures** (`studykit.figures`): vector PDF lettered in the papers' faces
  (Latin Modern Roman 8, Computer Modern math), and `save()`, which refuses a
  figure whose legend covers its data or whose lettering is too small;
- **sources** (`studykit.sources`): every `\fact` from a facts function, every
  `\claim` against the paperstore's annotations;
- **Overleaf sync** (`studykit.overleaf`): the paper goes to Overleaf without
  its markup and comes back with it;
- **tests** (`studykit.testing`): the checks above, plus a clean build, venue
  limits, abbreviations spelled out at first use and units joined by a thin
  space.

## Using it in a repository

```toml
# pixi.toml
[pypi-dependencies]
study-kit = { git = "https://github.com/DanielChahine004/study-kit.git", tag = "v1.0.0" }

[tasks]
kit-update = "python -m studykit bump && pixi install && pixi run python -m studykit rules"
```

```toml
# kit.toml, at the repository root
[papers.paper]
facts = "step3_outputs.facts"
abstract_words = 300

[checks]
names = ["GATE"]          # named, not abbreviated
```

```python
# tests/test_kit.py
from studykit.testing import *  # noqa: F401,F403
```

The version is pinned, so a change here reaches a repository only when it runs
`pixi run kit-update`; every test run's header says when a newer release is out.
A repository relaxes a check in `kit.toml`, never by editing the kit.

## Releasing

Edit, bump `version` in `pyproject.toml` and `src/studykit/__init__.py`, commit,
tag `vX.Y.Z`, push the tag.
