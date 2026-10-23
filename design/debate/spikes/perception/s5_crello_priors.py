"""Spike 5: can Crello give us layout priors for extreme aspects WITHOUT shipping 18 GB?
Reads ONLY geometry/typography columns (parquet column projection over HTTP range requests; no images)
for wide formats, and summarises how real designers lay out leaderboards / wide banners.
Output: out/crello_wide_layouts.json (a few hundred KB) - the kind of artefact we would bake into the image."""
import time, json, collections, os
import numpy as np
import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem
FMT = {25: "Leaderboard", 16: "Email header", 3: "Facebook cover", 24: "Skyscraper", 17: "Medium Rectangle", 29: "Youtube Thumbnail"}
COLS = ["format", "canvas_width", "canvas_height", "type", "left", "top", "width", "height", "font_size", "text", "opacity", "angle"]
fs = HfFileSystem(); t = time.time(); keep = []
files = sorted(f for f in fs.ls("datasets/cyberagent/crello/data", detail=False) if f.endswith(".parquet"))
type_names = None
for f in files:
    with fs.open(f, "rb", block_size=1 << 20) as fh:
        pf = pq.ParquetFile(fh)
        if type_names is None:
            ft = pf.schema_arrow.field("type").type
        tb = pf.read(columns=COLS).to_pylist()
    for r in tb:
        if r["format"] in FMT: keep.append(r)
print(f"kept {len(keep)} wide/odd-format designs in {time.time()-t:.0f}s")
out = os.path.join(os.path.dirname(__file__), "out", "crello_wide_layouts.json")
json.dump(keep, open(out, "w")); print("artefact size", round(os.path.getsize(out) / 1e6, 2), "MB")
