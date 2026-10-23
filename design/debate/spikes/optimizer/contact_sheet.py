"""Tile every rendered output into one PNG per sample for quick visual review."""
from pathlib import Path
from PIL import Image, ImageDraw

OUT = Path(__file__).resolve().parent / "out"
for tag in ("L1", "L2", "L3"):
    files = sorted(OUT.glob(f"{tag}_*x*.png"), key=lambda p: p.stem)
    ims = []
    for p in files:
        im = Image.open(p).convert("RGB")
        s = min(1.0, 420 / im.height, 700 / im.width)
        ims.append((p.stem, im.resize((max(1, round(im.width * s)), max(1, round(im.height * s))))))
    pad, cols = 16, 4
    rows = [ims[i:i + cols] for i in range(0, len(ims), cols)]
    W = max(sum(im.width for _, im in r) + pad * (len(r) + 1) for r in rows)
    H = sum(max(im.height for _, im in r) + pad + 18 for r in rows) + pad
    sheet = Image.new("RGB", (W, H), (245, 245, 245))
    d = ImageDraw.Draw(sheet)
    y = pad
    for r in rows:
        x = pad
        for name, im in r:
            d.text((x, y), name, fill=(0, 0, 0))
            sheet.paste(im, (x, y + 16))
            x += im.width + pad
        y += max(im.height for _, im in r) + pad + 18
    sheet.save(OUT / f"sheet_{tag}.png")
    print(OUT / f"sheet_{tag}.png", sheet.size)
