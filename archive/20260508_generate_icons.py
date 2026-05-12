"""
生成 PWA 图标（192x192 和 512x512 PNG）
"""
from PIL import Image, ImageDraw, ImageFont
import os

SIZES = [192, 512]
COLOR = "#4A90D9"
OUT_DIR = os.path.dirname(os.path.abspath(__file__))

for size in SIZES:
    img = Image.new("RGBA", (size, size), COLOR)
    draw = ImageDraw.Draw(img)

    # 绘制白色 "课" 字
    font_size = int(size * 0.55)
    try:
        font = ImageFont.truetype("C:/Windows/Fonts/msyh.ttc", font_size)
    except OSError:
        font = ImageFont.load_default()

    text = "课"
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]

    draw.text((x, y), text, fill="white", font=font)
    path = os.path.join(OUT_DIR, f"icon-{size}.png")
    img.save(path, "PNG")
    print(f"生成: {path}")

print("图标生成完成")
