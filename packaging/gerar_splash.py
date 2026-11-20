"""Gera packaging/splash.png, o ecrã de arranque do executável do Windows (enquanto o PyInstaller descompacta).

Correr na pasta do projeto, com o Pillow instalado:  python packaging/gerar_splash.py
"""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
W, H = 480, 300
BG, FG, MUTED = (33, 37, 41), (233, 236, 239), (173, 181, 189)


def font(size, bold=False):
    names = (["DejaVuSans-Bold.ttf", "arialbd.ttf"] if bold else ["DejaVuSans.ttf", "arial.ttf"])
    for name in names:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


def main():
    img = Image.new("RGB", (W, H), BG)
    icon = Image.open(ROOT / "portfolio_investimentos" / "static" / "icons" / "icon-512.png").convert("RGBA")
    icon = icon.resize((112, 112), Image.LANCZOS)
    img.paste(icon, ((W - 112) // 2, 48), icon)
    draw = ImageDraw.Draw(img)
    for text, f, y, color in (("Portfolio Investimentos", font(24, bold=True), 186, FG),
                              ("A abrir…", font(14), 228, MUTED)):
        w = draw.textlength(text, font=f)
        draw.text(((W - w) / 2, y), text, font=f, fill=color)
    img.save(ROOT / "packaging" / "splash.png", optimize=True)
    print("packaging/splash.png")


if __name__ == "__main__":
    main()
