"""Round 3: Crello format priors for EVERY format (tall, square, wide), geometry/typography columns only
(parquet column projection over HTTP; no images). Writes r3_out/crello_priors.json: robust per-format stats
(median, p25, p75, n) + a mapping onto the 26-size bench catalogue (borrowed by aspect when Crello lacks a format)."""
import json, os, time, sys
from pathlib import Path
import numpy as np
import pyarrow.parquet as pq
from huggingface_hub import HfFileSystem
OUT = Path(__file__).parent / "r3_out"; OUT.mkdir(exist_ok=True)
FMT_NAMES = ["Instagram Story", "Instagram", "Facebook", "Facebook cover", "Twitter", "Facebook AD", "Poster", "Instagram AD",
             "Tumblr", "Image", "Pinterest", "Flayer", "FB event cover", "Postcard", "Invitation", "Youtube", "Email header",
             "Medium Rectangle", "Graphic", "Large Rectangle", "Poster US", "Card", "Logo", "Title", "Skyscraper", "Leaderboard",
             "Presentation", "Gift Certificate", "VK Universal Post", "Youtube Thumbnail", "Business card", "Book Cover",
             "Presentation Wide", "VK Community Cover", "Certificate", "Zoom Background", "VK Post with Button", "T-Shirt",
             "Instagram Highlight Cover", "Coupon", "Letterhead", "IGTV Cover", "Album Cover", "LinkedIn Cover", "Storyboard",
             "Schedule Planner", "Invoice", "Resume", "Recipe Card", "Menu", "Mood Board", "Mind Map", "Label", "Newsletter",
             "Brochure", "Ticket", "Proposal", "Snapchat Geofilter", "Snapchat Moment Filter", "Twitch Offline Banner",
             "Twitch Profile Banner", "Infographic", "Photo Book", "Mobile Presentation", "Web Banner", "Gallery Image", "Calendar"]
COLS = ["format", "canvas_width", "canvas_height", "type", "left", "top", "width", "height", "font_size", "text", "angle"]
T = {0: "svg", 1: "text", 2: "image", 3: "bg", 4: "mask"}

def per_design(d):
    W, H = float(d["canvas_width"]), float(d["canvas_height"]); short = min(W, H)
    ty = [T[t] for t in d["type"]]
    n = len(ty)
    boxes = [(d["left"][i], d["top"][i], d["width"][i], d["height"][i]) for i in range(n)]
    full = [b[2] * b[3] >= 0.8 * W * H for b in boxes]
    txt = [i for i in range(n) if ty[i] == "text" and (d["text"][i] or "").strip()]
    img = [i for i in range(n) if ty[i] in ("image", "svg", "mask") and not full[i]]
    r = {"W": W, "H": H, "n_el": n, "n_text": len(txt), "n_img": len(img)}
    if txt:
        fs = sorted((d["font_size"][i] for i in txt), reverse=True); h = max(txt, key=lambda i: d["font_size"][i])
        r.update(head_fs_H=fs[0] / H, head_fs_short=fs[0] / short, head_lines=(d["text"][h] or "").count("\n") + 1,
                 head_cx=(d["left"][h] + d["width"][h] / 2) / W, head_cy=(d["top"][h] + d["height"][h] / 2) / H,
                 ramp=(fs[1] / fs[0]) if len(fs) > 1 and fs[0] > 0 else np.nan, min_fs_px=fs[-1], min_fs_short=fs[-1] / short,
                 text_area=sum(d["width"][i] * d["height"][i] for i in txt) / (W * H))
    if img:
        b = max(img, key=lambda i: d["width"][i] * d["height"][i])
        r.update(img_h_H=d["height"][b] / H, img_w_W=d["width"][b] / W, img_area=d["width"][b] * d["height"][b] / (W * H),
                 img_cx=(d["left"][b] + d["width"][b] / 2) / W, img_cy=(d["top"][b] + d["height"][b] / 2) / H)
    nb = [i for i in range(n) if not full[i] and ty[i] != "bg"]
    if nb:
        x0 = max(0, min(boxes[i][0] for i in nb)); y0 = max(0, min(boxes[i][1] for i in nb))
        x1 = min(W, max(boxes[i][0] + boxes[i][2] for i in nb)); y1 = min(H, max(boxes[i][1] + boxes[i][3] for i in nb))
        r.update(fill=max(0, x1 - x0) * max(0, y1 - y0) / (W * H), margin_short=max(0, min(x0, y0, W - x1, H - y1)) / short)
    return r

fs = HfFileSystem(); t0 = time.time(); rows = {}
files = sorted(f for f in fs.ls("datasets/cyberagent/crello/data", detail=False) if f.endswith(".parquet"))
for f in files:
    with fs.open(f, "rb", block_size=1 << 20) as fh:
        tb = pq.ParquetFile(fh).read(columns=COLS).to_pylist()
    for d in tb:
        try: rows.setdefault(FMT_NAMES[d["format"]], []).append(per_design(d))
        except Exception: pass
