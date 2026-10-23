"""Bench design set: the 3 official samples + 12 adversarial synthetic designs.

Synthetic designs get OPAQUE ids/group ids and (except S07, which tests z-ties) a shuffled
element list, so engines cannot lean on names or authoring order. Each design carries a
`features` list naming the adversarial cases it exercises (see round1/judge.md section 3).

Run from repo root:  .venv/bin/python design/debate/bench/designs.py   (writes bench/designs/*.json)
"""
from __future__ import annotations

import copy
import hashlib
import json
import random
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
OUT = Path(__file__).resolve().parent / "designs"

WHITE, DARK, ORANGE, GOLD = "rgba(255,255,255,1)", "rgba(43,27,46,1)", "rgba(232,106,58,1)", "rgba(240,178,66,1)"
SERIF, SANS = "Solstice Serif", "Solstice Sans"


def T(n, content, x, y, w, h, fs, z, family=SANS, color=WHITE, align="center", bold=False, **kw):
    el = {"_n": n, "type": "text", "x": x, "y": y, "width": w, "height": h, "z_index": z,
          "content": content, "font_family": family, "font_size": fs, "color": color, "text_align": align}
    if bold:
        el["font_weight"] = "bold"
    el.update(kw)
    return el


def I(n, asset, x, y, w, h, z, fit="contain", **kw):
    el = {"_n": n, "type": "image", "x": x, "y": y, "width": w, "height": h, "z_index": z,
          "asset_id": asset, "fit": fit}
    el.update(kw)
    return el


def S(n, x, y, w, h, z, fill, kind="rectangle", **kw):
    el = {"_n": n, "type": "shape", "x": x, "y": y, "width": w, "height": h, "z_index": z,
          "shape_type": kind, "fill_color": fill}
    el.update(kw)
    return el


def pill(n, label, x, y, w, h, fs, z, gid="cta", fill=ORANGE, text_color=WHITE, grouped=True):
    g = {"group_id": gid} if grouped else {}
    return [S(f"{n}_bg", x, y, w, h, z, fill, corner_radius=h / 2, **g),
            T(f"{n}_label", label, x, y + (h - fs * 1.2) / 2, w, fs * 1.2, fs, z + 1, bold=True,
              color=text_color, **g)]


BG = lambda W, H: I("bg", "solstice_bg_gradient.png", 0, 0, W, H, 0, fit="cover")  # noqa: E731
LOGO = "solstice_logo_lockup.png"
BOTTLE = "solstice_bottle.png"
CAN = "bench_can.png"
PHOTO = "bench_photo_busy.png"
LONG_P1 = ("We spent a summer chasing the last light of the day across orchards, rooftops and "
           "riverbanks, tasting as we went. The result is four small-batch infusions built around "
           "wild honey, blood orange, smoked rosemary and a little patience.")
LONG_P2 = ("Each bottle is filled within hours of pressing, lightly sparkled and never pasteurised. "
           "That is why the flavour changes slightly from batch to batch - and why we number them.")
LEGAL_LONG = ("Offer valid on participating flavours only while supplies last. Prices shown are "
              "recommended retail prices and may vary by store. Please drink responsibly. 21+.")


