# test_mqtt_board.py —— 板端 WiFi+MQTT 逻辑测试：在宿主 Python 上 mock
# BLE/network/ssl/umqtt/硬件模块，直接驱动 main.py 的 _drain_cmds 真实接收路径，
# 验证 WiFi 命令（扫描/连接/断开/忘记/状态）、MQTT 命令（SET/FORGET/STATUS）、
# MQTT 连接状态机（WiFi 就绪才连、订阅灯珠主题、收消息控灯、发布状态、断线重连）与
# /wifi.json 持久化。
# 运行：python3 test/test_mqtt_board.py
import os
import sys
import types
import time as _t
import json as _json
import tempfile

# 宿主没有 time.sleep_ms，补一个短桩（缩短连接等待）
_t.sleep_ms = lambda ms: _t.sleep(min(ms / 1000.0, 0.01))
_t.ticks_ms = lambda: int(_t.time() * 1000)
_t.ticks_diff = lambda a, b: a - b

# 让 import main 找到例程根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------- mock：bluetooth / neopixel / machine / ubinascii / ujson / ssl / umqtt / network ----------------
class FakeBle:
    def gatts_read(self, h):
        return b"\xff\x00\x40"

    def gap_disconnect(self, cid):
        print("  >> gap_disconnect(%s)" % cid)

    def gatts_register_services(self, s):
        return ((16,), (19, 21))


bluetooth = types.ModuleType("bluetooth")
bluetooth.BLE = FakeBle
bluetooth.UUID = lambda s: s
bluetooth.FLAG_WRITE = 1
bluetooth.FLAG_WRITE_NO_RESPONSE = 2
bluetooth.FLAG_READ = 4
bluetooth.FLAG_NOTIFY = 8
sys.modules["bluetooth"] = bluetooth

neopixel = types.ModuleType("neopixel")


class NP:
    def __init__(s, p, n):
        s._writes = 0

    def __setitem__(s, i, v):
        pass

    def write(s):
        s._writes += 1


neopixel.NeoPixel = NP
sys.modules["neopixel"] = neopixel

machine = types.ModuleType("machine")
machine.Pin = lambda p: None
sys.modules["machine"] = machine

ubinascii = types.ModuleType("ubinascii")
ubinascii.b2a_base64 = lambda b: __import__("base64").b64encode(b) + b"\n"
ubinascii.a2b_base64 = lambda s: __import__("base64").b64decode(s)
ubinascii.hexlify = lambda b: __import__("binascii").hexlify(b)
sys.modules["ubinascii"] = ubinascii

ujson = types.ModuleType("ujson")
ujson.dumps = _json.dumps
ujson.loads = _json.loads
sys.modules["ujson"] = ujson

# ---- ssl mock ----
ssl = types.ModuleType("ssl")
ssl.PROTOCOL_TLS_CLIENT = 0
ssl.CERT_NONE = 1
ssl.CERT_REQUIRED = 2


class SSLContext:
    def __init__(self, proto):
        self.proto = proto
        self.verify_mode = None
        self.loaded = None

    def load_verify_locations(self, cafile=None, path=None, cadata=None):
        self.loaded = cadata if cadata is not None else (cafile or path)

    def wrap_socket(self, sock, server_hostname=None, **kw):
        return sock


ssl.SSLContext = SSLContext
sys.modules["ssl"] = ssl

# ---- ntptime mock（宿主没有） ----
ntptime = types.ModuleType("ntptime")
ntptime.settime = lambda: None
sys.modules["ntptime"] = ntptime

# ---- umqtt.simple mock ----
umqtt = types.ModuleType("umqtt")
umqtt.simple = types.ModuleType("umqtt.simple")


