#!/usr/bin/env python3
"""
Combine already-produced BAC SM summary ROOT files.

This version intentionally uses the *original config_sm_summary.yaml* that was
saved in the summary directory (or an explicitly supplied --plotcfg) as the
source of truth for:

  - x range
  - y range / automatic y-range prescription
  - logx / logy
  - x/y titles
  - grids
  - axis divisions
  - legend position
  - entry labels/styles
  - labelmode

This mirrors btl-utils/python/summarize_modules.py as closely as possible.

Output:
  OUTDIR/
    stacked/
      <original plot name>.pdf/.png/.root
    diff_bac/
      <single-entry plot>.pdf/.png/.root
      <multi-entry plot>/
        <entry name>.pdf/.png/.root
    merge_report.txt

"stacked" means BAC histograms with the same entry are added bin-by-bin.
"diff_bac" means one BAC curve per BAC for a single quantity.

Graph ROOT files are also processed. For graphs:
  - stacked/: points from all BACs are concatenated into the same original
    graph entry, then fits/ranges are recomputed exactly from the plot config.
  - diff_bac/: one graph entry is compared across BACs, one BAC color each.
"""

import argparse
import logging
import os
import sys
from pathlib import Path

import numpy
import ROOT

ROOT.gROOT.SetBatch(1)

BACS = ["CIT", "MIB", "PKU", "UVA"]

# Keep one fixed BAC palette for comparison plots.
BAC_COLORS = {
    "CIT": "#f89c20",
    "MIB": "#3f90da",
    "PKU": "#bd1f01",
    "UVA": "#964a8b",
}

utils = None
yaml = None


def load_btl_utils(repo=None):
    """Locate btl-utils/python/utils.py and import it."""
    candidates = []

    if repo:
        p = Path(repo).expanduser().resolve()
        candidates += [p, p / "python"]

    env_repo = os.environ.get("BTL_UTILS")
    if env_repo:
        p = Path(env_repo).expanduser().resolve()
        candidates += [p, p / "python"]

    script_dir = Path(__file__).resolve().parent
    cwd = Path.cwd().resolve()

    candidates += [
        script_dir,
        script_dir / "python",
        cwd / "python",
        cwd,
    ]

    checked = []
    for p in candidates:
        p = p.resolve()

        if p in checked:
            continue
        checked.append(p)

        if (p / "utils.py").is_file():
            sys.path.insert(0, str(p))
            import utils as _utils
            return _utils

    checked_s = "\n  ".join(str(p) for p in checked)
    raise RuntimeError(
        "Could not find btl-utils/python/utils.py.\n"
        "Put this script in btl-utils/python/, run from the repository, or use:\n"
        "  --repo /path/to/btl-utils\n"
        "Checked:\n  " + checked_s
    )


def root_color(value):
    """Convert a config color (ROOT integer or #hex) to a ROOT color index."""
    if isinstance(value, str) and value.startswith("#"):
        return ROOT.TColor.GetColor(value)
    return int(value)


def find_plotcfg(directory):
    """
    Find the config_sm_summary.yaml saved by summarize_modules.py.

    Prefer a file directly in the supplied summary directory. If the supplied
    directory is one level above it, search recursively and choose the
    shallowest match.
    """
    base = Path(directory).expanduser().resolve()

    direct = base / "config_sm_summary.yaml"
    if direct.is_file():
        return direct

    matches = list(base.rglob("config_sm_summary.yaml"))
    if not matches:
        return None

    matches = sorted(
        matches,
        key=lambda p: (len(p.relative_to(base).parts), str(p)),
    )

    if len(matches) > 1:
        logging.warning(
            "Multiple config_sm_summary.yaml files found under %s; using %s",
            base,
            matches[0],
        )

    return matches[0]


def load_plotcfg(path):
    with open(path, "r") as f:
        return yaml.load(f.read())


def collect_hist_roots(directory):
    """
    Find h1_*.root files and map them by plot stem, not relative path.

    Matching by stem fixes the previous problem where identical summary ROOTs
    were missed if BAC directories had different internal nesting.
    """
    base = Path(directory).expanduser().resolve()
    result = {}

    for p in sorted(base.rglob("h1_*.root")):
        stem = p.stem

        if stem in result:
            # Prefer the shallower file but make the ambiguity visible.
            old = result[stem]
            old_depth = len(old.relative_to(base).parts)
            new_depth = len(p.relative_to(base).parts)

            logging.warning(
                "Duplicate plot stem %s in %s:\n  %s\n  %s",
                stem,
                base,
                old,
                p,
            )

            if new_depth < old_depth:
                result[stem] = p
        else:
            result[stem] = p

    return result


