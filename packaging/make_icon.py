"""Draws the PixSift app icon and writes .icns (macOS), .ico (Windows) and .png into this folder."""

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

HERE = Path(__file__).parent
S = 1024


def draw() -> Image.Image:
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    mask = Image.new("L", (S, S), 0)
    ImageDraw.Draw(mask).rounded_rectangle((64, 64, S - 64, S - 64), radius=200, fill=255)
    # Diagonal gradient background.
    bg = Image.new("RGBA", (S, S))
    top, bottom = (47, 111, 237), (24, 160, 88)
    px = bg.load()
    for y in range(S):
        for x in range(S):
            t = (x + y) / (2 * S)
            px[x, y] = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)) + (255,)
    img.paste(bg, mask=mask)
    d = ImageDraw.Draw(img)
    # Stacked photo cards + a face in front: "pictures, sorted by people".
    shadow = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(shadow).rounded_rectangle((300, 300, 780, 780), radius=60, fill=(0, 0, 0, 90))
    img.alpha_composite(shadow.filter(ImageFilter.GaussianBlur(24)))
    back = Image.new("RGBA", (S, S), (0, 0, 0, 0))
    ImageDraw.Draw(back).rounded_rectangle((230, 220, 690, 680), radius=56, fill=(255, 255, 255, 100))
    img.alpha_composite(back)
    d.rounded_rectangle((320, 330, 780, 790), radius=56, fill=(255, 255, 255, 255))
    d.ellipse((475, 410, 625, 560), fill=(47, 111, 237, 255))
    d.pieslice((410, 560, 690, 840), 180, 360, fill=(47, 111, 237, 255))
    d.rounded_rectangle((320, 330, 780, 790), radius=56, outline=(255, 255, 255, 255), width=8)
    return img


if __name__ == "__main__":
    icon = draw()
    icon.save(HERE / "pixsift.png")
    icon.save(HERE / "pixsift.ico", sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    icon.save(HERE / "pixsift.icns")
    print("icons written")