class FakeMQTT:
    instances = []
    connect_should_fail = False   # 类级：下次 connect 抛异常（模拟认证失败/拒连）

    def __init__(self, client_id=None, server=None, port=0, user=None,
                 password=None, keepalive=0, ssl=None, ssl_params={}):
        self.client_id = client_id
        self.server = server
        self.port = port
        self.user = user
        self.password = password
        self.keepalive = keepalive
        self.ssl = ssl
        self.sock = object()
        self.cb = None
        self.lw = None
        self.subscribed = []
        self.published = []
        self.pings = 0
        self.disconnected = 0
        self.connect_calls = 0
        self.connect_fail = False      # 实例级：下次 connect 抛异常（备用）
        self.msgs = []                 # check_msg 时按序派发的 (topic, msg)
        self.check_raise = None        # 下次 check_msg 抛异常（模拟断线）
        FakeMQTT.instances.append(self)

    def set_callback(self, f):
        self.cb = f

    def set_last_will(self, t, m, retain=False, qos=0):
        self.lw = (t, m, retain, qos)

    def connect(self, clean_session=True, timeout=None):
        self.connect_calls += 1
        if FakeMQTT.connect_should_fail:
            FakeMQTT.connect_should_fail = False
            raise OSError("connection refused")
        if self.connect_fail:
            self.connect_fail = False
            raise OSError("connection refused")
        return 0

    def subscribe(self, topic, qos=0):
        self.subscribed.append((topic, qos))

    def publish(self, topic, msg, retain=False, qos=0):
        self.published.append((topic, msg, retain, qos))

    def ping(self):
        self.pings += 1

    def check_msg(self):
        if self.check_raise is not None:
            e = self.check_raise
            self.check_raise = None
            raise e
        if self.msgs:
            t, m = self.msgs.pop(0)
            if self.cb:
                self.cb(t, m)
        return None

    def disconnect(self):
        self.disconnected += 1


umqtt.simple.MQTTClient = FakeMQTT
sys.modules["umqtt"] = umqtt
sys.modules["umqtt.simple"] = umqtt.simple

# ---- network mock ----
class FakeWlan:
    """行为可编程的假 WLAN：_result ∈ ok / wrong / notfound / timeout"""

    def __init__(self, if_id):
        self.if_id = if_id
        self._active = False
        self._cfg = {}
        self._ifc = ("0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0")
        self._conn = None
        self._result = "ok"
        self._disconnect_calls = 0
        self._scan_calls = 0

    def active(self, v=None):
        if v is None:
            return self._active
        self._active = v
        if v:
            if self.if_id == network.STA_IF:
                self._ifc = ("0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0")
        return v

    def config(self, *args, **kw):
        if kw:
            self._cfg.update(kw)
            return None
        if args and args[0] == "mac":
            return bytes.fromhex("24a132b4c5d6")
        return self._cfg.get(args[0], "") if args else self._cfg

    def ifconfig(self, addr=None):
        return self._ifc

    def scan(self):
        self._scan_calls += 1
        return [
            (b"MyWiFi", bytes.fromhex("112233445566"), 1, -40, 3, False),
            (b"OpenNet", bytes.fromhex("aabbccddeeff"), 6, -70, 0, False),
            ("\u6d4b\u8bd5".encode("utf-8"), b"\x01" * 6, 11, -55, 7, False),  # 中文 SSID
        ]

    def connect(self, ssid, pwd):
        self._conn = {"ssid": ssid, "pwd": pwd}
        if self._result == "ok":
            self._ifc = ("192.168.1.100", "255.255.255.0", "192.168.1.1", "8.8.8.8")
        else:
            self._ifc = ("0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0")

    def disconnect(self):
        self._disconnect_calls += 1
        self._conn = None
        self._ifc = ("0.0.0.0", "0.0.0.0", "0.0.0.0", "0.0.0.0")

    def isconnected(self):
        return self._result == "ok" and self._conn is not None

    def status(self, what=None):
        if what is not None:
            return 0
        if self._result == "wrong":
            return network.STAT_WRONG_PASSWORD
        if self._result == "notfound":
            return network.STAT_NO_AP_FOUND
        if self._result == "timeout":
            return network.STAT_CONNECTING
        return network.STAT_GOT_IP


network = types.ModuleType("network")
network.STA_IF = 0
network.AP_IF = 1
network.AUTH_OPEN = 0
network.AUTH_WEP = 1
network.AUTH_WPA_PSK = 2
network.AUTH_WPA2_PSK = 3
network.AUTH_WPA_WPA2_PSK = 4
network.AUTH_WPA2_ENTERPRISE = 5
network.AUTH_WPA3_PSK = 6
network.AUTH_WPA2_WPA3_PSK = 7
network.AUTH_WAPI_PSK = 8
network.AUTH_OWE = 9
network.STAT_IDLE = 1000
network.STAT_CONNECTING = 1001
network.STAT_WRONG_PASSWORD = 1002
network.STAT_NO_AP_FOUND = 1003
network.STAT_CONNECT_FAIL = 1004
network.STAT_ASSOC_FAIL = 1005
network.STAT_HANDSHAKE_TIMEOUT = 1006
network.STAT_NO_AP_FOUND_IN_AUTHMODE_THRESHOLD = 1007
network.STAT_NO_AP_FOUND_IN_RSSI_THRESHOLD = 1008
network.STAT_NO_AP_FOUND_W_COMPATIBLE_SECURITY = 1009
network.STAT_GOT_IP = 1010
network.WLAN = FakeWlan
sys.modules["network"] = network

