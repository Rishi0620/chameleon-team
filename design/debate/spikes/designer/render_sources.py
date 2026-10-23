import json, sys
sys.path.insert(0, ".")
from renderer.converter.convert import render_design_to_png
for name in ["level1_warmup", "level2_core", "level3_advanced"]:
    task = json.load(open(f"input/chameleon_sample_{name}.json"))
    w = render_design_to_png(task["source"], "brand_kit/assets", f"design/debate/spikes/designer/src_{name}.png")
    print(name, w)
