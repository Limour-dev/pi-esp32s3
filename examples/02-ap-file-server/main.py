# main.py —— 例程 02：WiFi 热点 + 文件浏览服务器 + LED 控制
#
# 功能：板子开启一个 WiFi 热点（默认 ESP-AP / 12345678），
#       手机/电脑连接该热点后，浏览器打开 http://192.168.4.1
#       即可看到板子 Flash 里的文件列表，点文件名可查看/下载内容；
#       页面底部提供 WS2812 灯珠颜色控制（取色器 + 预设色 + 熄灭）。
#
# 状态灯（WS2812，GPIO48）：
#   红色 = 正在启动热点；绿色 = 服务器就绪；蓝色 = 收到一次请求；
#   网页设置颜色后，灯珠保持用户设置的颜色

import gc
import os
import time
import network
import neopixel
from machine import Pin
import config

try:
    import usocket as socket
except ImportError:
    import socket

# ---------------- 状态灯（WS2812） ----------------

np = neopixel.NeoPixel(Pin(config.WS2812_PIN), 1)

led_user = None  # 网页设置的用户颜色；None = 未设置，走默认状态色


def set_color(r, g, b):
    np[0] = (r, g, b)
    np.write()


def set_led_user(r, g, b):
    """网页控制：设置颜色并保持。"""
    global led_user
    led_user = (r, g, b)
    set_color(r, g, b)


def restore_led():
    """请求处理完后恢复显示（用户色或默认绿色）。"""
    if led_user is None:
        set_color(0, 255, 0)
    else:
        set_color(*led_user)

# ---------------- WiFi 热点 ----------------

def start_ap():
    set_color(255, 0, 0)  # 红色：正在启动
    password = config.AP_PASSWORD
    if password and len(password) < 8:
        print("警告: AP_PASSWORD 不足 8 位，无法启用 WPA2，热点将以开放网络运行！")
        password = ""
    ap = network.WLAN(network.AP_IF)
    ap.config(
        essid=config.AP_SSID,
        authmode=network.AUTH_WPA_WPA2_PSK if password else network.AUTH_OPEN,
        password=password,
        max_clients=config.AP_MAX_CLIENTS,
        channel=config.AP_CHANNEL,
    )
    ap.active(True)
    while not ap.active():
        time.sleep(0.1)
    ip = ap.ifconfig()[0]
    print("=" * 56)
    print("WiFi 热点已开启: %s (密码: %s)" % (config.AP_SSID, password or "无"))
    print("手机连接该热点后，浏览器打开:")
    print("    http://%s:%d/" % (ip, config.SERVER_PORT))
    print("=" * 56)
    return ip


# ---------------- HTTP 文件服务器 ----------------

MIME = {
    ".html": "text/html; charset=utf-8",
    ".htm": "text/html; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".txt": "text/plain; charset=utf-8",
    ".py": "text/plain; charset=utf-8",
    ".md": "text/plain; charset=utf-8",
    ".json": "text/plain; charset=utf-8",
    ".log": "text/plain; charset=utf-8",
    ".csv": "text/plain; charset=utf-8",
    ".bin": "application/octet-stream",
}


