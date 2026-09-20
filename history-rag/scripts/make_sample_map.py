# -*- coding: utf-8 -*-
"""Создаёт тестовую карту-иллюстрацию для проверки --images."""
from PIL import Image, ImageDraw

img = Image.new("RGB", (400, 300), (230, 220, 200))
draw = ImageDraw.Draw(img)
draw.rectangle([20, 20, 380, 280], outline=(120, 80, 40), width=4)
draw.text((40, 130), "KRYM 1853-1856 (demo map)", fill=(60, 40, 20))
img.save("scripts/sample_corpus/карты/krym_1853.png")
print("ok")
