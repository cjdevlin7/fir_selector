#!/usr/bin/env python3
"""
FIR Selector — pick a color, click/search FIRs, export a PNG.

Interactive step (browser): Leaflet map served from a simplified GeoJSON
(data/firs_simplified.geojson, built by preprocess_firs.py) for fast
rendering of all 284 FIR polygons.

Export step (server): re-renders the *full-resolution* FIR geometries
(data/Global_FIRs.geojson) with matplotlib + cartopy, in the same dark
map style as Global_Maps.py / FIR_Base_Map.py (from the SPVHF_Stats
project), so the PNG matches that deck aesthetic at full detail.

Run:
    python3 app.py
    -> http://localhost:5002
"""

import colorsys
import gc
import io
import json
import os
import subprocess
from datetime import datetime, timezone

from flask import Flask, jsonify, render_template, request, send_file
from PIL import Image

import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import geopandas as gpd

HERE            = os.path.dirname(os.path.abspath(__file__))
SIMPLIFIED_PATH = os.path.join(HERE, "data", "firs_simplified.geojson")
FULLRES_PATH    = os.path.join(HERE, "data", "Global_FIRs.geojson")
LOGO_WHITE_PATH = os.path.join(HERE, "static", "img", "aireon_logo_white.png")
LOGO_DARK_PATH  = os.path.join(HERE, "static", "img", "aireon_logo_dark.png")

# ── Map style (matches Global_Maps.py) ─────────────────────────────────────
MAP_BG       = "#1C242B"
COAST_COLOR  = "#3E4650"
BORDER_COLOR = "#343C44"
FIR_EDGE_CLR = "#4A5568"
FIR_EDGE_A   = 0.45
FIR_EDGE_W   = 0.30

FIG_W, FIG_H = 24, 12
DPI          = 150  # 3600x1800 output — the free Render tier's 512MB cap leaves
                     # little headroom (a single render + logo composite peaks
                     # around 420MB at DPI 200 vs ~340MB here); indistinguishable
                     # at this resolution since it's still well above screen/deck use.

# How far export geometry is simplified before rendering. At 4800px wide, one
# pixel already covers ~0.075° of longitude, so detail finer than this is
# invisible in the output anyway — simplifying first cuts the in-memory
# GeoDataFrame from ~146MB to a fraction of that (341,859 -> ~72,000 points).
EXPORT_SIMPLIFY_TOLERANCE = 0.005

app = Flask(__name__)


def _shade(hex_color, delta):
    """Lighten (delta>0) or darken (delta<0) a hex color in HSL space."""
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    h, l, s = colorsys.rgb_to_hls(r, g, b)
    l = max(0.0, min(1.0, l + delta))
    r, g, b = colorsys.hls_to_rgb(h, l, s)
    return "#{:02x}{:02x}{:02x}".format(round(r * 255), round(g * 255), round(b * 255))


def _is_dark(hex_color):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) / 255 for i in (0, 2, 4))
    _, l, _ = colorsys.rgb_to_hls(r, g, b)
    return l < 0.5


def _land_ocean_tones(bg_color):
    """Land/ocean fills a shade off the background, so continents read as
    shapes (like the CartoDB tiles on the interactive map) instead of
    disappearing into a flat background."""
    if _is_dark(bg_color):
        return _shade(bg_color, 0.07), _shade(bg_color, -0.04)  # land lighter, ocean darker
    return _shade(bg_color, -0.06), _shade(bg_color, 0.05)      # land darker, ocean lighter