def read_histograms(fname, bac):
    """Read every TH1 (but not TH2) from a summary ROOT file."""
    f = ROOT.TFile.Open(str(fname), "READ")

    if not f or f.IsZombie():
        raise RuntimeError(f"Cannot open ROOT file: {fname}")

    result = {}

    for key in f.GetListOfKeys():
        obj = key.ReadObj()

        if obj.InheritsFrom("TH1") and not obj.InheritsFrom("TH2"):
            name = str(obj.GetName())
            h = obj.Clone(f"{name}__{bac}")
            h.SetDirectory(0)
            result[name] = h

    f.Close()
    return result


def compatible_binning(h1, h2):
    if h1.GetNbinsX() != h2.GetNbinsX():
        return False

    a1 = h1.GetXaxis()
    a2 = h2.GetXaxis()

    if abs(a1.GetXmin() - a2.GetXmin()) > 1e-9:
        return False

    if abs(a1.GetXmax() - a2.GetXmax()) > 1e-9:
        return False

    # Also compare variable-bin edges if present.
    xb1 = a1.GetXbins()
    xb2 = a2.GetXbins()

    if xb1.GetSize() != xb2.GetSize():
        return False

    if xb1.GetSize():
        for i in range(xb1.GetSize()):
            if abs(xb1[i] - xb2[i]) > 1e-9:
                return False

    return True


def apply_original_entry_style(hist, entrycfg):
    """Reapply the style originally specified in config_sm_summary.yaml."""
    color = root_color(entrycfg["color"])

    hist.SetOption("hist")
    hist.SetLineWidth(entrycfg.get("linewidth", 2))
    hist.SetLineColor(color)
    hist.SetLineStyle(entrycfg.get("linestyle", 1))
    hist.SetFillColor(color)
    hist.SetFillStyle(entrycfg.get("fillstyle", 0))


def set_stats_title(hist, label, labelmode):
    """
    Reproduce summarize_modules.py's histogram legend statistics formatting.
    """
    mean = hist.GetMean()
    stddev = hist.GetStdDev()

    mean_str = f"{round(mean)}" if mean > 100 else f"{mean:0.2f}"

    if labelmode == "stddev":
        hist.SetTitle(
            f"{label}"
            f"#scale[0.7]{{ [#mu: {mean_str}, #sigma: {stddev:0.2f}]}}"
        )

    elif labelmode == "stddev_by_mean":
        frac = stddev / abs(mean) * 100 if mean else 0.0

        hist.SetTitle(
            f"{label}"
            f"#scale[0.7]{{ [#mu: {mean_str}, #sigma: {stddev:0.2f}, "
            f"#sigma/#mu: {frac:0.2f}%]}}"
        )

    else:
        hist.SetTitle(label)


def plot_ranges(plotcfg, hists):
    """
    EXACT histogram range prescription from summarize_modules.py:

      xrange = (xmin, xmax)
      yrange = (
          plotcfg.get("ymin", 0.5),
          plotcfg.get("ymax", 1e3 * max(hist maximum))
      )
      logy = plotcfg.get("logy", True)

    Handle explicit YAML null safely as "not specified".
    """
    xmin = plotcfg["xmin"]
    xmax = plotcfg["xmax"]

    ymin = plotcfg.get("ymin", None)
    ymax = plotcfg.get("ymax", None)

    if ymin is None:
        ymin = 0.5

    if ymax is None:
        maxbin = max(float(h.GetMaximum()) for h in hists)
        ymax = 1e3 * maxbin

        # Avoid an invalid axis only for pathological all-empty histograms.
        if ymax <= ymin:
            ymax = max(10.0 * ymin, 1.0)

    return (xmin, xmax), (ymin, ymax)


