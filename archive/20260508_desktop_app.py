"""
课表桌面版 — 使用 pywebview 封装独立 HTML 为原生窗口应用
"""
import os, sys, webview


def resource_path():
    """PyInstaller 打包后取数据文件的路径"""
    if getattr(sys, "frozen", False):
        return sys._MEIPASS
    return os.path.dirname(os.path.abspath(__file__))


def main():
    html_path = os.path.join(resource_path(), "课表.html")
    if not os.path.exists(html_path):
        print(f"错误：找不到 {html_path}")
        print("请先运行 python export_standalone.py 生成课表 HTML 文件")
        sys.exit(1)

    webview.create_window(
        title="课程表",
        url=html_path,
        width=1280,
        height=800,
        min_size=(900, 600),
        resizable=True,
        fullscreen=False,
    )
    webview.start()


if __name__ == "__main__":
    main()
