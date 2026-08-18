#!/usr/bin/env python3
"""
preprocess_firs.py
-------------------
One-time build step: reads the full-resolution FIR polygon set
(data/Global_FIRs.geojson) and writes a simplified, browser-sized
GeoJSON to data/firs_simplified.geojson for fast Leaflet rendering.

The full-resolution file is used unchanged for the server-side PNG
export (app.py), so simplification here only affects what gets drawn
interactively in the browser — the exported PNG stays full detail.

Run once after setup, and again only if the source GeoJSON changes:
    python3 preprocess_firs.py
"""

import json
import os

import geopandas as gpd

HERE       = os.path.dirname(os.path.abspath(__file__))
SRC_PATH   = os.path.join(HERE, "data", "Global_FIRs.geojson")
OUT_PATH   = os.path.join(HERE, "data", "firs_simplified.geojson")

# Degrees of tolerance for Douglas-Peucker simplification. Small enough to
# preserve FIR shape at global zoom, large enough to cut point count ~10x.
SIMPLIFY_TOLERANCE = 0.02


def main():
    print(f"Loading {SRC_PATH} …")
    gdf = gpd.read_file(SRC_PATH).to_crs("EPSG:4326")

    # The GeoJSON top-level "id" (e.g. "00-00-f0-00") is the stable per-FIR
    # key but geopandas doesn't expose it as a column, so pull it back out of
    # the raw file by feature position (read order is preserved by fiona).
    with open(SRC_PATH) as f:
        raw = json.load(f)
    raw_ids = [feat.get("id") for feat in raw["features"]]
    assert len(raw_ids) == len(gdf), "feature count mismatch between raw and parsed GeoJSON"
    gdf["id"] = raw_ids

    gdf = gdf[~gdf.geometry.is_empty & gdf.geometry.notna()].copy()
    print(f"  {len(gdf)} features")

    before = sum(len(g.exterior.coords) if g.geom_type == "Polygon"
                 else sum(len(p.exterior.coords) for p in g.geoms)
                 for g in gdf.geometry)

    gdf["geometry"] = gdf.geometry.simplify(SIMPLIFY_TOLERANCE, preserve_topology=True)

    after = sum(len(g.exterior.coords) if g.geom_type == "Polygon"
                else sum(len(p.exterior.coords) for p in g.geoms)
                for g in gdf.geometry)
    print(f"  points: {before:,} -> {after:,}")

    gdf = gdf[["id", "volumeName", "icaoID", "geometry"]]

    os.makedirs(os.path.dirname(OUT_PATH), exist_ok=True)
    gdf.to_file(OUT_PATH, driver="GeoJSON")

    size_mb = os.path.getsize(OUT_PATH) / 1_000_000
    print(f"  -> {OUT_PATH} ({size_mb:.1f} MB)")


if __name__ == "__main__":
    main()
