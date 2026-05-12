"""
桌面版课程表 — pywebview 原生窗口封装
"""
import os, sys
from PIL import Image
import webview

BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def ensure_icon():
    """将 logo.png 转为 logo.ico（pywebview Windows 需要 .ico 格式）"""
    png_path = os.path.join(BASE_DIR, "logo.png")
    ico_path = os.path.join(BASE_DIR, "logo.ico")
    if not os.path.exists(png_path):
        return None
    if not os.path.exists(ico_path):
        img = Image.open(png_path)
        img.save(ico_path, format="ico", sizes=[(256, 256)])
    return ico_path


def main():
    html_path = os.path.join(BASE_DIR, "课表.html")
    if not os.path.exists(html_path):
        print("错误：未找到 课表.html，请先运行 python export_standalone.py")
        sys.exit(1)

    ico_path = ensure_icon()
    window = webview.create_window(
        "课程表",
        html_path,
        width=1200,
        height=800,
        min_size=(800, 600),
        resizable=True,
        text_select=True,
    )
    webview.start(icon=ico_path)


if __name__ == "__main__":
    main()