print(f"scanned {sum(len(v) for v in rows.values())} designs in {time.time()-t0:.0f}s", flush=True)
keys = ["n_el", "n_text", "n_img", "head_fs_H", "head_fs_short", "head_lines", "head_cx", "head_cy", "ramp", "min_fs_px",
        "min_fs_short", "text_area", "img_h_H", "img_w_W", "img_area", "img_cx", "img_cy", "fill", "margin_short"]
pri = {}
for fmt, L in rows.items():
    sizes = {}
    for r in L: sizes[(int(r["W"]), int(r["H"]))] = sizes.get((int(r["W"]), int(r["H"])), 0) + 1
    (w, h), _ = max(sizes.items(), key=lambda kv: kv[1])
    st = {"n": len(L), "size": [w, h], "aspect": w / h}
    for k in keys:
        v = np.array([r[k] for r in L if k in r and np.isfinite(r[k])], float)
        if len(v) >= 10: st[k] = {"p25": round(float(np.percentile(v, 25)), 4), "med": round(float(np.median(v)), 4), "p75": round(float(np.percentile(v, 75)), 4), "n": int(len(v))}
    pri[fmt] = st
# map the bench/platform catalogue onto Crello formats (exact where Crello has the format; else nearest aspect among n>=150)
CAT = {"ig_post": (1080, 1080), "ig_portrait": (1080, 1350), "ig_story": (1080, 1920), "ig_landscape": (1080, 566), "fb_post": (1200, 630),
       "fb_cover": (820, 312), "fb_event": (1920, 1005), "x_post": (1600, 900), "x_header": (1500, 500), "li_post": (1200, 627),
       "li_banner": (1584, 396), "pin": (1000, 1500), "yt_thumb": (1280, 720), "yt_channel": (2560, 1440), "slide_16x9": (1920, 1080),
       "leaderboard": (728, 90), "large_leaderboard": (970, 90), "billboard": (970, 250), "med_rect": (300, 250), "large_rect": (336, 280),
       "half_page": (300, 600), "skyscraper": (160, 600), "mobile_banner": (320, 50), "large_mobile": (320, 100), "email_header": (600, 200),
       "letter_flyer": (1275, 1650)}
EXACT = {"ig_post": "Instagram", "ig_story": "Instagram Story", "fb_post": "Facebook", "fb_cover": "Facebook cover", "fb_event": "FB event cover",
         "x_post": "Twitter", "li_banner": "LinkedIn Cover", "pin": "Pinterest", "yt_thumb": "Youtube Thumbnail", "yt_channel": "Youtube",
         "slide_16x9": "Presentation Wide", "leaderboard": "Leaderboard", "med_rect": "Medium Rectangle", "large_rect": "Large Rectangle",
         "skyscraper": "Skyscraper", "email_header": "Email header", "letter_flyer": "Poster US"}
big = {f: p for f, p in pri.items() if p["n"] >= 150}
mapping = {}
for c, (w, h) in CAT.items():
    if c in EXACT and EXACT[c] in pri:
        mapping[c] = {"crello": EXACT[c], "how": "exact format", "crello_size": pri[EXACT[c]]["size"]}
    else:
        best = min(big, key=lambda f: abs(np.log(big[f]["aspect"] / (w / h))))
        mapping[c] = {"crello": best, "how": f"borrowed: nearest aspect ({big[best]['aspect']:.2f} vs {w/h:.2f})", "crello_size": big[best]["size"]}
json.dump({"priors": pri, "catalogue_map": mapping, "_doc": __doc__}, open(OUT / "crello_priors.json", "w"), indent=1)
print("formats:", len(pri), "| catalogue map:", {c: m["crello"] + ("" if m["how"] == "exact format" else "*") for c, m in mapping.items()})
for c in ("ig_story", "ig_post", "ig_portrait", "pin", "half_page", "skyscraper", "leaderboard", "mobile_banner", "med_rect", "yt_thumb", "li_banner"):
    p = pri[mapping[c]["crello"]]
    g = lambda k: (p.get(k) or {}).get("med", float("nan"))
    print(f"{c:13s} <- {mapping[c]['crello']:18s} n={p['n']:5d}  head font/H {g('head_fs_H'):.3f}  font/short {g('head_fs_short'):.3f}  lines {g('head_lines'):.0f}  ramp {g('ramp'):.2f}  min font px {g('min_fs_px'):.1f}  img h/H {g('img_h_H'):.2f}  fill {g('fill'):.2f}  margin/short {g('margin_short'):.3f}")
