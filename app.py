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

import io
import json
import os
from datetime import datetime

from flask import Flask, jsonify, render_template, request, send_file

import matplotlib as mpl
mpl.use("Agg")
import matplotlib.pyplot as plt
import cartopy.crs as ccrs
import cartopy.feature as cfeature
import geopandas as gpd

HERE            = os.path.dirname(os.path.abspath(__file__))
SIMPLIFIED_PATH = os.path.join(HERE, "data", "firs_simplified.geojson")
FULLRES_PATH    = os.path.join(HERE, "data", "Global_FIRs.geojson")

# ── Map style (matches Global_Maps.py) ─────────────────────────────────────
MAP_BG       = "#1C242B"
COAST_COLOR  = "#3E4650"
BORDER_COLOR = "#343C44"
FIR_EDGE_CLR = "#4A5568"
FIR_EDGE_A   = 0.45
FIR_EDGE_W   = 0.30

FIG_W, FIG_H = 24, 12
DPI          = 200

app = Flask(__name__)

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
        _fullres_gdf = gdf
    return _fullres_gdf


@app.route("/")
def index():
    return render_template("index.html")


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
      "background": "#1C242B"   (optional)
    }
    """
    payload     = request.get_json(force=True) or {}
    selections  = payload.get("selections", {})
    bg_color    = payload.get("background") or MAP_BG

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

    ax.add_feature(cfeature.LAND.with_scale("110m"), facecolor=bg_color, zorder=0)
    ax.add_feature(cfeature.OCEAN.with_scale("110m"), facecolor=bg_color, zorder=0)
    ax.add_feature(cfeature.COASTLINE.with_scale("110m"),
                    edgecolor=COAST_COLOR, linewidth=0.35, alpha=0.80, zorder=3)
    ax.add_feature(cfeature.BORDERS.with_scale("110m"),
                    edgecolor=BORDER_COLOR, linewidth=0.25, alpha=0.65, zorder=3)

    # All FIR outlines, faint, as base context.
    gdf.boundary.plot(ax=ax, transform=ccrs.PlateCarree(),
                       edgecolor=FIR_EDGE_CLR, linewidth=FIR_EDGE_W,
                       alpha=FIR_EDGE_A, zorder=10)

    # Selected FIRs, colored on top — fill + bright edge.
    if selections:
        for fid, color in selections.items():
            sub = gdf[gdf["id"] == fid]
            if sub.empty:
                continue
            sub.plot(ax=ax, transform=ccrs.PlateCarree(),
                     facecolor=color, alpha=0.35, edgecolor="none", zorder=11)
            sub.boundary.plot(ax=ax, transform=ccrs.PlateCarree(),
                               edgecolor=color, linewidth=0.9, alpha=0.95, zorder=12)

    buf = io.BytesIO()
    plt.savefig(buf, format="png", facecolor=bg_color)
    plt.close(fig)
    buf.seek(0)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return send_file(buf, mimetype="image/png",
                      as_attachment=True, download_name=f"fir_map_{ts}.png")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5002, debug=True)
