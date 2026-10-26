"""PixSift logo: a viewfinder framing a friendly face, with a spark. One geometry, two outputs:

- logo.svg (vector master; also used as the web favicon and in-app mark)
- pixsift.png / .icns (macOS) / .ico (Windows), drawn with Pillow at 4x and downsampled for smooth edges.
"""

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
FRONTEND_PUBLIC = HERE.parent / "frontend" / "public"

# Geometry on a 1024 canvas.
TOP, BOTTOM, ACCENT = (79, 70, 229), (147, 51, 234), (251, 113, 133)  # indigo -> violet, coral
INSET, RADIUS = 72, 200                                             # app-icon plate
BRACKET = dict(left=272, top=272, right=752, bottom=752, arm=150, width=56)
EYES = ((432, 470), (592, 470))
EYE_R = 34
SMILE = dict(box=(392, 452, 632, 652), width=52)                   # lower half of this ellipse
SPARK = dict(cx=752, cy=272, r=104)                                 # replaces the top-right corner


def svg() -> str:
    b, s, sp = BRACKET, SMILE, SPARK
    l, t, r, bt, a = b["left"], b["top"], b["right"], b["bottom"], b["arm"]
    corners = f"M{l} {t + a}V{t}H{l + a} M{r} {bt - a}V{bt}H{r - a} M{l + a} {bt}H{l}V{bt - a}"
    x0, y0, x1, y1 = s["box"]
    cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, (x1 - x0) / 2, (y1 - y0) / 2
    smile = f"M{cx - rx} {cy}A{rx} {ry} 0 0 0 {cx + rx} {cy}"
    k = sp["r"] * 0.28  # spark waist
    spark = (f"M{sp['cx']} {sp['cy'] - sp['r']}Q{sp['cx'] + k} {sp['cy'] - k} {sp['cx'] + sp['r']} {sp['cy']}"
             f"Q{sp['cx'] + k} {sp['cy'] + k} {sp['cx']} {sp['cy'] + sp['r']}"
             f"Q{sp['cx'] - k} {sp['cy'] + k} {sp['cx'] - sp['r']} {sp['cy']}"
             f"Q{sp['cx'] - k} {sp['cy'] - k} {sp['cx']} {sp['cy'] - sp['r']}Z")
    hex_ = lambda c: "#%02x%02x%02x" % c  # noqa: E731
    return f'''<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1024 1024" role="img" aria-label="PixSift">
  <defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">
    <stop offset="0" stop-color="{hex_(TOP)}"/><stop offset="1" stop-color="{hex_(BOTTOM)}"/></linearGradient></defs>
  <rect x="{INSET}" y="{INSET}" width="{1024 - 2 * INSET}" height="{1024 - 2 * INSET}" rx="{RADIUS}" fill="url(#g)"/>
  <g fill="none" stroke="#fff" stroke-linecap="round" stroke-linejoin="round">
    <path d="{corners}" stroke-width="{b['width']}"/>
    <path d="{smile}" stroke-width="{s['width']}"/>
  </g>
  <circle cx="{EYES[0][0]}" cy="{EYES[0][1]}" r="{EYE_R}" fill="#fff"/>
  <circle cx="{EYES[1][0]}" cy="{EYES[1][1]}" r="{EYE_R}" fill="#fff"/>
  <path d="{spark}" fill="{hex_(ACCENT)}"/>
</svg>
'''


def raster(size: int = 1024, ss: int = 4) -> Image.Image:
    S = size * ss
    f = S / 1024
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    # Plate with a diagonal gradient and a soft shadow.
    ramp = np.add.outer(np.arange(S), np.arange(S)) / (2 * S - 2)  # 0 top-left -> 1 bottom-right
    plate = Image.fromarray(np.dstack([(TOP[i] + (BOTTOM[i] - TOP[i]) * ramp).astype(np.uint8) for i in range(3)]
                                      + [np.full((S, S), 255, np.uint8)]), "RGBA")
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle([INSET * f, INSET * f, (1024 - INSET) * f, (1024 - INSET) * f],
                                           radius=RADIUS * f, fill=255)
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    shadow.putalpha(mask.point(lambda v: v * 0.35).filter(ImageFilter.GaussianBlur(18 * f)))
    img.alpha_composite(shadow, (0, int(14 * f)))
    img.paste(plate, mask=mask)
    d = ImageDraw.Draw(img)
    b, w = BRACKET, BRACKET["width"] * f
    l, t, r, bt, a = (v * f for v in (b["left"], b["top"], b["right"], b["bottom"], b["arm"]))
    for pts in (((l, t + a), (l, t), (l + a, t)), ((r, bt - a), (r, bt), (r - a, bt)), ((l + a, bt), (l, bt), (l, bt - a))):
        d.line(pts, fill="white", width=round(w), joint="curve")
        for x, y in (pts[0], pts[2]):  # round caps
            d.ellipse([x - w / 2, y - w / 2, x + w / 2, y + w / 2], fill="white")
    for ex, ey in EYES:
        d.ellipse([(ex - EYE_R) * f, (ey - EYE_R) * f, (ex + EYE_R) * f, (ey + EYE_R) * f], fill="white")
    x0, y0, x1, y1 = (v * f for v in SMILE["box"])
    sw = SMILE["width"] * f
    d.arc([x0, y0, x1, y1], 0, 180, fill="white", width=round(sw))
    cy = (y0 + y1) / 2
    for x in (x0 + sw / 2, x1 - sw / 2):  # round caps on the smile
        d.ellipse([x - sw / 2, cy - sw / 2, x + sw / 2, cy + sw / 2], fill="white")
    sp, k = SPARK, SPARK["r"] * 0.28
    cx, cyy, rr = sp["cx"] * f, sp["cy"] * f, sp["r"] * f
    kk = k * f
    star = []
    for i in range(64):  # quadratic-curve star, sampled
        q, t_ = divmod(i, 16)
        t_ /= 16
        p0 = [(cx, cyy - rr), (cx + rr, cyy), (cx, cyy + rr), (cx - rr, cyy)][q]
        p2 = [(cx + rr, cyy), (cx, cyy + rr), (cx - rr, cyy), (cx, cyy - rr)][q]
        c = [(cx + kk, cyy - kk), (cx + kk, cyy + kk), (cx - kk, cyy + kk), (cx - kk, cyy - kk)][q]
        star.append(tuple((1 - t_) ** 2 * p0[j] + 2 * (1 - t_) * t_ * c[j] + t_ ** 2 * p2[j] for j in range(2)))
    d.polygon(star, fill=ACCENT)
    return img.resize((size, size), Image.LANCZOS)


if __name__ == "__main__":
    (HERE / "logo.svg").write_text(svg())
    (FRONTEND_PUBLIC / "favicon.svg").write_text(svg())
    icon = raster()
    icon.save(HERE / "pixsift.png")
    icon.save(HERE / "pixsift.icns")
    icon.save(HERE / "pixsift.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("logo written")