def draw(hists, outbase, plotcfg, legendtitle):
    """Call the repository plotting function with the original plot config."""
    xrange, yrange = plot_ranges(plotcfg, hists)

    outbase.parent.mkdir(parents=True, exist_ok=True)

    logging.info(
        "Drawing %-55s xrange=%s yrange=%s logy=%s",
        str(outbase),
        xrange,
        yrange,
        plotcfg.get("logy", True),
    )

    utils.root_plot1D(
        l_hist=hists,
        outfile=str(outbase) + ".pdf",
        xrange=xrange,
        yrange=yrange,
        logx=plotcfg.get("logx", False),
        logy=plotcfg.get("logy", True),
        xtitle=plotcfg["xtitle"],
        ytitle=plotcfg["ytitle"],
        gridx=plotcfg.get("gridx", True),
        gridy=plotcfg.get("gridy", True),
        ndivisionsx=plotcfg.get("ndivisionsx", None),
        ndivisionsy=plotcfg.get("ndivisionsy", None),
        centerlabelx=plotcfg.get("centerlabelx", False),
        centerlabely=plotcfg.get("centerlabely", False),
        stackdrawopt="nostack",
        legendpos=plotcfg.get("legendpos", "UR"),
        legendncol=1,
        legendfillstyle=0,
        legendfillcolor=0,
        legendtextsize=0.045,
        legendtitle=legendtitle,
        legendheightscale=1.0,
        legendwidthscale=2.0,
        CMSextraText="BTL Internal",
        lumiText="Phase-2",
    )


def make_stacked(
    plotname,
    plotcfg,
    data,
    active_bacs,
    outdir,
    report,
):
    """
    Recreate one original-format plot, but with each entry summed across BACs.
    """
    out_hists = []

    for entryname, entrycfg in plotcfg["entries"].items():
        missing = [
            bac
            for bac in active_bacs
            if entryname not in data[bac]
        ]

        if missing:
            report.append(
                f"STACKED SKIP {plotname}/{entryname}: "
                f"missing TH1 in {', '.join(missing)}"
            )
            return False

        href = data[active_bacs[0]][entryname]
        h = href.Clone(entryname)
        h.SetDirectory(0)

        for bac in active_bacs[1:]:
            h_other = data[bac][entryname]

            if not compatible_binning(h, h_other):
                report.append(
                    f"STACKED SKIP {plotname}/{entryname}: "
                    f"incompatible binning for {bac}"
                )
                return False

            h.Add(h_other)

        apply_original_entry_style(h, entrycfg)
        set_stats_title(
            h,
            entrycfg["label"],
            plotcfg.get("labelmode", None),
        )

        out_hists.append(h)

    legendtitle = (
        "ALL"
        if len(active_bacs) == 4
        else "+".join(active_bacs)
    )

    draw(
        out_hists,
        Path(outdir) / "stacked" / plotname,
        plotcfg,
        legendtitle,
    )

    report.append(
        f"STACKED OK   {plotname}: {len(out_hists)} entr(y/ies)"
    )
    return True


def make_diff_bac(
    plotname,
    plotcfg,
    data,
    active_bacs,
    outdir,
    report,
):
    """
    For each original entry, draw one curve per BAC.

    Single-entry original plots keep their original filename.
    Multi-entry original plots get a directory named exactly after the original
    plot, so they are no longer easy to mistake as "missing":

      diff_bac/h1_lo_LR_bar/
        L_light_yield_vs_bar.*
        R_light_yield_vs_bar.*
        avg_light_yield_vs_bar.*
    """
    n_entries = len(plotcfg["entries"])
    produced = 0

    for entryname, entrycfg in plotcfg["entries"].items():
        missing = [
            bac
            for bac in active_bacs
            if entryname not in data[bac]
        ]

        if missing:
            report.append(
                f"DIFF SKIP    {plotname}/{entryname}: "
                f"missing TH1 in {', '.join(missing)}"
            )
            continue

        hists = []

        # Validate compatible x binning for a meaningful BAC comparison.
        href = data[active_bacs[0]][entryname]

        bad_binning = [
            bac
            for bac in active_bacs[1:]
            if not compatible_binning(href, data[bac][entryname])
        ]

        if bad_binning:
            report.append(
                f"DIFF SKIP    {plotname}/{entryname}: "
                f"incompatible binning in {', '.join(bad_binning)}"
            )
            continue

        for bac in active_bacs:
            h = data[bac][entryname].Clone(f"{entryname}__{bac}")
            h.SetDirectory(0)

            color = ROOT.TColor.GetColor(BAC_COLORS[bac])

            h.SetOption("hist")
            h.SetLineColor(color)
            h.SetLineWidth(3)
            h.SetLineStyle(1)
            h.SetFillColor(color)
            h.SetFillStyle(0)

            set_stats_title(
                h,
                f"{bac}: {entrycfg['label']}",
                plotcfg.get("labelmode", None),
            )

            hists.append(h)

        if n_entries == 1:
            outbase = (
                Path(outdir)
                / "diff_bac"
                / plotname
            )
        else:
            outbase = (
                Path(outdir)
                / "diff_bac"
                / plotname
                / entryname
            )

        draw(
            hists,
            outbase,
            plotcfg,
            "BAC",
        )

        report.append(
            f"DIFF OK      {plotname}/{entryname}: "
            f"{len(hists)} BAC curves"
        )
        produced += 1

    return produced



