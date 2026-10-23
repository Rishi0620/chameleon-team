"""Round-2 stress designs with OPAQUE ids (never seen by compose.py while it was written).

PHOTO : 1080x1350 ad, full-bleed busy photo (calm sky top / busy foliage bottom), dark headline +
        subhead on the sky, a dark translucent FOOTER BAR holding the white logo and a CTA pill.
SPLIT : 1200x628 link ad, solid orange COLOUR BLOCK on the left half carrying dark text, logo,
        dark CTA pill; product on the dark right half.
UNSEEN: inventor's design (design/debate/spikes/inventor/unseen.py), copied verbatim.
"""

PHOTO = {
    "canvas": {"width": 1080, "height": 1350},
    "elements": [
        {"id": "q7f2", "type": "image", "x": 0, "y": 0, "width": 1080, "height": 1350, "z_index": 0,
         "asset_id": "r2_busy_photo.png", "fit": "cover"},
        {"id": "a91c", "type": "text", "x": 72, "y": 110, "width": 900, "height": 220, "z_index": 3,
         "content": "Wild light, bottled.", "font_family": "Solstice Serif", "font_size": 92,
         "font_weight": "bold", "color": "rgba(43,27,46,1)", "text_align": "left"},
        {"id": "k03d", "type": "text", "x": 72, "y": 330, "width": 760, "height": 90, "z_index": 3,
         "content": "A sparkling botanical for long summer evenings.", "font_family": "Solstice Sans",
         "font_size": 30, "color": "rgba(43,27,46,0.9)", "text_align": "left"},
        {"id": "zz10", "type": "shape", "x": 0, "y": 1140, "width": 1080, "height": 210, "z_index": 1,
         "shape_type": "rectangle", "fill_color": "rgba(43,27,46,1)", "opacity": 0.88},
        {"id": "m4m4", "type": "image", "x": 60, "y": 1190, "width": 330, "height": 110, "z_index": 2,
         "asset_id": "solstice_logo_lockup.png", "fit": "contain"},
        {"id": "p0p0", "type": "shape", "x": 712, "y": 1200, "width": 308, "height": 90, "z_index": 2,
         "shape_type": "rectangle", "fill_color": "rgba(232,106,58,1)", "corner_radius": 45, "group_id": "x1"},
        {"id": "r8r8", "type": "text", "x": 712, "y": 1226, "width": 308, "height": 40, "z_index": 3,
         "content": "Taste it", "font_family": "Solstice Sans", "font_size": 30, "font_weight": "bold",
         "color": "rgba(255,255,255,1)", "text_align": "center", "group_id": "x1"},
    ],
}

SPLIT = {
    "canvas": {"width": 1200, "height": 628},
    "elements": [
        {"id": "u1", "type": "shape", "x": 0, "y": 0, "width": 1200, "height": 628, "z_index": 0,
         "shape_type": "rectangle", "fill_color": "rgba(43,27,46,1)"},
        {"id": "u2", "type": "shape", "x": 0, "y": 0, "width": 600, "height": 628, "z_index": 1,
         "shape_type": "rectangle", "fill_color": "rgba(232,106,58,1)"},
        {"id": "u3", "type": "image", "x": 680, "y": 64, "width": 500, "height": 500, "z_index": 2,
         "asset_id": "solstice_bottle.png", "fit": "contain"},
        {"id": "u4", "type": "image", "x": 48, "y": 48, "width": 210, "height": 70, "z_index": 2,
         "asset_id": "solstice_logo_lockup.png", "fit": "contain"},
        {"id": "u5", "type": "text", "x": 48, "y": 190, "width": 500, "height": 140, "z_index": 3,
         "content": "Summer in a bottle.", "font_family": "Solstice Serif", "font_size": 60,
         "font_weight": "bold", "color": "rgba(43,27,46,1)", "text_align": "left"},
        {"id": "u6", "type": "text", "x": 48, "y": 360, "width": 480, "height": 70, "z_index": 3,
         "content": "Four botanical infusions, now in stores.", "font_family": "Solstice Sans",
         "font_size": 24, "color": "rgba(43,27,46,1)", "text_align": "left"},
        {"id": "u7", "type": "shape", "x": 48, "y": 480, "width": 220, "height": 64, "z_index": 2,
         "shape_type": "rectangle", "fill_color": "rgba(43,27,46,1)", "corner_radius": 32, "group_id": "gq"},
        {"id": "u8", "type": "text", "x": 48, "y": 500, "width": 220, "height": 30, "z_index": 3,
         "content": "Shop now", "font_family": "Solstice Sans", "font_size": 22, "font_weight": "bold",
         "color": "rgba(255,255,255,1)", "text_align": "center", "group_id": "gq"},
    ],
}


def unseen():
    import importlib.util
    from pathlib import Path
    p = Path(__file__).resolve().parents[1] / "inventor" / "unseen.py"
    src = p.read_text()
    start = src.index("design = {")
    end = src.index("\n}\n", start) + 2
    ns = {}
    exec(src[start:end], ns)  # only the literal dict, not galley
    return ns["design"]