def _composite_logo(png_bytes, bg_color):
    """Paste the Aireon logo (white on dark backgrounds, dark on light ones)
    in the bottom-right corner, sized to stay legible without dominating.
    Shifted left of the true corner so it lands on the solid body of
    Antarctica rather than the jagged coastline right at the edge."""
    im = Image.open(io.BytesIO(png_bytes)).convert("RGBA")
    logo_path = LOGO_WHITE_PATH if _is_dark(bg_color) else LOGO_DARK_PATH
    logo = Image.open(logo_path).convert("RGBA")

    target_w = round(im.width * 0.12)
    target_h = round(logo.height * (target_w / logo.width))
    logo = logo.resize((target_w, target_h), Image.LANCZOS)

    margin_right = round(im.width * 0.09)
    margin_bottom = round(im.width * 0.015)
    pos = (im.width - logo.width - margin_right, im.height - logo.height - margin_bottom)
    im.alpha_composite(logo, pos)

    out = io.BytesIO()
    im.convert("RGB").save(out, format="PNG")
    out.seek(0)
    return out


def _get_version():
    """Short git commit hash — Render sets RENDER_GIT_COMMIT automatically
    on every deploy, so this always reflects what's actually running."""
    commit = os.environ.get("RENDER_GIT_COMMIT")
    if commit:
        return commit[:7]
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=HERE, stderr=subprocess.DEVNULL
        ).decode().strip()
    except Exception:
        return "dev"


APP_VERSION = _get_version()
DEPLOYED_AT = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")  # process start time

# Newest first. Add an entry here with each user-visible change.
CHANGELOG = [
    {
        "date": "2026-08-18",
        "items": [
            "Reduced export memory usage (lower render DPI, simplified export "
            "geometry, periodic worker recycling) to fix out-of-memory crashes "
            "on the free hosting tier — no visible change in output quality.",
        ],
    },
    {
        "date": "2026-08-18",
        "items": [
            "Added an \"Include Aireon Logo\" option — white on dark backgrounds, "
            "dark on light ones — shown as a live preview in the map's corner and "
            "included in the exported PNG when checked.",
        ],
    },
    {
        "date": "2026-08-18",
        "items": [
            "Added this Change Log page, and a How-To page linked above the title.",
            "Picking a background color now re-themes the live map preview (dark/light tiles), not just the exported PNG.",
            "Fixed FIR selection breaking after scrolling into a repeated copy of the world map (e.g. reaching Australia from the left) — the map is now clamped to a single copy.",
        ],
    },
    {
        "date": "2026-08-18",
        "items": [
            "Fixed a bug where an exported FIR could render tiny and offset from the map beneath it.",
            "Land and ocean now render in distinct tones instead of a single flat color, matching the interactive map more closely.",
        ],
    },
    {
        "date": "2026-08-18",
        "items": [
            "Added the version number and deploy time shown under the Export PNG button.",
        ],
    },
    {
        "date": "2026-08-18",
        "items": [
            "Fixed the first PNG export after the app had been idle sometimes failing.",
        ],
    },
    {
        "date": "2026-08-18",
        "items": [
            "Initial release: color palette, FIR search/select by name, ICAO id, or map click, and full-resolution PNG export.",
        ],
    },
]

_fullres_gdf = None  # lazy-loaded, cached full-resolution FIR GeoDataFrame


def get_fullres_gdf():
    global _fullres_gdf
    if _fullres_gdf is None:
        gdf = gpd.read_file(FULLRES_PATH).to_crs("EPSG:4326")
        with open(FULLRES_PATH) as f:
            raw = json.load(f)
        raw_ids = [feat.get("id") for feat in raw["features"]]
        gdf["id"] = raw_ids
        gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
        gdf["geometry"] = gdf.geometry.simplify(EXPORT_SIMPLIFY_TOLERANCE, preserve_topology=True)
        _fullres_gdf = gdf
    return _fullres_gdf


@app.route("/")
def index():
    return render_template("index.html", version=APP_VERSION, deployed_at=DEPLOYED_AT)


@app.route("/how-to")
def how_to():
    return render_template("how_to.html")


@app.route("/changelog")
def changelog():
    return render_template("changelog.html", version=APP_VERSION,
                            deployed_at=DEPLOYED_AT, entries=CHANGELOG)