def collect_graph_roots(directory):
    """Map g1_*.root files by plot stem, independent of directory nesting."""
    base = Path(directory).expanduser().resolve()
    result = {}

    for p in sorted(base.rglob("g1_*.root")):
        stem = p.stem

        if stem in result:
            old = result[stem]
            old_depth = len(old.relative_to(base).parts)
            new_depth = len(p.relative_to(base).parts)

            logging.warning(
                "Duplicate graph plot stem %s in %s:\n  %s\n  %s",
                stem,
                base,
                old,
                p,
            )

            if new_depth < old_depth:
                result[stem] = p
        else:
            result[stem] = p

    return result


def read_graphs(fname, bac):
    """Read every TGraph-like object from a summary ROOT file."""
    f = ROOT.TFile.Open(str(fname), "READ")

    if not f or f.IsZombie():
        raise RuntimeError(f"Cannot open ROOT file: {fname}")

    result = {}

    for key in f.GetListOfKeys():
        obj = key.ReadObj()

        if obj.InheritsFrom("TGraph"):
            name = str(obj.GetName())

            gr = obj.Clone(f"{name}__{bac}")

            # Existing graph ROOTs may already carry fitted TF1s from the
            # single-BAC production. We deliberately remove them, because
            # merged/diff plots must refit their own point set.
            try:
                gr.GetListOfFunctions().Clear()
            except Exception:
                pass

            result[name] = gr

    f.Close()
    return result


def graph_xy(gr):
    """Return graph x/y arrays as numpy arrays."""
    n = int(gr.GetN())

    x = numpy.array(
        [float(gr.GetX()[i]) for i in range(n)],
        dtype=float,
    )

    y = numpy.array(
        [float(gr.GetY()[i]) for i in range(n)],
        dtype=float,
    )

    return x, y


def apply_original_graph_style(gr, entrycfg, color_override=None):
    """Reapply summarize_modules.py graph style from config."""
    color = (
        root_color(color_override)
        if color_override is not None
        else root_color(entrycfg["color"])
    )

    gr.SetLineWidth(entrycfg.get("linewidth", 2))
    gr.SetLineColor(color)
    gr.SetMarkerColor(color)
    gr.SetMarkerSize(entrycfg.get("size", 1))
    gr.SetMarkerStyle(entrycfg.get("marker", 4))
    gr.SetFillStyle(0)

    # ROOT <= 6.30 does not expose TGraph::SetOption reliably. The repository
    # itself stores the graph draw option on the graph's internal histogram.
    gr.GetHistogram().SetOption(entrycfg.get("drawopt", "P"))


def graph_corr_title(gr, label, labelmode):
    """Apply the graph correlation label mode used by summarize_modules.py."""
    if labelmode != "corr":
        gr.SetTitle(label)
        return

    x, y = graph_xy(gr)

    if len(x) >= 2 and numpy.std(x) > 0 and numpy.std(y) > 0:
        corr = numpy.corrcoef(x, y)[0, 1] * 100
        gr.SetTitle(
            f"{label}#scale[0.7]{{ [#rho: {corr:0.2g}%]}}"
        )
    else:
        gr.SetTitle(label)