import main  # noqa: E402

# ---- 把配置指到临时文件，缩短超时/重试间隔 ----
_tmpdir = tempfile.mkdtemp(prefix="mqtt05_")
main.WIFI_CFG_FILE = os.path.join(_tmpdir, "wifi.json")
main.MQTT_CFG_FILE = os.path.join(_tmpdir, "mqtt.json")
main.STA_CONNECT_TIMEOUT = 1
main.MQTT_RETRY_INTERVAL = 0          # 断线后立即重试（测试快）
main.MQTT_CA_CERT_FILE = os.path.join(_tmpdir, "ca.pem")
with open(main.MQTT_CA_CERT_FILE, "wb") as f:
    f.write(b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n")
main.ble = FakeBle()
main.conn_id = 99
main.notified = []
main._notify = lambda t: main.notified.append(t)
main.authed = True

b64 = lambda s: __import__("base64").b64encode(s.encode("utf-8")).decode("ascii")


def drain(ls):
    main.pending = [bytes(l + "\n", "utf-8") for l in ls]
    main._drain_cmds()
    out = main.notified
    main.notified = []
    return out


ok = True


def chk(name, cond, extra=""):
    global ok
    print(("PASS " if cond else "FAIL ") + name, extra)
    ok = ok and cond


def read_cfg_file():
    try:
        with open(main.WIFI_CFG_FILE) as f:
            return _json.load(f)
    except OSError:
        return None


def read_mqtt_file():
    try:
        with open(main.MQTT_CFG_FILE) as f:
            return _json.load(f)
    except OSError:
        return None


last_client = lambda: FakeMQTT.instances[-1]

# ================= WiFi 部分（回归例程 04，AP 已移除） =================

# ---- 认证门禁 ----
main.authed = False
chk("未认证 MQTT_STATUS 被门禁", drain(["MQTT_STATUS"]) == ["ERR auth required"])
main.authed = True

# ---- 扫描 ----
out = drain(["WIFI_SCAN"])
chk("扫描返回 3 项 + DONE", len(out) == 4 and out[-1] == "DONE", out)
chk("中文 SSID 走 base64", out[2] == "N 7 11 -55 " + b64("\u6d4b\u8bd5"))

# ---- 连接成功 → 保存配置（含 mqtt 键不在内） ----
out = drain(["WIFI_CONNECT %s %s" % (b64("MyWiFi"), b64("pass123"))])
chk("连接成功响应", out == ["WIFI connecting MyWiFi", "WIFI OK 192.168.1.100", "DONE"], out)
chk("wifi.json 保存 sta", read_cfg_file() == {"sta": {"ssid": "MyWiFi", "password": "pass123"}})

# ---- 状态（无 AP 行） ----
out = drain(["WIFI_STATUS"])
chk("WIFI_STATUS 行数 3（STA+SAVED+DONE，无 AP）", len(out) == 3 and out[-1] == "DONE", out)
chk("状态行 STA CONNECTED", out[0].startswith("STA CONNECTED " + b64("MyWiFi")), out[0])
chk("状态行无 AP", not any(l.startswith("AP ") for l in out))

# ---- 连接失败：错密码不覆盖已保存配置 ----
main.sta_if.disconnect()
main.sta_if._result = "wrong"
out = drain(["WIFI_CONNECT %s %s" % (b64("MyWiFi"), b64("bad"))])
chk("错密码以 ERR 收尾", out[-1] == "ERR wrong password", out[-1])
chk("错密码不覆盖已保存配置", main.saved_sta == {"ssid": "MyWiFi", "password": "pass123"})

# ================= MQTT 配置命令 =================

# ---- MQTT_SET 保存配置 ----
main.sta_if._result = "ok"
main._last_mqtt_attempt = 0
out = drain(["MQTT_SET %s 8883 %s %s" % (b64("mqtt.example.com"), b64("testuser"), b64("secret"))])
chk("MQTT_SET 响应", out == ["OK mqtt configured", "DONE"], out)
d = read_mqtt_file()
chk("mqtt.json 保存 mqtt",
    d and d["mqtt"] == {"host": "mqtt.example.com", "port": 8883, "user": "testuser", "password": "secret"}, d)
chk("wifi.json 不受 MQTT_SET 影响", read_cfg_file() == {"sta": {"ssid": "MyWiFi", "password": "pass123"}})
chk("MQTT 配置未写进 wifi.json", "mqtt" not in (read_cfg_file() or {}))
main._mqtt_tick()   # 让状态机跑一轮（WiFi 未连 → disconnected）
chk("MQTT 未连接前状态为 disconnected", main.mqtt_state == "disconnected")

# ---- MQTT_SET 参数校验 ----
out = drain(["MQTT_SET %s 0 %s %s" % (b64("h"), b64("u"), b64("p"))])
chk("端口 0 被拒", out == ["ERR bad port"], out)
out = drain(["MQTT_SET %s 70000 %s %s" % (b64("h"), b64("u"), b64("p"))])
chk("端口 70000 被拒", out == ["ERR bad port"], out)
out = drain(["MQTT_SET %s 8883 %s" % (b64("h"), b64("u"))])
chk("3 参数（缺密码）被接受，密码置空", out == ["OK mqtt configured", "DONE"] and main.mqtt_cfg["password"] == "", out)
drain(["MQTT_SET %s 8883 %s %s" % (b64("mqtt.example.com"), b64("testuser"), b64("secret"))])  # 恢复正式配置
out = drain(["MQTT_SET %s 8883 %s %s" % (b64(""), b64("u"), b64("p"))])
chk("空 host 被拒（参数折叠为 bad args）", out[0].startswith("ERR"), out)

# ---- MQTT_STATUS（配置了、未连接） ----
out = drain(["MQTT_STATUS"])
chk("MQTT_STATUS 行格式",
    out[0] == "MQTT DISCONNECTED"
    and out[1] == "MQTT_CFG %s 8883 %s" % (b64("mqtt.example.com"), b64("testuser"))
    and out[2] == "MQTT_LED %s" % b64("esp32s3/led")
    and out[3] == "DONE", out)

# ================= MQTT 连接状态机 =================

# ---- WiFi 未连接 → 不连 MQTT ----
main.sta_if.disconnect()
n0 = len(FakeMQTT.instances)
main._mqtt_tick()
chk("WiFi 断时 mqtt_state=disconnected 且不建连", main.mqtt_state == "disconnected" and len(FakeMQTT.instances) == n0)

# ---- WiFi 已连接 → 自动建连：TLS 上下文 + 订阅 + 上线发布 ----
main.sta_if._result = "ok"
main._last_mqtt_attempt = 0
out = drain(["WIFI_CONNECT %s %s" % (b64("MyWiFi"), b64("pass123"))])  # 确保 STA 已连
main._last_mqtt_attempt = 0
main._mqtt_tick()
cli = last_client()
chk("MQTT 已连接", main.mqtt_state == "connected")
chk("MQTT 参数正确（server/port/user/pass/keepalive）",
    cli.server == "mqtt.example.com" and cli.port == 8883
    and cli.user == b"testuser" and cli.password == b"secret"
    and cli.keepalive == main.MQTT_KEEPALIVE)
chk("客户端 ID 用 MAC 尾部", cli.client_id == b"esp32s3-b4c5d6", cli.client_id)
chk("ssl 上下文传入且加载了 CA", isinstance(cli.ssl, SSLContext) and cli.ssl.loaded == b"-----BEGIN CERTIFICATE-----\nfake\n-----END CERTIFICATE-----\n")
chk("LWT 已设置（offline，保留）", cli.lw == (b"esp32s3/status", b"offline", True, 0))
chk("已订阅灯珠主题", cli.subscribed == [(b"esp32s3/led", 0)])
pub = {t: (m, r) for t, m, r, q in cli.published}
chk("上线发布 online（保留）", pub.get(b"esp32s3/status") == (b"online", True))
ind_cyan = ("#%02x%02x%02x" % main._dim_indicator((0, 180, 180))).encode()
chk("当前颜色发布到 state（保留，指示灯缩亮）", pub.get(b"esp32s3/led/state") == (ind_cyan, True), pub)  # WiFi 已连：青

# ---- 保持连接：check_msg + 周期性 ping ----
main._last_ping = 0
main._mqtt_tick()
chk("connected 时 check_msg 不抛异常", main.mqtt_state == "connected")
chk("keepalive/2 到点后 ping 一次", cli.pings >= 1)

# ---- MQTT 消息控灯：#RRGGBB ----
cli.msgs.append((b"esp32s3/led", b"#ff0000"))
main._mqtt_tick()
chk("MQTT #ff0000 → led_user=(255,0,0)", main.led_user == (255, 0, 0))
chk("MQTT 色来源标记为 mqtt", main.led_user_src == "mqtt")
main.apply_led()
chk("灯珠已写（np.write 被调用）", main.np._writes >= 1)
chk("颜色发布到 state（retained）", cli.published[-1][:2] == (b"esp32s3/led/state", b"#ff0000") and cli.published[-1][2] is True)

# ---- MQTT 消息控灯：r,g,b 与非法负载 ----
cli.msgs.append((b"esp32s3/led", b"0, 128, 255"))
main._mqtt_tick()
chk("MQTT '0,128,255' → led_user=(0,128,255)", main.led_user == (0, 128, 255))
cli.msgs.append((b"esp32s3/led", b"bogus"))
before = main.led_user
main._mqtt_tick()
chk("非法负载被忽略（颜色不变）", main.led_user == before)
cli.msgs.append((b"esp32s3/other", b"#00ff00"))
main._mqtt_tick()
chk("非灯珠主题消息被忽略", main.led_user == (0, 128, 255))

# ---- BLE 断开只清 BLE 色，MQTT 色保留 ----
main.led_user = (9, 9, 9)
main.led_user_src = "mqtt"
main._irq(bluetooth.IRQ_CENTRAL_DISCONNECT if hasattr(bluetooth, "IRQ_CENTRAL_DISCONNECT") else 2, (0,))
chk("BLE 断开不清 MQTT 色", main.led_user == (9, 9, 9))
main.led_user_src = "ble"
main._irq(2, (0,))
chk("BLE 断开清 BLE 色", main.led_user is None)

# ---- 断线检测：check_msg 抛 OSError → 断开 ----
cli.check_raise = OSError(104)      # ECONNRESET
main._mqtt_tick()
chk("check_msg 异常 → 断开", main.mqtt_state == "disconnected")
chk("客户端已 disconnect", cli.disconnected >= 1)

# ---- 时钟未校准（TLS 校验开启时）不连 MQTT ----
main._mqtt_disconnect()
orig_sane = main._clock_sane
main._clock_sane = lambda: False
main.mqtt_err = None
main._last_mqtt_attempt = 0
main._mqtt_tick()
chk("时钟未校准 → 不建连且提示等 NTP", main.mqtt_state == "disconnected" and len(FakeMQTT.instances) == 1 and main.mqtt_err is not None and "NTP" in main.mqtt_err, main.mqtt_err)
main._clock_sane = orig_sane
main._last_mqtt_attempt = 0
main._mqtt_tick()
chk("时钟恢复后自动重连", main.mqtt_state == "connected" and len(FakeMQTT.instances) == 2)

# ---- 连接失败（如认证被拒）→ 状态回 disconnected，错误可查 ----
main._mqtt_disconnect()            # 先断开当前连接
FakeMQTT.connect_should_fail = True
main._last_mqtt_attempt = 0
main._mqtt_tick()
chk("连接失败 → disconnected", main.mqtt_state == "disconnected")
chk("mqtt_err 已记录", main.mqtt_err is not None and "refused" in main.mqtt_err, main.mqtt_err)
out = drain(["MQTT_STATUS"])
chk("MQTT_STATUS 含最近错误", any(l.startswith("MQTT_ERR ") for l in out), out)

# ---- 配置读回 ----
main.mqtt_cfg = None
main._wifi_load_cfg()
main._mqtt_load_cfg()
chk("重新读取配置恢复 mqtt", main.mqtt_cfg == {"host": "mqtt.example.com", "port": 8883, "user": "testuser", "password": "secret"})

# ---- MQTT_FORGET ----
main._last_mqtt_attempt = 0
main._mqtt_tick()                   # 重新连上，便于验证 forget 会断开
out = drain(["MQTT_FORGET"])
chk("MQTT_FORGET 响应", out == ["OK mqtt forgotten", "DONE"], out)
chk("forget 后 mqtt_cfg 清空", main.mqtt_cfg is None)
chk("forget 后 mqtt.json 为空", read_mqtt_file() in (None, {}) or "mqtt" not in (read_mqtt_file() or {}))
chk("forget 不影响 wifi.json", read_cfg_file() == {"sta": {"ssid": "MyWiFi", "password": "pass123"}} or read_cfg_file() is None)
main._mqtt_tick()
chk("无配置 → 状态 off", main.mqtt_state == "off")

# ---- 未知命令 ----
out = drain(["WIFI_BOGUS"])
chk("未知命令 ERR", out == ["ERR unknown command: WIFI_BOGUS"], out)

print("\n板端 WiFi+MQTT 逻辑:", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
