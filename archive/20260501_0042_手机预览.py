"""手机预览服务 - 在手机上查看课表（支持 PWA 添加到主屏幕）"""
import http.server
import socket
import os
import re

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
HTML_FILE = os.path.join(BASE_DIR, "我的课表.html")
MANIFEST = {
    "name": "我的课表",
    "short_name": "课表",
    "description": "内蒙古工业大学课程表",
    "start_url": "/",
    "display": "standalone",
    "background_color": "#4A90D9",
    "theme_color": "#4A90D9",
    "icons": [
        {
            "src": "/icon.svg",
            "sizes": "any",
            "type": "image/svg+xml",
            "purpose": "any maskable"
        }
    ]
}
# 内联 SVG 图标：蓝色圆角方块 + 白色"课"字
ICON_SVG = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 512 512">
<rect width="512" height="512" rx="72" fill="#4A90D9"/>
<text x="256" y="340" text-anchor="middle" font-size="280" font-weight="bold" font-family="-apple-system,Helvetica,Arial,sans-serif" fill="white">课</text>
</svg>"""


class Handler(http.server.SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._serve_html()
        elif self.path == "/manifest.json":
            self._serve_json(MANIFEST)
        elif self.path == "/icon.svg":
            self._serve_svg()
        elif self.path == "/sw.js":
            self._serve_sw()
        else:
            super().do_GET()

    def _serve_html(self):
        if not os.path.exists(HTML_FILE):
            self.send_response(404)
            self.send_header("Content-Type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write("请先运行 export_html.py 生成课表文件".encode("utf-8"))
            return
        with open(HTML_FILE, "rb") as f:
            html = f.read().decode("utf-8")
        # 注入 PWA meta 标签
        pwa_tags = """<link rel="manifest" href="/manifest.json">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-title" content="课表">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<link rel="apple-touch-icon" href="/icon.svg">
<meta name="theme-color" content="#4A90D9">"""
        html = html.replace("</head>", pwa_tags + "\n</head>")
        # 注入 service worker 注册
        sw_script = """<script>
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('/sw.js');
}
</script>"""
        html = html.replace("</body>", sw_script + "\n</body>")
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(html.encode("utf-8"))))
        self.end_headers()
        self.wfile.write(html.encode("utf-8"))

    def _serve_json(self, obj):
        import json
        data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_svg(self):
        data = ICON_SVG.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "image/svg+xml")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _serve_sw(self):
        # Service Worker: 缓存课表 HTML 以支持离线访问
        sw = """self.addEventListener('install', function(e) {
  self.skipWaiting();
});
self.addEventListener('activate', function(e) {
  e.waitUntil(clients.claim());
});
self.addEventListener('fetch', function(e) {
  e.respondWith(
    fetch(e.request)["catch"](function() {
      return caches.match(e.request);
    })
  );
});"""
        data = sw.encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/javascript")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, format, *args):
        pass  # 不打印请求日志


def get_local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"


if __name__ == "__main__":
    if not os.path.exists(HTML_FILE):
        print("错误：未找到「我的课表.html」，请先运行 export_html.py 生成")
        exit(1)

    ip = get_local_ip()
    port = 8000

    print("=" * 50)
    print("     课程表 - 手机预览")
    print("=" * 50)
    print()
    print(f" 电脑端打开：http://localhost:{port}")
    print(f" 手机端打开：http://{ip}:{port}")
    print()
    print(" 请确保手机和电脑连接同一个 WiFi")
    print(" 在手机浏览器中输入上面地址")
    print()
    print(" 手机 Safari 用户：点「分享」→「添加到主屏幕」")
    print(" 手机 Chrome 用户：点菜单 →「添加到主屏幕」")
    print()
    print(" 按 Ctrl+C 关闭服务")
    print("=" * 50)
    print()

    server = http.server.HTTPServer(("0.0.0.0", port), Handler)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n服务已关闭")
        server.server_close()
