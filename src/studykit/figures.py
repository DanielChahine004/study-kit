"""Figures that match the writeup: vector PDF, lettered in the papers' faces (Latin Modern
Roman 8 for text, Computer Modern math), on a transparent background, saved only when no
legend covers the data, no lettering is below the minimum size and none is cropped at the edge.

    from studykit.figures import plt, save     # plt is matplotlib.pyplot with the kit style applied
    fig, ax = plt.subplots(figsize=(6.3, 2.4))  # drawn at the width it prints at
    ...
    save(fig, OUT / "name.pdf")

Write symbols the text face lacks (l, sigma, alpha, approx) as mathtext, $\\ell$.
A repository can change the minimum text size in kit.toml ([checks] min_text_pt).
"""
import logging
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib import font_manager  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.path import Path as MPath  # noqa: E402
from matplotlib.text import Text  # noqa: E402

from studykit import config  # noqa: E402

FONTS = Path(__file__).resolve().parent / "fonts"
STYLE = {"font.family": "Latin Modern Roman", "mathtext.fontset": "cm", "axes.formatter.use_mathtext": True,
         "pdf.fonttype": 42, "figure.facecolor": "none", "axes.facecolor": "none",
         "font.size": 8, "legend.fontsize": 7}

logging.getLogger("fontTools").setLevel(logging.ERROR)    # the Latin Modern files carry old timestamps it warns about
for _f in FONTS.glob("*.otf"):
    font_manager.fontManager.addfont(_f)
plt.rcParams.update(STYLE)


def legends_clear(fig):
    """Fails if a legend covers a plotted line, marker or point: move the legend to an empty
    corner or above the panels (fig.legend(loc="outside upper center")), or give it room."""
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    inside = lambda box, xy: any(box.contains(x, y) for x, y in xy[np.isfinite(xy).all(axis=1)])
    for leg in [ax.get_legend() for ax in fig.axes if ax.get_legend()] + list(fig.legends):
        box = leg.get_window_extent(r)
        for ax in fig.axes:
            if not box.overlaps(ax.get_window_extent(r)):
                continue
            for art in [*ax.lines, *ax.collections]:
                if not art.get_visible():
                    continue
                if isinstance(art, Line2D):
                    xy = art.get_transform().transform(np.asarray(art.get_xydata(), float))
                    xy = xy[np.isfinite(xy).all(axis=1)]
                    joined = art.get_linestyle() not in ("None", "none", "", " ") and len(xy) > 1
                    hit = MPath(xy).intersects_bbox(box, filled=False) if joined else inside(box, xy)
                elif len(art.get_offsets()) and len(art.get_paths()) <= 1:     # markers: where they sit
                    hit = inside(box, art.get_offset_transform().transform(np.asarray(art.get_offsets(), float)))
                else:                                                          # lines and bars: their paths
                    t = art.get_transform()
                    hit = any(p.transformed(t).intersects_bbox(box, filled=False) for p in art.get_paths())
                what = art.get_label() if not str(art.get_label()).startswith("_") else type(art).__name__
                assert not hit, f"the legend covers {what!r} in panel {ax.get_title(loc='left') or ax.get_title()!r}"


def text_large_enough(fig, min_pt=None):
    """Fails if any lettering, tick labels included, is set below the minimum size."""
    min_pt = min_pt or config.load()["checks"]["min_text_pt"]
    small = sorted({(round(x.get_fontsize(), 1), x.get_text()[:30]) for x in fig.findobj(Text)
                    if x.get_visible() and x.get_text().strip() and x.get_fontsize() < min_pt})
    assert not small, f"text below {min_pt} pt: {small[:5]}"


def lettering_inside(fig, tol_in=0.01):
    """Fails if anything drawn, lettering and legends included, reaches past the edge of the figure,
    where the PDF crops it (a legend anchored above the panels, a suptitle with no room): give it room
    with fig.tight_layout(rect=...) or a taller figure."""
    fig.canvas.draw()
    t, f = fig.get_tightbbox(fig.canvas.get_renderer()), fig.bbox_inches
    over = {"left": f.x0 - t.x0, "bottom": f.y0 - t.y0, "right": t.x1 - f.x1, "top": t.y1 - f.y1}
    out = {k: round(v, 2) for k, v in over.items() if v > tol_in}
    assert not out, f"cropped at the figure edge, by inches: {out}"


def save(fig, path, **kw):
    """Every figure is saved through here: legend and text-size checks, then a PDF with no
    creation timestamp, so an unchanged figure is byte-identical on rerun."""
    legends_clear(fig)
    text_large_enough(fig)
    if kw.get("bbox_inches") != "tight":                     # a tight box grows to fit, so nothing is cropped
        lettering_inside(fig)
    fig.savefig(path, metadata={"CreationDate": None}, **kw)
