#!/usr/bin/env python3
"""
warm_cartopy_cache.py
----------------------
cartopy downloads its Natural Earth basemap shapefiles (land, ocean,
coastline, borders) from the network the first time a feature is drawn.
On Render that first draw happens inside a live /api/render request on a
fresh container, and the download can take long enough to blow past the
request timeout — the export fails even though the render itself is fine.

Run this once during the build step so the shapefiles are already on disk
before the app starts serving traffic. See render.yaml's buildCommand.
"""

import cartopy.feature as cfeature

FEATURES = [
    ("physical", "land"),
    ("physical", "ocean"),
    ("physical", "coastline"),
    ("cultural", "admin_0_boundary_lines_land"),
]


def main():
    for category, name in FEATURES:
        feat = cfeature.NaturalEarthFeature(category, name, "110m")
        list(feat.geometries())  # forces the download
        print(f"  cached {category}/{name}")


if __name__ == "__main__":
    main()
