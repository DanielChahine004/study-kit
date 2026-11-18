"""The kit's own checks: its rules ship, its figure style saves a clean figure and refuses a covered one."""
import pytest

from studykit import rules
from studykit.figures import legends_clear, plt, save


def test_rules_ship_with_the_kit():
    assert rules.core().startswith("# Writing rules")


def test_a_clean_figure_saves(tmp_path):
    fig, ax = plt.subplots(figsize=(3, 2))
    ax.plot([0, 1], [0, 0.1], label="low")
    ax.set_ylim(0, 1)
    ax.legend(loc="upper right")
    save(fig, tmp_path / "f.pdf")
    assert (tmp_path / "f.pdf").read_bytes().startswith(b"%PDF")


def test_a_legend_over_the_data_is_refused():
    fig, ax = plt.subplots(figsize=(3, 2))
    ax.plot([0, 1], [0, 1], label="diagonal")
    ax.legend(loc="center")
    with pytest.raises(AssertionError, match="legend covers"):
        legends_clear(fig)
