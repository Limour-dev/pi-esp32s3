# test_wifi_board.py —— 板端 WiFi 逻辑测试：在宿主 Python 上 mock BLE/network/硬件模块，
# 直接驱动 main.py 的 _drain_cmds 真实接收路径，验证 WiFi 命令
# （扫描/连接/断开/忘记/状态/热点重配）与 /wifi.json 持久化。
# 运行：python3 test/test_wifi_board.py
import os
import sys
import types
import time as _t
import json as _json
import tempfile

# 宿主没有 time.sleep_ms，补一个短桩（缩短连接等待/AP 启动等待）
_t.sleep_ms = lambda ms: _t.sleep(min(ms / 1000.0, 0.01))
_t.ticks_ms = lambda: int(_t.time() * 1000)
_t.ticks_diff = lambda a, b: a - b

# 让 import main 找到例程根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ---------------- mock：bluetooth / neopixel / machine / ubinascii / ujson / network ----------------
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
        pass

    def __setitem__(s, i, v):
        pass

    def write(s):
        pass


neopixel.NeoPixel = NP
sys.modules["neopixel"] = neopixel

machine = types.ModuleType("machine")
machine.Pin = lambda p: None
sys.modules["machine"] = machine

ubinascii = types.ModuleType("ubinascii")
ubinascii.b2a_base64 = lambda b: __import__("base64").b64encode(b) + b"\n"
ubinascii.a2b_base64 = lambda s: __import__("base64").b64decode(s)
sys.modules["ubinascii"] = ubinascii

ujson = types.ModuleType("ujson")
ujson.dumps = _json.dumps
ujson.loads = _json.loads
sys.modules["ujson"] = ujson


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
            else:  # AP_IF
                self._ifc = ("192.168.4.1", "255.255.255.0", "192.168.4.1", "0.0.0.0")
        return v

    def config(self, *args, **kw):
        if kw:
            self._cfg.update(kw)
            return None
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
            if what == "rssi":
                return -40
            if what == "stations":
                return ()          # AP 客户端列表
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

# ---- 把配置指到临时文件，缩短连接超时 ----
_tmpdir = tempfile.mkdtemp(prefix="wifi04_")
main.WIFI_CFG_FILE = os.path.join(_tmpdir, "wifi.json")
main.STA_CONNECT_TIMEOUT = 1     # sleep_ms 已打桩，1 秒超时 = 40 次空转
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


# ---- 认证门禁（WiFi 命令同样被门禁） ----
main.authed = False
chk("未认证 WIFI_SCAN 被门禁", drain(["WIFI_SCAN"]) == ["ERR auth required"])
main.authed = True

# ---- 扫描 ----
out = drain(["WIFI_SCAN"])
chk("扫描返回 3 项 + DONE", len(out) == 4 and out[-1] == "DONE", out)
chk("扫描行格式 N auth ch rssi b64", out[0] == "N 3 1 -40 " + b64("MyWiFi"))
chk("中文 SSID 走 base64 不破坏行协议", out[2] == "N 7 11 -55 " + b64("\u6d4b\u8bd5"))
chk("STA 扫描后恢复未激活", main.sta_if.active() is False)

# ---- 连接成功 → 保存配置 ----
out = drain(["WIFI_CONNECT %s %s" % (b64("MyWiFi"), b64("pass123"))])
chk("连接成功响应 WIFI connecting + WIFI OK ip + DONE",
    out == ["WIFI connecting MyWiFi", "WIFI OK 192.168.1.100", "DONE"], out)
chk("sta_ssid 已记录", main.sta_ssid == "MyWiFi")
chk("wifi.json 已保存 sta", read_cfg_file() == {"sta": {"ssid": "MyWiFi", "password": "pass123"}})

# ---- 状态（已连接） ----
main._ap_start()   # 让 AP 处于活动状态（essid 来自 config.py 默认）
main._last_led = None
out = drain(["WIFI_STATUS"])
chk("状态行 STA CONNECTED", out[0] == "STA CONNECTED %s 192.168.1.100 192.168.1.1 8.8.8.8" % b64("MyWiFi"), out[0])
chk("状态行 AP", out[1].startswith("AP %s 192.168.4.1 0" % b64("ESP32S3-AP")), out[1])
chk("状态行 SAVED + DONE", out[2] == "SAVED %s" % b64("MyWiFi") and out[3] == "DONE")

# ---- 连接失败：错误密码 ----
main.sta_if.disconnect()
main.sta_if._result = "wrong"
main.sta_ssid = None
out = drain(["WIFI_CONNECT %s %s" % (b64("MyWiFi"), b64("bad"))])
chk("错密码以 ERR 收尾（无 DONE）", out[-1] == "ERR wrong password", out[-1])
chk("错密码不覆盖已保存配置", main.saved_sta == {"ssid": "MyWiFi", "password": "pass123"})

# ---- 连接失败：找不到网络 ----
main.sta_if._result = "notfound"
out = drain(["WIFI_CONNECT %s %s" % (b64("NoSuchNet"), b64("x"))])
chk("找不到网络原因", out[-1] == "ERR network not found", out[-1])

# ---- 断开（保留配置） ----
main.sta_if._result = "ok"
main.saved_sta = {"ssid": "MyWiFi", "password": "pass123"}
main._wifi_save_cfg()
out = drain(["WIFI_DISCONNECT"])
chk("断开响应", out == ["OK wifi disconnected", "DONE"], out)
chk("断开后 sta.disconnect 被调用", main.sta_if._disconnect_calls >= 1)
chk("断开保留配置（文件仍在）", read_cfg_file() is not None)

# ---- 忘记配置 ----
out = drain(["WIFI_FORGET"])
chk("忘记响应", out == ["OK wifi forgotten", "DONE"], out)
chk("忘记后 saved_sta 清空", main.saved_sta is None)
chk("忘记后文件里没有 sta", "sta" not in (read_cfg_file() or {}))

# ---- 热点重配 ----
out = drain(["WIFI_AP %s %s" % (b64("ESP32S3-AP2"), b64("87654321"))])
chk("热点重配响应", out == ["OK ap configured", "DONE"], out)
chk("AP 立即重配 essid", main.ap_if._cfg.get("essid") == "ESP32S3-AP2")
chk("AP 密码已记录", main.ap_if._cfg.get("password") == "87654321")
d = read_cfg_file()
chk("wifi.json 保存 ap", d and d.get("ap") == {"ssid": "ESP32S3-AP2", "password": "87654321"}, d)

# ---- 配置读回 ----
main.saved_sta = None
main.ap_cfg = None
main._wifi_load_cfg()
chk("重新读取配置恢复 ap", main.ap_cfg == {"ssid": "ESP32S3-AP2", "password": "87654321"})
chk("重新读取配置时 saved_sta 为空", main.saved_sta is None)

# ---- 自动重连（按保存配置） ----
main.saved_sta = {"ssid": "MyWiFi", "password": "pass123"}
main.sta_if.disconnect()
main.sta_if._result = "ok"
main._wifi_auto_connect()
chk("自动重连成功", main.sta_if.isconnected() and main.sta_ssid == "MyWiFi")

# ---- 门禁再次确认 + 命令未知 ----
main.authed = True
out = drain(["WIFI_BOGUS"])
chk("未知命令 ERR", out == ["ERR unknown command: WIFI_BOGUS"], out)

print("\n板端 WiFi 逻辑:", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