def mime_of(name):
    # 注意：本固件没有 os.path，手写取扩展名
    dot = name.rfind(".")
    ext = name[dot:].lower() if dot >= 0 else ""
    return MIME.get(ext, "application/octet-stream")


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def build_listing(ip):
    """生成根目录 / 的文件列表 HTML 页面。"""
    rows = []
    for name in sorted(os.listdir("/")):
        try:
            size = os.stat("/" + name)[6]
        except OSError:
            size = 0
        rows.append(
            '<li><a href="/%s">%s</a><span class="size">%d B</span></li>'
            % (name, esc(name), size)
        )
    return (
        "<!DOCTYPE html>\n"
        '<html lang="zh-CN">\n'
        "<head>\n"
        '<meta charset="utf-8">\n'
        '<meta name="viewport" content="width=device-width, initial-scale=1">\n'
        "<title>ESP32 文件浏览器</title>\n"
        "<style>\n"
        "body{font-family:system-ui,sans-serif;margin:0;padding:16px;"
        "background:#0f172a;color:#e2e8f0;}\n"
        "h1{font-size:1.2rem;}\n"
        "ul{list-style:none;padding:0;}\n"
        "li{display:flex;justify-content:space-between;gap:8px;padding:10px 12px;"
        "background:#1e293b;border-radius:8px;margin-bottom:8px;word-break:break-all;}\n"
        "a{color:#38bdf8;text-decoration:none;}\n"
        ".size{color:#64748b;font-size:0.85rem;white-space:nowrap;}\n"
        "footer{color:#64748b;font-size:0.8rem;margin-top:16px;text-align:center;}\n"
        "h2{font-size:1rem;margin:24px 0 8px;}\n"
        ".ledctrl{background:#1e293b;border-radius:8px;padding:12px;margin-top:8px;}\n"
        ".ledrow{display:flex;flex-wrap:wrap;gap:8px;align-items:center;margin:8px 0;}\n"
        "button{background:#2563eb;color:#fff;border:none;border-radius:6px;padding:8px 12px;font-size:0.9rem;cursor:pointer;}\n"
        "button:active{background:#1d4ed8;}\n"
        "input[type=color]{width:56px;height:40px;border:none;background:none;padding:0;cursor:pointer;}\n"
        "</style>\n"
        "</head>\n"
        "<body>\n"
        "<h1>&#128193; ESP32 文件列表</h1>\n"
        "<ul>%s</ul>\n"
        "<h2>&#128276; LED 控制（WS2812）</h2>\n"
        "<div class=\"ledctrl\">\n"
        "  <div class=\"ledrow\">\n"
        "    <input type=\"color\" id=\"picker\" value=\"#ff0000\">\n"
        "    <button onclick=\"sendColor()\">设置颜色</button>\n"
        "    <button onclick=\"sendHex('000000')\">熄灭</button>\n"
        "    <button onclick=\"sendHex('00ff00')\">恢复绿色</button>\n"
        "  </div>\n"
        "  <div class=\"ledrow\">\n"
        "    <button onclick=\"sendHex('ff0000')\">红</button>\n"
        "    <button onclick=\"sendHex('00ff00')\">绿</button>\n"
        "    <button onclick=\"sendHex('0000ff')\">蓝</button>\n"
        "    <button onclick=\"sendHex('ffff00')\">黄</button>\n"
        "    <button onclick=\"sendHex('00ffff')\">青</button>\n"
        "    <button onclick=\"sendHex('ff00ff')\">品红</button>\n"
        "    <button onclick=\"sendHex('ffffff')\">白</button>\n"
        "  </div>\n"
        "</div>\n"
        "<script>\n"
        "function sendHex(hex){location.href='/setled?hex='+hex;}\n"
        "function sendColor(){var v=document.getElementById('picker').value.replace('#','');sendHex(v);}\n"
        "</script>\n"
        "<footer>ESP32-S3 &middot; %s:%d</footer>\n"
        "</body>\n"
        "</html>\n"
    ) % ("\n".join(rows), ip, config.SERVER_PORT)


def _send_response(conn, code, reason, ctype, body):
    head = (
        "HTTP/1.1 %d %s\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n"
        "\r\n" % (code, reason, ctype, len(body))
    )
    conn.send(head.encode("utf-8"))
    if body:
        conn.send(body)


def _send_404(conn):
    body = (
        "<html><body style='font-family:sans-serif'>"
        "<h1>404 Not Found</h1>"
        "<p><a href='/'>返回文件列表</a></p>"
        "</body></html>"
    ).encode("utf-8")
    _send_response(conn, 404, "Not Found", "text/html; charset=utf-8", body)


def _send_redirect(conn, location):
    head = (
        "HTTP/1.1 302 Found\r\n"
        "Location: %s\r\n"
        "Content-Length: 0\r\n"
        "Connection: close\r\n"
        "\r\n" % location
    ).encode("utf-8")
    conn.send(head)


