"""Robustness probe: GALLEY on a design shape it was NOT developed against.

A 1200x628 'link ad' with a split layout (product picture on the left half,
LEFT-aligned copy stack on the right), opaque ids, no group for the logo,
a text-only CTA and a two-colour headline. Retarget to story / square / leaderboard.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import galley as G  # noqa: E402

design = {
    "canvas": {"width": 1200, "height": 628},
    "elements": [
        {"id": "e0", "type": "image", "x": 0, "y": 0, "width": 1200, "height": 628, "z_index": 0,
         "asset_id": "solstice_bg_gradient.png", "fit": "cover"},
        {"id": "e1", "type": "image", "x": 40, "y": 40, "width": 548, "height": 548, "z_index": 2,
         "asset_id": "solstice_bottle.png", "fit": "contain"},
        {"id": "e2", "type": "image", "x": 650, "y": 70, "width": 240, "height": 80, "z_index": 2,
         "asset_id": "solstice_logo_lockup.png", "fit": "contain"},
        {"id": "e3", "type": "text", "x": 660, "y": 190, "width": 500, "height": 130, "z_index": 3,
         "content": "Golden hour, bottled.", "font_family": "Solstice Serif", "font_size": 52,
         "font_weight": "bold", "color": "rgba(255,255,255,1)", "text_align": "left",
         "style_runs": [{"start": 13, "end": 21, "color": "rgba(240,178,66,1)"}]},
        {"id": "e4", "type": "text", "x": 660, "y": 340, "width": 480, "height": 90, "z_index": 3,
         "content": "Four new botanical infusions, in stores this June.",
         "font_family": "Solstice Sans", "font_size": 24, "color": "rgba(255,255,255,0.85)", "text_align": "left"},
        {"id": "e5", "type": "shape", "x": 660, "y": 470, "width": 260, "height": 70, "z_index": 2,
         "shape_type": "rectangle", "fill_color": "rgba(232,106,58,1)", "corner_radius": 35, "group_id": "g7"},
        {"id": "e6", "type": "text", "x": 660, "y": 489, "width": 260, "height": 34, "z_index": 3,
         "content": "Find a store", "font_family": "Solstice Sans", "font_size": 24, "font_weight": "bold",
         "color": "rgba(255,255,255,1)", "text_align": "center", "group_id": "g7"},
    ],
}

if __name__ == "__main__":
    Path(G.OUT / "U_source.json").write_text(json.dumps(design))
    G.render_design_to_png(design, str(G.ASSETS), str(G.OUT / "U_source.png"))
    g = G.decompile(design)
    print(G.describe(g))
    names = ["U_source"]
    for W, H in [(1080, 1920), (1080, 1080), (728, 90), (1600, 400)]:
        print(f"\n -> target {W}x{H}")
        ctx, res = G.solve(g, W, H, top_k=3)
        out = G.emit(g, design, ctx, res[0])
        name = f"U_{W}x{H}"
        G.render_design_to_png(out, str(G.ASSETS), str(G.OUT / f"{name}.png"))
        print("   chosen:", G.render_struct(res[0][2], res[0][3]), " off-canvas:", G.bounds_report(out))
        names.append(name)
    G.contact_sheet(names, G.OUT / "sheet_unseen.png")
