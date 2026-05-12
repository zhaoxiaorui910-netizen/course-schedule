"""
为 课表.html 添加 PWA 支持（manifest + service worker 注册），输出到 pwa/index.html
"""
import os, shutil

BASE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(BASE, "课表.html")
DST = os.path.join(BASE, "pwa", "index.html")
ICONS = ["icon-192.png", "icon-512.png"]

# 复制图标到 pwa/
for fn in ICONS:
    shutil.copy2(os.path.join(BASE, fn), os.path.join(BASE, "pwa", fn))

with open(SRC, "r", encoding="utf-8") as f:
    html = f.read()

# 在 <title> 后插入 manifest + iOS meta
insert_after_title = """\
<link rel="manifest" href="manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="课程表">
<link rel="apple-touch-icon" href="icon-192.png">
"""
html = html.replace("<title>课程表</title>", "<title>课程表</title>\n" + insert_after_title)

# 在 </body> 前插入 service worker 注册
sw_script = """\
<script>
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('sw.js');
}
</script>
"""
html = html.replace("</body>", sw_script + "\n</body>")

with open(DST, "w", encoding="utf-8") as f:
    f.write(html)

print(f"生成: {DST}")
print("PWA 文件已就绪")
