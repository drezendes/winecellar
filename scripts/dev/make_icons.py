"""Generate the PWA/home-screen icons (a cream wine glass on wine red).

Run: .venv\\Scripts\\python.exe scripts\\dev\\make_icons.py
Writes static/icons/icon-512.png, icon-192.png, apple-touch-icon.png.
Idempotent — regenerates the files each run.
"""

from pathlib import Path

from PIL import Image, ImageDraw

WINE = (114, 47, 55)
WINE_DEEP = (78, 31, 38)
CREAM = (250, 246, 240)

OUT_DIR = Path(__file__).resolve().parents[2] / "static" / "icons"


def draw_glass(size=512):
    """A filled wine-glass silhouette, centered with maskable-safe margins."""
    img = Image.new("RGB", (size, size), WINE)
    draw = ImageDraw.Draw(img)

    s = size / 512  # geometry authored on a 512 grid

    def xy(*coords):
        return [c * s for c in coords]

    # Subtle vignette ring so the flat background reads less sterile.
    draw.ellipse(xy(-160, -160, 672, 672), outline=WINE_DEEP, width=int(90 * s))

    # Bowl: bottom half-disc (flat rim at the top).
    draw.pieslice(xy(146, 62, 366, 302), 0, 180, fill=CREAM)
    # Wine inside the bowl, flat surface slightly below the rim.
    draw.pieslice(xy(162, 94, 350, 286), 0, 180, fill=WINE_DEEP)
    # Stem and foot.
    draw.rectangle(xy(244, 296, 268, 396), fill=CREAM)
    draw.ellipse(xy(178, 386, 334, 428), fill=CREAM)

    return img


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    base = draw_glass(512)
    base.save(OUT_DIR / "icon-512.png")
    base.resize((192, 192), Image.LANCZOS).save(OUT_DIR / "icon-192.png")
    base.resize((180, 180), Image.LANCZOS).save(OUT_DIR / "apple-touch-icon.png")
    print(f"wrote 3 icons to {OUT_DIR}")


if __name__ == "__main__":
    main()
