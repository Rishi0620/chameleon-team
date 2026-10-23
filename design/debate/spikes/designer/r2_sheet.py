import sys, glob
from PIL import Image, ImageDraw
prefix, out = sys.argv[1], sys.argv[2]
files = sorted(glob.glob(f"{prefix}*.png"))
cells = []
for f in files:
    im = Image.open(f).convert("RGB")
    s = min(560 / im.width, 380 / im.height)
    cells.append((f, im.resize((max(1, int(im.width * s)), max(1, int(im.height * s))))))
cols = 3
rows = [cells[i:i + cols] for i in range(0, len(cells), cols)]
H = sum(max(c[1].height for c in r) + 26 for r in rows) + 10
sheet = Image.new("RGB", (cols * 580 + 20, H), (238, 238, 238))
d = ImageDraw.Draw(sheet)
y = 5
for r in rows:
    for j, (f, im) in enumerate(r):
        x = 10 + j * 580
        d.text((x, y), f.split("/")[-1].replace(".png", ""), fill=(0, 0, 0))
        sheet.paste(im, (x, y + 14))
    y += max(c[1].height for c in r) + 26
sheet.save(out)
print(out, sheet.size)
