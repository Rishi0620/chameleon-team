"""Spike 5b: what do ~317 real Crello leaderboards (728x90-class) look like? Priors we can bake in."""
import json, collections, os
import numpy as np
D = json.load(open(os.path.join(os.path.dirname(__file__), "out", "crello_wide_layouts.json")))
T = {0: "svg", 1: "text", 2: "image", 3: "bg", 4: "mask"}
def summarise(fmt):
    rows = [d for d in D if d["format"] == fmt]
    sizes = collections.Counter((d["canvas_width"], d["canvas_height"]) for d in rows)
    n_text, n_img, head_cx, head_hfrac, head_lines, n_shown, big_img_cx, big_img_hfrac, text_cover_w, fs_min = [], [], [], [], [], [], [], [], [], []
    for d in rows:
        W, H = d["canvas_width"], d["canvas_height"]; ty = [T[t] for t in d["type"]]
        txt = [i for i, t in enumerate(ty) if t == "text" and d["text"][i].strip()]
        img = [i for i, t in enumerate(ty) if t in ("image", "svg", "mask") and d["width"][i] * d["height"][i] < 0.8 * W * H]
        n_text.append(len(txt)); n_img.append(len(img)); n_shown.append(len(ty))
        if txt:
            h = max(txt, key=lambda i: d["font_size"][i])
            head_cx.append((d["left"][h] + d["width"][h] / 2) / W)
            head_hfrac.append(d["font_size"][h] / H)
            head_lines.append(d["text"][h].count("\n") + 1)
            fs_min.append(min(d["font_size"][i] for i in txt) / H * 90)       # smallest text, in px at 90px height
            text_cover_w.append((max(d["left"][i] + d["width"][i] for i in txt) - min(d["left"][i] for i in txt)) / W)
        if img:
            b = max(img, key=lambda i: d["width"][i] * d["height"][i])
            big_img_cx.append((d["left"][b] + d["width"][b] / 2) / W); big_img_hfrac.append(d["height"][b] / H)
    q = lambda a: f"p25={np.percentile(a,25):.2f} p50={np.median(a):.2f} p75={np.percentile(a,75):.2f}" if len(a) else "n/a"
    print(f"\n== {fmt} n={len(rows)} top sizes={sizes.most_common(3)}")
    print(f"  #elements {q(n_shown)} | #text {q(n_text)} | #non-bg images/svgs {q(n_img)}")
    print(f"  largest text: centre-x/W {q(head_cx)} ; font_size/H {q(head_hfrac)} ; lines {q(head_lines)}")
    print(f"  smallest text font in px @H=90: {q(fs_min)}")
    print(f"  text span width/W {q(text_cover_w)}")
    print(f"  biggest non-bg image: centre-x/W {q(big_img_cx)} ; height/H {q(big_img_hfrac)}")
    hc = np.array(head_cx); print(f"  headline zone: left third {np.mean(hc<0.4):.0%}  middle {np.mean((hc>=0.4)&(hc<=0.6)):.0%}  right {np.mean(hc>0.6):.0%}")
for f in (25, 16, 3, 24):
    summarise(f)
