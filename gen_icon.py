# -*- coding: utf-8 -*-
"""生成 glance/assets/icon.ico —— 浅蓝圆角底 + 白色放大镜。"""
import os

from PIL import Image, ImageDraw

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "glance", "assets", "icon.ico")
BLUE = (47, 109, 246, 255)
WHITE = (255, 255, 255, 255)


def make(size):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=int(size * 0.22), fill=BLUE)
    cx, cy, rad = int(size * 0.43), int(size * 0.43), int(size * 0.20)
    w = max(2, int(size * 0.075))
    d.ellipse([cx - rad, cy - rad, cx + rad, cy + rad], outline=WHITE, width=w)
    x1, y1 = cx + int(rad * 0.72), cy + int(rad * 0.72)
    d.line([x1, y1, int(size * 0.75), int(size * 0.75)], fill=WHITE, width=int(w * 1.25))
    return img


def main():
    sizes = [16, 24, 32, 48, 64, 128, 256]
    base = make(256)
    base.save(OUT, format="ICO", sizes=[(s, s) for s in sizes])
    print("wrote", OUT)


if __name__ == "__main__":
    main()