@app.route("/api/firs")
def api_firs():
    """Simplified FIR polygons for the interactive map."""
    with open(SIMPLIFIED_PATH) as f:
        data = json.load(f)
    return jsonify(data)


@app.route("/api/render", methods=["POST"])
def api_render():
    """
    Render the full-resolution FIR map with custom per-FIR colors.

    Body: {
      "selections": { "<fir id>": "#rrggbb", ... },
      "background": "#1C242B",   (optional)
      "include_logo": false      (optional)
    }
    """
    payload      = request.get_json(force=True) or {}
    selections   = payload.get("selections", {})
    bg_color     = payload.get("background") or MAP_BG
    include_logo = bool(payload.get("include_logo"))

    gdf = get_fullres_gdf()

    mpl.rcParams["agg.path.chunksize"] = 10000
    fig = plt.figure(figsize=(FIG_W, FIG_H), dpi=DPI)
    ax = plt.axes([0, 0, 1, 1], projection=ccrs.PlateCarree())
    ax.set_global()
    # geopandas .plot() on a small FIR subset overwrites ax.dataLim instead of
    # unioning with it; with the default equal+datalim aspect that shrinks the
    # axes' box to fit the last-plotted subset, squeezing the whole map into a
    # sliver (worst for polygons near the poles/dateline). 'auto' aspect makes
    # the box just fill the figure rect regardless of dataLim, avoiding it —
    # exact since FIG_W:FIG_H already matches the 360:180 lon/lat ratio.
    ax.set_aspect("auto")
    ax.axis("off")
    fig.patch.set_facecolor(bg_color)
    ax.set_facecolor(bg_color)

    land_color, ocean_color = _land_ocean_tones(bg_color)
    ax.add_feature(cfeature.LAND.with_scale("110m"), facecolor=land_color, zorder=0)
    ax.add_feature(cfeature.OCEAN.with_scale("110m"), facecolor=ocean_color, zorder=0)
    ax.add_feature(cfeature.COASTLINE.with_scale("110m"),
                    edgecolor=COAST_COLOR, linewidth=0.35, alpha=0.80, zorder=3)
    ax.add_feature(cfeature.BORDERS.with_scale("110m"),
                    edgecolor=BORDER_COLOR, linewidth=0.25, alpha=0.65, zorder=3)

    # All FIR outlines, faint, as base context. Uses cartopy's add_geometries
    # (same mechanism as add_feature above) rather than geopandas' .plot(),
    # which mutates ax.dataLim as a side effect — with a small selected
    # subset plotted afterwards, that corrupts the box/data scaling and
    # visibly warps or mis-scales whatever was plotted through it.
    ax.add_geometries(gdf.geometry, ccrs.PlateCarree(),
                       facecolor="none", edgecolor=FIR_EDGE_CLR,
                       linewidth=FIR_EDGE_W, alpha=FIR_EDGE_A, zorder=10)

    # Selected FIRs, colored on top — fill + bright edge.
    if selections:
        for fid, color in selections.items():
            sub = gdf[gdf["id"] == fid]
            if sub.empty:
                continue
            ax.add_geometries(sub.geometry, ccrs.PlateCarree(),
                               facecolor=color, edgecolor="none",
                               alpha=0.35, zorder=11)
            ax.add_geometries(sub.geometry, ccrs.PlateCarree(),
                               facecolor="none", edgecolor=color,
                               linewidth=0.9, alpha=0.95, zorder=12)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", facecolor=bg_color)
    plt.close(fig)
    buf.seek(0)

    if include_logo:
        buf = _composite_logo(buf.getvalue(), bg_color)

    # Matplotlib/Agg's C-level buffers for a render this size don't always
    # get handed back to the OS promptly on a plain refcount drop — on a
    # 512MB instance, back-to-back exports can stack peak usage instead of
    # each starting fresh. An explicit collect closes that gap.
    gc.collect()

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(buf, mimetype="image/png",
                      as_attachment=True, download_name=f"fir_map_{ts}.png")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