def fit_graph(gr, entrycfg, plotname, entryname, tag):
    """
    Refit a graph exactly when the original entry config requested a fit.

    summarize_modules.py fits over min(graph x) ... max(graph x), with
    ROOT option 'SEM' and goption 'L', then appends the fitted expression
    to the legend title. We reproduce that here.
    """
    fits = entrycfg.get("fit", {})

    if not fits or gr.GetN() < 2:
        return

    x, _ = graph_xy(gr)

    if not len(x):
        return

    xmin_fn = float(numpy.min(x))
    xmax_fn = float(numpy.max(x))

    if xmax_fn <= xmin_fn:
        return

    for fnname, fnstr in fits.items():
        # Unique ROOT object names avoid collisions when 4 BAC fits coexist.
        safe_tag = str(tag).replace("/", "_").replace(" ", "_")
        unique_name = (
            f"{fnname}_{plotname}_{entryname}_{safe_tag}"
        )

        f1 = ROOT.TF1(
            unique_name,
            fnstr,
            xmin_fn,
            xmax_fn,
        )

        color = int(gr.GetLineColor())

        f1.SetLineWidth(2)
        f1.SetLineStyle(7)
        f1.SetLineColor(color)

        gr.Fit(
            f1,
            "SEM",
            "L",
            xmin_fn,
            xmax_fn,
        )

        fn_expr_str = utils.root_get_fn_expr(
            f1,
            "0.2g",
        )

        gr.SetTitle(
            f"{gr.GetTitle()} "
            f"#scale[0.7]{{[y={fn_expr_str}]}}"
        )


def merge_graph_points(graphs, name):
    """Concatenate points from several BAC TGraphs into one TGraph."""
    out = ROOT.TGraph()
    out.SetName(name)

    for gr in graphs:
        x, y = graph_xy(gr)

        for xx, yy in zip(x, y):
            out.AddPoint(
                float(xx),
                float(yy),
            )

    return out


def graph_ranges(plotcfg, graphs):
    """
    Reproduce summarize_modules.py's graph-range prescription.

    Start from explicit config bounds when present. For bounds set to null,
    derive min/max from all graphs. If an automatically-derived bound has
    |value| > 100, round outward to the next 100 and add one extra 100,
    exactly as the repository does.
    """
    xmin = plotcfg.get("xmin", None)
    xmax = plotcfg.get("xmax", None)
    ymin = plotcfg.get("ymin", None)
    ymax = plotcfg.get("ymax", None)

    all_x = []
    all_y = []

    for gr in graphs:
        x, y = graph_xy(gr)

        if len(x):
            all_x.extend(x.tolist())

        if len(y):
            all_y.extend(y.tolist())

    if not all_x or not all_y:
        raise ValueError("Cannot determine graph range from empty graphs.")

    if plotcfg.get("xmin", None) is None:
        xmin = min(all_x)

    if plotcfg.get("xmax", None) is None:
        xmax = max(all_x)

    if plotcfg.get("ymin", None) is None:
        ymin = min(all_y)

    if plotcfg.get("ymax", None) is None:
        ymax = max(all_y)

    if plotcfg.get("xmin", None) is None and abs(xmin) > 100:
        xmin = 100 * (numpy.floor(xmin / 100) - 1)

    if plotcfg.get("xmax", None) is None and abs(xmax) > 100:
        xmax = 100 * (numpy.ceil(xmax / 100) + 1)

    if plotcfg.get("ymin", None) is None and abs(ymin) > 100:
        ymin = 100 * (numpy.floor(ymin / 100) - 1)

    if plotcfg.get("ymax", None) is None and abs(ymax) > 100:
        ymax = 100 * (numpy.ceil(ymax / 100) + 1)

    # Degenerate ranges are not expected for the current summary config, but
    # protect ROOT from a zero-width dummy histogram.
    if xmax <= xmin:
        delta = 1.0 if xmin == 0 else 0.05 * abs(xmin)
        xmin -= delta
        xmax += delta

    if ymax <= ymin:
        delta = 1.0 if ymin == 0 else 0.05 * abs(ymin)
        ymin -= delta
        ymax += delta

    return (
        (float(xmin), float(xmax)),
        (float(ymin), float(ymax)),
    )


