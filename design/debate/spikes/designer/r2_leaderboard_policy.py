"""Round-2: what SHOULD a 728x90 / 320x50 do with a 140-char headline that copy rules forbid shortening?
Builds three policies for L3 from the same measurement code and renders them side by side:
  A  R1 output (logo | 4-line 14px headline | CTA 14px)          -> current behaviour
  B  'message first': headline gets every pixel the hierarchy allows: product + subhead gone,
     logo at its recognisability floor, CTA label <= headline/1.2 but >= 12px, 3-line cap,
     optical margins balanced (right margin = logo's visible left margin, capped)
  C  'brand reminder': headline hidden, logo | product | CTA (what you get if 'legible or absent'
     is applied literally to the headline)
Run from repo root.
"""
import copy
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.argv = sys.argv[:1]
import compose as C  # noqa: E402

src = json.load(open("input/chameleon_sample_level3_advanced.json"))["source"]
A = json.load(open(HERE / "out_level3_advanced_728x90.json"))
ids = [e["id"] for e in src["elements"]]
for e, i in zip(A["elements"], ids):
    e["id"] = i
byid = lambda d: {e["id"]: e for e in d["elements"]}  # noqa: E731
S = byid(src)


def policy_B(W=728, H=90):
    d = copy.deepcopy(A)
    o = byid(d)
    m = 12
    # logo at recognisability floor (visible mark ~ 0.5H)
    vis = C.place_image(o["logo"], S["logo"], 0.5 * H, 1e3, H / 2, W, H)
    vis = C.place_image(o["logo"], S["logo"], vis[3] - vis[1], 0 + (vis[2] - vis[0]) / 2 + m, H / 2, W, H)
    left_margin = vis[0]
    right_margin = min(left_margin, 32)          # balance optical margins, but don't starve the copy
    # CTA: label strictly below headline rank, never below 12 judge-px
    s, t = S["cta_bg"], S["cta_label"]
    an = C.chip_anatomy(s, t)
    fs_cta = 12
    w, h = C.chip_size(t, an, fs_cta, h_band=(2.4, 2.8), pad_band=(1.0, 1.3))
    C.build_chip(o["cta_bg"], o["cta_label"], an, fs_cta, W - right_margin - w, H / 2, w, h)
    col_l, col_r = vis[2] + 14, W - right_margin - w - 14
    b = C.fit_text(S["headline"], col_r - col_l, H - 2 * 11, 20, 14, 3)
    bw = C.balanced_width(S["headline"], b["fs"], col_r - col_l)
    C.place_text(o["headline"], b["fs"], bw, H / 2 - b["opt_h"] / 2, (col_l + col_r) / 2, "center", H)
    # product hidden in B (it would cost ~45px of measure = one more line)
    C.hide(o["product"], src["canvas"], W, H)
    return d, b


def policy_C(W=728, H=90):
    d = copy.deepcopy(A)
    o = byid(d)
    C.hide(o["headline"], src["canvas"], W, H)
    lv = C.place_image(o["logo"], S["logo"], 0.62 * H, 140, H / 2, W, H)
    o["product"].pop("opacity", None)
    pv = C.place_image(o["product"], S["product"], 0.86 * H, W / 2 - 40, H / 2, W, H)
    return d, None


if __name__ == "__main__":
    B, bb = policy_B()
    Cc, _ = policy_C()
    print("B headline:", bb["fs"], "px,", bb["n"], "lines")
    for tag, d in (("A", A), ("B", B), ("C", Cc)):
        clean = {"canvas": d["canvas"], "elements": d["elements"]}
        (HERE / f"r2_lb_{tag}.json").write_text(json.dumps(clean, indent=1))
        C.render_design_to_png(clean, C.ASSETS, str(HERE / f"r2_lb_{tag}.png"))
    from PIL import Image, ImageDraw
    ims = [Image.open(HERE / f"r2_lb_{t}.png").convert("RGB") for t in "ABC"]
    sheet = Image.new("RGB", (728, 3 * 110), (240, 240, 240))
    dr = ImageDraw.Draw(sheet)
    for k, (t, im) in enumerate(zip("ABC", ims)):
        dr.text((4, k * 110 + 2), {"A": "A: R1 (4 lines 14px, CTA 14px)", "B": "B: message-first (3-line cap, CTA<headline)",
                                    "C": "C: brand reminder (headline hidden)"}[t], fill=(0, 0, 0))
        sheet.paste(im, (0, k * 110 + 16))
    sheet.save(HERE / "r2_lb_sheet.png")