def _parse_query(query):
    """解析 /setled?hex=ff0000 这类查询串，返回参数字典。"""
    params = {}
    if query:
        for kv in query.split("&"):
            if "=" in kv:
                k, v = kv.split("=", 1)
                params[k] = v
    return params


def _clamp(v, lo=0, hi=255):
    if v < lo:
        return lo
    if v > hi:
        return hi
    return v


def handle_setled(conn, query):
    """网页 LED 控制：/setled?hex=RRGGBB 或 /setled?r=&g=&b=。"""
    params = _parse_query(query)
    r = g = b = 0
    try:
        if "hex" in params:
            h = params["hex"].strip()
            if len(h) == 6:
                r = int(h[0:2], 16)
                g = int(h[2:4], 16)
                b = int(h[4:6], 16)
        else:
            r = _clamp(int(params.get("r", 0)))
            g = _clamp(int(params.get("g", 0)))
            b = _clamp(int(params.get("b", 0)))
    except ValueError:
        pass
    set_led_user(r, g, b)
    print("LED 设置为: rgb(%d,%d,%d)" % (r, g, b))
    _send_redirect(conn, "/")


def _read_request(conn):
    """读完请求头（以空行 \r\n\r\n 结尾），最多 4KB。"""
    buf = b""
    while b"\r\n\r\n" not in buf and len(buf) < 4096:
        chunk = conn.recv(1024)
        if not chunk:
            break
        buf += chunk
    return buf.decode("utf-8", "ignore")


def serve_listing(conn, ip):
    html = build_listing(ip).encode("utf-8")
    _send_response(conn, 200, "OK", "text/html; charset=utf-8", html)


def serve_file(conn, path):
    name = path.lstrip("/")
    if not name or "/" in name or ".." in name:
        _send_404(conn)
        return
    try:
        size = os.stat("/" + name)[6]
    except OSError:
        _send_404(conn)
        return
    head = (
        "HTTP/1.1 200 OK\r\n"
        "Content-Type: %s\r\n"
        "Content-Length: %d\r\n"
        "Connection: close\r\n"
        "\r\n" % (mime_of(name), size)
    ).encode("utf-8")
    conn.send(head)
    with open("/" + name, "rb") as f:
        while True:
            chunk = f.read(1024)
            if not chunk:
                break
            conn.send(chunk)


def handle_request(conn, ip):
    try:
        conn.settimeout(5)
        req = _read_request(conn)
        lines = req.split("\r\n")
        if not lines or not lines[0]:
            return
        parts = lines[0].split(" ")
        if len(parts) < 2:
            return
        method, path = parts[0], parts[1]
        route, _, query = path.partition("?")
        if method != "GET":
            _send_response(conn, 405, "Method Not Allowed",
                           "text/plain; charset=utf-8",
                           b"only GET supported")
            return
        if route == "/setled":
            handle_setled(conn, query)
        elif route in ("/", ""):
            serve_listing(conn, ip)
        else:
            serve_file(conn, route)
    except Exception as e:
        print("请求处理异常:", e)
    finally:
        try:
            conn.close()
        except OSError:
            pass


def run_server(ip, port):
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(("0.0.0.0", port))
    s.listen(2)
    print("HTTP 服务器已启动: http://%s:%d/" % (ip, port))
    set_color(0, 255, 0)  # 绿色：就绪
    while True:
        try:
            conn, addr = s.accept()
            print("客户端接入:", addr)
            set_color(0, 0, 255)  # 蓝色：处理请求
            handle_request(conn, ip)
            restore_led()  # 恢复显示（用户色或默认绿色）
        except Exception as e:
            print("accept 异常:", e)
            time.sleep(0.5)


# ---------------- 主流程 ----------------

print("=" * 56)
print("ESP32-S3 例程 02：WiFi 热点 + 文件浏览服务器")
print("=" * 56)
ip = start_ap()
gc.collect()
run_server(ip, config.SERVER_PORT)