def draw_graphs(
    graphs,
    outbase,
    plotcfg,
    legendtitle,
    dummy_name,
):
    """Draw graphs through the same utils.root_plot1D path as the repo."""
    xrange, yrange = graph_ranges(
        plotcfg,
        graphs,
    )

    outbase.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    logging.info(
        "Drawing %-55s xrange=%s yrange=%s logy=%s",
        str(outbase),
        xrange,
        yrange,
        plotcfg.get("logy", False),
    )

    htmp = ROOT.TH1F(
        dummy_name,
        "",
        1,
        xrange[0],
        xrange[1],
    )
    htmp.SetDirectory(0)

    utils.root_plot1D(
        l_hist=[htmp],
        outfile=str(outbase) + ".pdf",
        xrange=xrange,
        yrange=yrange,
        l_graph_overlay=graphs,
        logx=plotcfg.get("logx", False),
        logy=plotcfg.get("logy", False),
        xtitle=plotcfg["xtitle"],
        ytitle=plotcfg["ytitle"],
        gridx=plotcfg.get("gridx", True),
        gridy=plotcfg.get("gridy", True),
        ndivisionsx=plotcfg.get("ndivisionsx", None),
        ndivisionsy=plotcfg.get("ndivisionsy", None),
        centerlabelx=plotcfg.get("centerlabelx", False),
        centerlabely=plotcfg.get("centerlabely", False),
        stackdrawopt="nostack",
        legendpos=plotcfg.get("legendpos", "UR"),
        legendncol=1,
        legendfillstyle=0,
        legendfillcolor=0,
        legendtextsize=0.045,
        legendtitle=legendtitle,
        legendheightscale=1.0,
        legendwidthscale=1.9,
        CMSextraText="BTL Internal",
        lumiText="Phase-2",
    )


def make_stacked_graph(
    plotname,
    plotcfg,
    data,
    active_bacs,
    outdir,
    report,
):
    """
    Recreate the original graph structure after concatenating BAC point sets.

    Example:
      original g1_lo-avg_vs_barcode has Left / Right / Bar graphs.
      stacked output still has Left / Right / Bar, but each contains points
      from all selected BACs.
    """
    out_graphs = []

    for entryname, entrycfg in plotcfg["entries"].items():
        missing = [
            bac
            for bac in active_bacs
            if entryname not in data[bac]
        ]

        if missing:
            report.append(
                f"STACKED-G SKIP {plotname}/{entryname}: "
                f"missing TGraph in {', '.join(missing)}"
            )
            return False

        gr = merge_graph_points(
            [
                data[bac][entryname]
                for bac in active_bacs
            ],
            entryname,
        )

        apply_original_graph_style(
            gr,
            entrycfg,
        )

        graph_corr_title(
            gr,
            entrycfg["label"],
            plotcfg.get("labelmode", None),
        )

        fit_graph(
            gr,
            entrycfg,
            plotname,
            entryname,
            "ALL",
        )

        out_graphs.append(gr)

    legendtitle = (
        "ALL"
        if len(active_bacs) == 4
        else "+".join(active_bacs)
    )

    draw_graphs(
        out_graphs,
        Path(outdir) / "stacked" / plotname,
        plotcfg,
        legendtitle,
        f"h1_tmp_{plotname}",
    )

    report.append(
        f"STACKED-G OK {plotname}: {len(out_graphs)} entr(y/ies)"
    )

    return True


def make_diff_bac_graph(
    plotname,
    plotcfg,
    data,
    active_bacs,
    outdir,
    report,
):
    """
    Compare one original graph quantity across BACs.

    For a single-entry graph, keep the original plot filename.
    For a multi-entry graph, create:
      diff_bac/<plotname>/<entryname>.pdf/png/root
    """
    n_entries = len(plotcfg["entries"])
    produced = 0

    for entryname, entrycfg in plotcfg["entries"].items():
        missing = [
            bac
            for bac in active_bacs
            if entryname not in data[bac]
        ]

        if missing:
            report.append(
                f"DIFF-G SKIP  {plotname}/{entryname}: "
                f"missing TGraph in {', '.join(missing)}"
            )
            continue

        graphs = []

        for bac in active_bacs:
            original = data[bac][entryname]

            gr = original.Clone(
                f"{entryname}__{bac}"
            )

            try:
                gr.GetListOfFunctions().Clear()
            except Exception:
                pass

            apply_original_graph_style(
                gr,
                entrycfg,
                color_override=BAC_COLORS[bac],
            )

            graph_corr_title(
                gr,
                f"{bac}: {entrycfg['label']}",
                plotcfg.get("labelmode", None),
            )

            fit_graph(
                gr,
                entrycfg,
                plotname,
                entryname,
                bac,
            )

            graphs.append(gr)

        if n_entries == 1:
            outbase = (
                Path(outdir)
                / "diff_bac"
                / plotname
            )
        else:
            outbase = (
                Path(outdir)
                / "diff_bac"
                / plotname
                / entryname
            )

        draw_graphs(
            graphs,
            outbase,
            plotcfg,
            "BAC",
            f"h1_tmp_{plotname}_{entryname}",
        )

        report.append(
            f"DIFF-G OK    {plotname}/{entryname}: "
            f"{len(graphs)} BAC graphs"
        )

        produced += 1

    return produced