def designs() -> dict[str, dict]:
    d: dict[str, dict] = {}

    W, H = 1200, 628
    d["S01_split_photo"] = dict(canvas=(W, H), features=["split layout", "photo-like cover image (half canvas)",
                                                          "left-aligned copy", "solid shape background"], els=[
        S("bg", 0, 0, W, H, 0, DARK),
        I("photo", PHOTO, 0, 0, 600, 628, 1, fit="cover"),
        I("logo", LOGO, 660, 50, 240, 80, 2),
        T("headline", "Golden hour, bottled.", 660, 160, 500, 140, 56, 3, SERIF, align="left", bold=True,
          style_runs=[{"start": 13, "end": 21, "color": GOLD}]),
        T("subhead", "Four new botanical infusions - in stores this June.", 660, 320, 480, 70, 24, 3,
          color="rgba(255,255,255,0.85)", align="left"),
        *pill("cta", "Find a store", 660, 440, 260, 70, 24, 3, gid="g1")])

    W, H = 1080, 1350
    d["S02_text_over_photo"] = dict(canvas=(W, H), features=["full-bleed busy photo", "translucent full scrim",
                                                              "dark text on calm sky", "centre-crop moves text onto busy area"], els=[
        I("photo", PHOTO, 0, 0, W, H, 0, fit="cover"),
        S("scrim", 0, 0, W, H, 1, "rgba(0,0,0,1)", opacity=0.25),
        T("headline", "Picnic season is here", 80, 110, 920, 230, 96, 3, SERIF, color="rgba(25,30,70,1)", bold=True),
        T("subhead", "Pack the new Solstice botanicals", 140, 350, 800, 50, 36, 3, color="rgba(25,30,70,1)"),
        *pill("cta", "Shop now", 390, 1060, 300, 80, 30, 3, gid="g2"),
        I("logo", LOGO, 400, 1180, 280, 93, 3)])

    W, H = 1080, 1080
    caps = [("Blood Orange", 60, 300), ("Wild Honey", 400, 280), ("Smoked Rosemary", 720, 300)]
    els = [BG(W, H), T("headline", "Pick your flavour", 90, 70, 900, 100, 72, 3, SERIF, bold=True),
           I("prod_a", BOTTLE, 60, 260, 300, 300, 2), I("prod_b", CAN, 420, 250, 240, 320, 2),
           I("prod_c", BOTTLE, 720, 260, 300, 300, 2)]
    for i, (c, x, w) in enumerate(caps):
        els += [T(f"cap{i}", c, x, 600, w, 36, 26, 3, bold=True), T(f"price{i}", "$4.99", x, 645, w, 32, 24, 3, color=GOLD)]
    els += [*pill("cta", "Build a 3-pack", 370, 860, 340, 84, 28, 3, gid="g3"), I("logo", LOGO, 40, 980, 210, 70, 3)]
    d["S03_multi_product_grid"] = dict(canvas=(W, H), features=["three products (two assets)", "repeated caption/price structure",
                                                                 "many small text boxes"], els=els)

    W, H = 1080, 1350
    d["S04_long_copy_editorial"] = dict(canvas=(W, H), features=["light background (contrast)", "very long copy",
                                                                  "letter_spacing kicker", "line divider", "left-aligned", "italic"], els=[
        S("bg", 0, 0, W, H, 0, "rgba(246,240,230,1)"),
        T("kicker", "FIELD NOTES - ISSUE 07", 90, 90, 900, 30, 22, 2, color=ORANGE, align="left", bold=True, letter_spacing=6),
        T("headline", "What we learned bottling two hundred sunsets for one very small summer collection",
          90, 140, 900, 320, 64, 2, SERIF, color=DARK, align="left", bold=True),
        S("divider", 90, 480, 900, 4, 2, DARK, kind="line", stroke_color=DARK, stroke_width=3),
        T("body1", LONG_P1, 90, 510, 900, 220, 26, 2, color="rgba(60,50,60,1)", align="left"),
        T("body2", LONG_P2, 90, 760, 900, 190, 26, 2, color="rgba(60,50,60,1)", align="left"),
        T("byline", "Words by the Solstice field team", 90, 980, 600, 30, 22, 2, color="rgba(110,100,110,1)",
          align="left", font_style="italic"),
        *pill("cta", "Read more", 780, 1220, 210, 60, 22, 2, gid="g4")])

    W, H = 1080, 1080
    d["S05_rotated_sticker_bleed"] = dict(canvas=(W, H), features=["rotated 3-element group", "group bleeds off canvas in source",
                                                                    "translucent deco bleed"], els=[
        BG(W, H), S("deco", -60, 600, 300, 300, 1, WHITE, kind="ellipse", opacity=0.1),
        I("product", BOTTLE, 290, 200, 500, 500, 2),
        T("headline", "Summer Sale", 90, 740, 900, 110, 90, 3, SERIF, bold=True),
        T("subhead", "Every flavour, this weekend only.", 140, 860, 800, 40, 28, 3),
        S("st_bg", 870, -20, 220, 220, 4, GOLD, kind="ellipse", rotation=15, group_id="g5"),
        T("st_big", "50%", 870, 25, 220, 80, 64, 5, SERIF, color=DARK, bold=True, rotation=15, group_id="g5"),
        T("st_small", "OFF", 870, 105, 220, 40, 30, 5, color=DARK, bold=True, rotation=15, group_id="g5"),
        *pill("cta", "Shop the sale", 390, 940, 300, 76, 26, 3, gid="g6")])

    d["S06_ungrouped_text_backgrounds"] = dict(canvas=(W, H), features=["shape behind text WITHOUT group_id (x3)",
                                                                         "stroke-only frame (renders invisible)",
                                                                         "price tag overlapping product (intended layering)"], els=[
        S("bg", 0, 0, W, H, 0, DARK),
        S("frame", 40, 40, 1000, 1000, 1, "rgba(0,0,0,0)", stroke_color=WHITE, stroke_width=4),
        T("headline", "Taste the glow", 90, 120, 900, 100, 80, 3, SERIF, bold=True),
        S("hl_bar", 300, 240, 480, 56, 2, GOLD),
        T("hl_text", "NEW - LIMITED RUN", 300, 252, 480, 34, 26, 3, color=DARK, bold=True),
        I("product", BOTTLE, 340, 330, 400, 400, 2),
        S("tag_bg", 720, 380, 180, 180, 3, ORANGE, kind="ellipse"),
        T("tag_text", "$5", 720, 425, 180, 90, 72, 4, SERIF, bold=True),
        *pill("cta", "Order today", 380, 800, 320, 80, 28, 3, grouped=False),
        T("legal", "Prices valid while supplies last.", 290, 1010, 500, 22, 16, 3, color="rgba(255,255,255,0.6)")])

    W, H = 1600, 900
    bg7 = BG(W, H)
    del bg7["z_index"]                               # missing z_index on purpose
    d["S07_lines_zties_spacing"] = dict(canvas=(W, H), shuffle=False, features=[
        "missing z_index", "z ties broken by list order (pill shape+label share z)", "letter_spacing 10",
        "explicit newline", "horizontal + rotated (vertical) line shapes", "unbreakable URL in legal",
        "contain image in a non-matching (0.6) box"], els=[
        bg7,
        T("kicker", "SOLSTICE  STUDIO  SESSIONS", 120, 120, 900, 34, 24, 2, color=ORANGE, align="left", bold=True, letter_spacing=10),
        S("rule", 120, 175, 600, 6, 2, WHITE, kind="line", stroke_color=WHITE, stroke_width=4),
        T("headline", "Live music\nat golden hour", 120, 210, 900, 240, 96, 2, SERIF, align="left", bold=True),
        S("vrule", 1000, 397, 600, 6, 2, WHITE, kind="line", stroke_color=WHITE, stroke_width=4, rotation=90),
        T("date", "Fri 21 June - 7pm", 120, 480, 700, 50, 36, 2, align="left"),
        I("logo", LOGO, 1360, 80, 200, 67, 2),
        I("product", BOTTLE, 1340, 250, 240, 400, 2),
        S("cta_bg", 120, 600, 300, 80, 3, ORANGE, corner_radius=40),
        T("cta_label", "Get tickets", 120, 622, 300, 36, 30, 3, bold=True),
        T("legal", "Tickets non-refundable. 21+ only. solstice.com/studio-sessions-terms-and-conditions",
          120, 820, 900, 24, 18, 2, color="rgba(255,255,255,0.6)", align="left")])

    W, H = 1080, 1080
    d["S08_missing_and_empty"] = dict(canvas=(W, H), features=["LARGE missing hero asset", "empty / whitespace / newline-only text",
                                                                "emoji + CJK (tofu)", "HTML entity &amp;"], els=[
        S("bg", 0, 0, W, H, 0, "rgba(30,40,60,1)"),
        I("hero", "summer_campaign_hero_v2.png", 140, 140, 800, 500, 1, fit="cover"),
        I("logo", LOGO, 40, 30, 210, 70, 3),
        T("headline", "Café culture, bottled \U0001F379", 90, 680, 900, 80, 64, 3, SERIF, bold=True),
        T("subhead", "Salt &amp; Pepper popcorn pairing - 日本語 edition", 140, 780, 800, 40, 28, 3),
        T("empty", "", 100, 840, 300, 40, 30, 3),
        T("spaces", "   ", 600, 840, 300, 40, 30, 3),
        T("newline", "\n", 400, 1000, 200, 40, 30, 3),
        *pill("cta", "Discover", 390, 900, 300, 76, 28, 3, gid="g8")])

    W, H = 728, 90
    d["S09_banner_source"] = dict(canvas=(W, H), features=["source is a 728x90 leaderboard (reverse direction)"], els=[
        BG(W, H), I("logo", LOGO, 12, 20, 150, 50, 2),
        T("headline", "Chase the Light - new botanical sparklers", 190, 18, 360, 54, 22, 2, SERIF, bold=True),
        *pill("cta", "Shop now", 580, 24, 134, 42, 16, 2, gid="g9")])

    W, H = 1080, 1920
    d["S10_story_source"] = dict(canvas=(W, H), features=["9:16 story source", "busy photo bg + partial scrim",
                                                           "rotated sticker overlapping product", "huge 3-line headline"], els=[
        I("photo", PHOTO, 0, 0, W, H, 0, fit="cover"),
        S("scrim", 0, 0, W, 900, 1, "rgba(20,15,30,1)", opacity=0.45),
        I("logo", LOGO, 390, 120, 300, 100, 3),
        T("headline", "Your summer, in three sips", 80, 300, 920, 400, 110, 3, SERIF, bold=True),
        I("product", BOTTLE, 240, 760, 600, 600, 2),
        S("st_bg", 700, 720, 300, 70, 4, "rgba(220,60,50,1)", rotation=-10, group_id="g10"),
        T("st_label", "NEW", 700, 735, 300, 40, 34, 5, bold=True, rotation=-10, group_id="g10"),
        *pill("cta", "Swipe up to shop", 290, 1560, 500, 110, 40, 3, gid="g11"),
        T("legal", "Drink responsibly.", 340, 1820, 400, 30, 22, 3, color="rgba(255,255,255,0.7)")])

    W, H = 1080, 1080
    d["S11_card_overlay"] = dict(canvas=(W, H), features=["full-canvas translucent overlay", "card panel holding dark text (no group)",
                                                           "invisible stroke-only frame", "light card on dark bg"], els=[
        BG(W, H), S("overlay", 0, 0, W, H, 1, "rgba(0,0,0,1)", opacity=0.35),
        S("card", 140, 260, 800, 600, 2, "rgba(250,246,238,1)", corner_radius=24),
        T("card_head", "Members get early access", 200, 320, 680, 140, 56, 3, SERIF, color=DARK, bold=True),
        T("card_body", "Join the Solstice club for first pours, tasting nights and 15% off every order.",
          200, 490, 680, 120, 28, 3, color=DARK),
        *pill("cta", "Join free", 390, 700, 300, 80, 28, 3, gid="g12"),
        I("logo", LOGO, 390, 110, 300, 100, 3),
        S("frame", 20, 20, 1040, 1040, 5, "rgba(0,0,0,0)", stroke_color=WHITE, stroke_width=3)])

    W, H = 1080, 1350
    labels = ["VEGAN", "GLUTEN FREE", "NON-GMO", "LOW CAL", "KETO", "ORGANIC"]
    els = [S("bg", 0, 0, W, H, 0, DARK), I("logo", LOGO, 390, 50, 300, 100, 2),
           T("price", "$4.99", 90, 200, 600, 170, 140, 2, SERIF, color=ORANGE, align="left", bold=True),
           T("old_price", "$6.49", 700, 280, 250, 50, 40, 2, color="rgba(255,255,255,0.5)", align="left"),
           I("product", BOTTLE, 600, 400, 440, 440, 2)]
    for i, b in enumerate(["Zero added sugar", "40 calories", "Real botanicals", "Lightly sparkling"]):
        els.append(T(f"bullet{i}", "• " + b, 90, 450 + i * 70, 480, 40, 30, 2, align="left"))
    for i, lab in enumerate(labels):
        x, y = 90 + (i % 3) * 310, 900 + (i // 3) * 80
        els += pill(f"badge{i}", lab, x, y, 280, 56, 20, 2, gid=f"gb{i}", fill="rgba(80,60,90,1)")
    els += [*pill("cta", "Add to cart", 340, 1100, 400, 90, 32, 3, gid="g13"),
            T("legal", LEGAL_LONG, 90, 1240, 900, 50, 16, 2, color="rgba(255,255,255,0.55)")]
    d["S12_many_badges"] = dict(canvas=(W, H), features=["6 badge groups in 2 rows", "4 bullet texts", "price hierarchy (140 vs 40 px)",
                                                          "2-line legal"], els=els)
    return d


def opaque(design_name: str, spec: dict, seed: int) -> dict:
    """Turn an authoring spec into a task dict with opaque ids and shuffled order."""
    rng = random.Random(seed)
    els = copy.deepcopy(spec["els"])
    gmap: dict[str, str] = {}
    for el in els:
        n = el.pop("_n")
        el["id"] = "e" + hashlib.sha1(f"{design_name}/{n}".encode()).hexdigest()[:7]
        if el.get("group_id"):
            gmap.setdefault(el["group_id"], "g" + hashlib.sha1(f"{design_name}/{el['group_id']}".encode()).hexdigest()[:5])
            el["group_id"] = gmap[el["group_id"]]
    if spec.get("shuffle", True):
        rng.shuffle(els)
    W, H = spec["canvas"]
    return {"task_id": design_name, "features": spec["features"],
            "source": {"canvas": {"width": W, "height": H}, "elements": els},
            "target_canvas": {"width": W, "height": H}}


def load_all() -> dict[str, dict]:
    """name -> task dict (source + features). Official samples keep their original ids."""
    tasks = {}
    for p in sorted((ROOT / "input").glob("chameleon_sample_*.json")):
        t = json.loads(p.read_text())
        name = "L" + p.stem.split("level")[1][0] + "_" + p.stem.split("_")[-1]
        tasks[name] = {"task_id": name, "features": ["official sample"], "source": t["source"],
                       "target_canvas": t["target_canvas"]}
    for p in sorted(OUT.glob("S*.json")):
        tasks[p.stem] = json.loads(p.read_text())
    return tasks


if __name__ == "__main__":
    import sys
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from common import render_png
    OUT.mkdir(parents=True, exist_ok=True)
    for i, (name, spec) in enumerate(designs().items()):
        task = opaque(name, spec, seed=100 + i)
        (OUT / f"{name}.json").write_text(json.dumps(task, indent=1))
    for name, task in load_all().items():
        render_png(task["source"], str(OUT / f"src_{name}.png"))
        print(name, len(task["source"]["elements"]), "elements")