def main():
    parser = argparse.ArgumentParser(
        description=(
            "Combine existing btl-utils SM summary ROOT files (TH1 + TGraph), "
            "using the original config_sm_summary.yaml for ranges and style."
        )
    )

    for bac in BACS:
        parser.add_argument(
            f"--{bac}",
            required=False,
            help=f"{bac} SM summary directory",
        )

    parser.add_argument(
        "--repo",
        default=None,
        help=(
            "Path to btl-utils repository. Usually unnecessary if this script "
            "is placed in btl-utils/python/."
        ),
    )

    parser.add_argument(
        "--plotcfg",
        default=None,
        help=(
            "Optional config_sm_summary.yaml. If omitted, use the copy saved "
            "inside the first BAC summary directory."
        ),
    )

    parser.add_argument(
        "--outdir",
        required=True,
        help="Top-level output directory",
    )

    parser.add_argument(
        "--plots",
        nargs="*",
        default=None,
        help=(
            "Optional plot filter, accepting h1_* and/or g1_* names. "
            "By default every configured hist1 and graph plot is processed."
        ),
    )

    parser.add_argument(
        "--only",
        choices=["all", "stacked", "diff_bac"],
        default="all",
        help="Default: create both stacked and diff_bac outputs.",
    )

    args = parser.parse_args()

    global utils, yaml
    utils = load_btl_utils(args.repo)
    yaml = utils.yaml

    active_bacs = [
        bac
        for bac in BACS
        if getattr(args, bac)
    ]

    if len(active_bacs) < 2:
        parser.error(
            "Please provide at least two BAC summary directories."
        )

    if args.plotcfg:
        plotcfg_path = Path(
            args.plotcfg
        ).expanduser().resolve()
    else:
        plotcfg_path = find_plotcfg(
            getattr(args, active_bacs[0])
        )

        if plotcfg_path is None:
            parser.error(
                "Could not find config_sm_summary.yaml in the first BAC "
                "summary directory. Pass it with --plotcfg."
            )

    cfg_all = load_plotcfg(
        plotcfg_path
    )

    selected_cfg = {
        name: cfg
        for name, cfg in cfg_all.items()
        if cfg.get("type") in ("hist1", "graph")
    }

    if args.plots:
        requested = {
            p[:-5] if p.endswith(".root") else p
            for p in args.plots
        }

        selected_cfg = {
            name: cfg
            for name, cfg in selected_cfg.items()
            if name in requested
        }

    n_hist_cfg = sum(
        cfg.get("type") == "hist1"
        for cfg in selected_cfg.values()
    )

    n_graph_cfg = sum(
        cfg.get("type") == "graph"
        for cfg in selected_cfg.values()
    )

    logging.info(
        "Using plot config: %s",
        plotcfg_path,
    )

    logging.info(
        "Configured plots: %d TH1 + %d graph = %d total",
        n_hist_cfg,
        n_graph_cfg,
        len(selected_cfg),
    )

    hist_maps = {
        bac: collect_hist_roots(
            getattr(args, bac)
        )
        for bac in active_bacs
    }

    graph_maps = {
        bac: collect_graph_roots(
            getattr(args, bac)
        )
        for bac in active_bacs
    }

    for bac in active_bacs:
        logging.info(
            "%s: found %d h1_*.root + %d g1_*.root",
            bac,
            len(hist_maps[bac]),
            len(graph_maps[bac]),
        )

    report = [
        "BAC summary merge report",
        "========================",
        f"BACs: {', '.join(active_bacs)}",
        f"Plot config: {plotcfg_path}",
        (
            f"Configured plots: {n_hist_cfg} hist1 + "
            f"{n_graph_cfg} graph = {len(selected_cfg)}"
        ),
        "",
    ]

    n_stacked_hist = 0
    n_diff_hist = 0

    n_stacked_graph = 0
    n_diff_graph = 0

    n_missing_plot = 0
    n_read_error = 0

    for idx, (plotname, plotcfg) in enumerate(
        selected_cfg.items(),
        start=1,
    ):
        ptype = plotcfg.get("type")

        logging.info(
            "[%d/%d] %s (%s)",
            idx,
            len(selected_cfg),
            plotname,
            ptype,
        )

        file_maps = (
            hist_maps
            if ptype == "hist1"
            else graph_maps
        )

        missing_bacs = [
            bac
            for bac in active_bacs
            if plotname not in file_maps[bac]
        ]

        if missing_bacs:
            msg = (
                f"PLOT MISSING {plotname} ({ptype}): "
                f"no ROOT file in {', '.join(missing_bacs)}"
            )

            logging.warning(msg)
            report.append(msg)

            n_missing_plot += 1
            continue

        data = {}

        try:
            for bac in active_bacs:
                if ptype == "hist1":
                    data[bac] = read_histograms(
                        file_maps[bac][plotname],
                        bac,
                    )
                else:
                    data[bac] = read_graphs(
                        file_maps[bac][plotname],
                        bac,
                    )

        except Exception as exc:
            logging.exception(
                "Failed reading %s",
                plotname,
            )

            report.append(
                f"READ ERROR   {plotname}: {exc}"
            )

            n_read_error += 1
            continue

        expected_entries = list(
            plotcfg["entries"].keys()
        )

        for bac in active_bacs:
            extra = sorted(
                set(data[bac])
                - set(expected_entries)
            )

            missing_obj = sorted(
                set(expected_entries)
                - set(data[bac])
            )

            if missing_obj:
                report.append(
                    f"OBJECT MISS  {plotname} [{bac}]: "
                    + ", ".join(missing_obj)
                )

            if extra:
                report.append(
                    f"OBJECT EXTRA {plotname} [{bac}]: "
                    + ", ".join(extra)
                )

        if ptype == "hist1":
            if args.only in ("all", "stacked"):
                if make_stacked(
                    plotname,
                    plotcfg,
                    data,
                    active_bacs,
                    args.outdir,
                    report,
                ):
                    n_stacked_hist += 1

            if args.only in ("all", "diff_bac"):
                n_diff_hist += make_diff_bac(
                    plotname,
                    plotcfg,
                    data,
                    active_bacs,
                    args.outdir,
                    report,
                )

        elif ptype == "graph":
            if args.only in ("all", "stacked"):
                if make_stacked_graph(
                    plotname,
                    plotcfg,
                    data,
                    active_bacs,
                    args.outdir,
                    report,
                ):
                    n_stacked_graph += 1

            if args.only in ("all", "diff_bac"):
                n_diff_graph += make_diff_bac_graph(
                    plotname,
                    plotcfg,
                    data,
                    active_bacs,
                    args.outdir,
                    report,
                )

    report += [
        "",
        "Summary",
        "-------",
        f"Stacked histogram plots: {n_stacked_hist}",
        f"diff_bac histogram entry plots: {n_diff_hist}",
        f"Stacked graph plots: {n_stacked_graph}",
        f"diff_bac graph entry plots: {n_diff_graph}",
        f"Configured plots missing ROOT in >=1 BAC: {n_missing_plot}",
        f"ROOT read errors: {n_read_error}",
    ]

    outdir = Path(
        args.outdir
    )

    outdir.mkdir(
        parents=True,
        exist_ok=True,
    )

    report_path = (
        outdir
        / "merge_report.txt"
    )

    report_path.write_text(
        "\n".join(report)
        + "\n"
    )

    logging.info("Done.")

    logging.info(
        (
            "stacked: %d hist + %d graph | "
            "diff_bac: %d hist-entry + %d graph-entry | "
            "missing: %d | errors: %d"
        ),
        n_stacked_hist,
        n_stacked_graph,
        n_diff_hist,
        n_diff_graph,
        n_missing_plot,
        n_read_error,
    )

    logging.info(
        "Detailed report: %s",
        report_path,
    )


if __name__ == "__main__":
    main()
