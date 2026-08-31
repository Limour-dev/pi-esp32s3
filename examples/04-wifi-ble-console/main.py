# main.py —— 例程 04：BLE 网页控制台 + WiFi 配置
#
# 功能：ESP32-S3 作为 BLE 外设（GATT 服务器），提供三个能力：
#   1. 文件服务：列出 / 读取 / 写入 / 删除板子 Flash 文件（同例程 03）
#   2. LED 服务：网页直接写 3 字节 RGB 控制 WS2812 灯珠（同例程 03）
#   3. WiFi 服务：扫描周围路由器、连接路由器（STA）、配置回退热点（AP）、查看状态
# 网页客户端见 web/index.html（Web Bluetooth，需 HTTPS 才能用）。
#
# WiFi 行为：
#   - 热点（AP）**永远开着**，作为回退配置入口；连不上路由器时热点仍可用。
#   - 路由器连接配置（SSID/密码）经 BLE 命令设置后保存在 /wifi.json，
#     上电自动按保存的配置连接，断线后每 STA_RETRY_INTERVAL 秒自动重连。
#   - 注意：本固件 MicroPython 无 lwIP NAT，热点**不转发**路由器的网络，
#     热点下的设备只能访问 ESP32 自身提供的服务。
#
# BLE 协议（ASCII 文本行，\n 结尾，经 CMD 特征写入；响应经 DATA 特征 notify）：
#   每条命令的响应都以 DONE 行结束（出错则 ERR 行结束，无 DONE）。
#   连接后必须先认证：除 AUTH 外的任何命令在通过认证前都回 ERR auth required。
#   AUTH <password>        -> AUTH OK ... DONE（错误：ERR auth failed ... 无 DONE）
#   PING                   -> PONG <name> <version> ... DONE
#   LIST / READ / SIZE / DEL / WRITE_BEGIN / WRITE_CHUNK / WRITE_END（文件服务，同例程 03）
#   WIFI_SCAN              -> N <auth> <channel> <rssi> <b64ssid> 每项一行 ... DONE
#   WIFI_CONNECT <b64ssid> <b64pwd> -> WIFI connecting <ssid>（可跟多条 C <秒> 进度）...
#                              -> WIFI OK <ip> ... DONE / ERR <原因>
#   WIFI_DISCONNECT        -> OK wifi disconnected ... DONE（仅断开，保留已保存配置）
#   WIFI_FORGET            -> OK wifi forgotten ... DONE（断开并删除已保存配置）
#   WIFI_STATUS            -> STA <state> <b64ssid> <ip> <gw> <dns>
#                              AP <b64ssid> <ip> <clients>
#                              SAVED <b64ssid>（未保存则为空行）... DONE
#   WIFI_AP <b64ssid> <b64pwd> -> OK ap configured ... DONE（改回退热点名/密码并保存）
#   SSID/密码一律 base64 传输，避免空格/非 ASCII 字符破坏行协议。
#
# 状态灯（WS2812，GPIO48）：
#   用户设置颜色后保持用户色；否则按优先级：
#   蓝 = BLE 已连接；橙 = 正在连接路由器；青 = 路由器已连接；暗绿 = 广播中/回退热点。
#
# 环境前提：本固件（v1.29.0 ESP32 变体）未导出 IRQ_* 常量，按官方编号硬编码兜底。

import gc
import os
import time
import ubinascii
import ujson
import bluetooth
import neopixel
import network
from machine import Pin

# ---------------- 配置（优先 config.py，缺失时用内置默认值） ----------------
try:
    import config

    DEVICE_NAME = config.DEVICE_NAME
    WS2812_PIN = config.WS2812_PIN
    WS2812_NUM = config.WS2812_NUM
    LED_SERVICE_UUID = config.LED_SERVICE_UUID
    LED_CHAR_UUID = config.LED_CHAR_UUID
    FILE_SERVICE_UUID = config.FILE_SERVICE_UUID
    CMD_CHAR_UUID = config.CMD_CHAR_UUID
    DATA_CHAR_UUID = config.DATA_CHAR_UUID
    BLE_PASSWORD = config.BLE_PASSWORD
    CHUNK_SIZE = config.CHUNK_SIZE
    AP_SSID = config.AP_SSID
    AP_PASSWORD = config.AP_PASSWORD
    AP_MAX_CLIENTS = config.AP_MAX_CLIENTS
    AP_CHANNEL = config.AP_CHANNEL
    STA_CONNECT_TIMEOUT = config.STA_CONNECT_TIMEOUT
    STA_RETRY_INTERVAL = config.STA_RETRY_INTERVAL
    WIFI_CFG_FILE = config.WIFI_CFG_FILE
except ImportError:
    DEVICE_NAME = "ESP32S3-WIFI"
    WS2812_PIN = 48
    WS2812_NUM = 1
    LED_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
    LED_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
    FILE_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
    CMD_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
    DATA_CHAR_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"
    BLE_PASSWORD = "1234"
    CHUNK_SIZE = 180
    AP_SSID = "ESP32S3-AP"
    AP_PASSWORD = "12345678"
    AP_MAX_CLIENTS = 4
    AP_CHANNEL = 1
    STA_CONNECT_TIMEOUT = 20
    STA_RETRY_INTERVAL = 30
    WIFI_CFG_FILE = "/wifi.json"

VERSION = "1.0"
MAX_WRITE_SIZE = 512 * 1024  # 网页写入文件的最大字节数，防 OOM
MAX_AUTH_FAILS = 3        # 密码连续错误次数上限，超过自动断开（防爆破）

# ---------------- BLE 事件码 ----------------
def _irq_const(name, fallback):
    try:
        return getattr(bluetooth.BLE, name)
    except AttributeError:
        return fallback


IRQ_CENTRAL_CONNECT = _irq_const("IRQ_CENTRAL_CONNECT", 1)
IRQ_CENTRAL_DISCONNECT = _irq_const("IRQ_CENTRAL_DISCONNECT", 2)
IRQ_GATTS_WRITE = _irq_const("IRQ_GATTS_WRITE", 3)
IRQ_GATTS_READ_REQUEST = _irq_const("IRQ_GATTS_READ_REQUEST", 4)

# ---------------- WS2812 状态灯 ----------------
np = neopixel.NeoPixel(Pin(WS2812_PIN), WS2812_NUM)
led_user = None        # 网页设置的灯珠颜色；None = 走状态色
led_dirty = False      # 标记需要应用颜色（主循环里写灯）
_last_led = None       # 上一次应用的 LED 状态串（主循环检测变化）


def set_color(r, g, b):
    for i in range(WS2812_NUM):
        np[i] = (r, g, b)
    np.write()


def _sta_connected():
    """STA 是否已连上路由器（无异常版本）。"""
    try:
        sta = _sta()
        return sta.active() and sta.isconnected()
    except Exception:
        return False


def _led_state():
    """当前应显示的 LED 状态串（用户色优先）。"""
    if led_user is not None:
        return "user"
    if connected:
        return "ble"
    if sta_connecting:
        return "wifi-connecting"
    if _sta_connected():
        return "wifi-up"
    return "adv"


def apply_led():
    global led_dirty
    if not led_dirty:
        return
    led_dirty = False
    s = _led_state()
    if s == "user":
        set_color(*led_user)
    elif s == "ble":
        set_color(0, 0, 80)        # BLE 已连接：蓝
    elif s == "wifi-connecting":
        set_color(255, 120, 0)     # 正在连接路由器：橙
    elif s == "wifi-up":
        set_color(0, 180, 180)     # 路由器已连接：青
    else:
        set_color(0, 40, 0)        # 广播中：暗绿


def _led_tick():
    """主循环每轮调用：检测 LED 状态变化，置脏标记。"""
    global _last_led, led_dirty
    cur = _led_state()
    if cur != _last_led:
        _last_led = cur
        led_dirty = True


# ---------------- WiFi 接口（STA 连路由器 / AP 回退热点） ----------------
sta_if = None
ap_if = None
saved_sta = None         # /wifi.json 里保存的路由器配置 {"ssid","password"}；None=未保存
ap_cfg = None            # /wifi.json 里保存的热点配置 {"ssid","password"}；None=用 config.py 默认
sta_ssid = None          # 当前已连接路由器的 SSID（字符串）
sta_connecting = False   # 正在连接路由器（LED 橙色）
_last_sta_attempt = 0    # 上一次自动重连时刻（ticks_ms）


def _sta():
    global sta_if
    if sta_if is None:
        sta_if = network.WLAN(network.STA_IF)
    return sta_if


def _ap():
    global ap_if
    if ap_if is None:
        ap_if = network.WLAN(network.AP_IF)
    return ap_if


def _wifi_load_cfg():
    """开机读取 /wifi.json，恢复路由器与热点配置。"""
    global saved_sta, ap_cfg
    saved_sta = None
    ap_cfg = None
    try:
        with open(WIFI_CFG_FILE) as f:
            d = ujson.loads(f.read())
    except OSError:
        return                     # 没有配置文件：用 config.py 默认值
    except ValueError as e:
        print("wifi.json 解析失败（忽略）:", e)
        return
    sta = d.get("sta") or {}
    if sta.get("ssid"):
        saved_sta = {"ssid": str(sta["ssid"]), "password": str(sta.get("password", ""))}
    ap = d.get("ap") or {}
    if ap.get("ssid"):
        ap_cfg = {"ssid": str(ap["ssid"]), "password": str(ap.get("password", ""))}


def _wifi_save_cfg():
    """把当前保存的路由器/热点配置写回 /wifi.json。"""
    d = {}
    if saved_sta:
        d["sta"] = saved_sta
    if ap_cfg:
        d["ap"] = ap_cfg
    try:
        with open(WIFI_CFG_FILE, "w") as f:
            f.write(ujson.dumps(d))
    except OSError as e:
        print("wifi.json 写入失败:", e)


def _ap_start():
    """启动/重配回退热点（幂等）。STA 连上路由器后 AP 信道自动跟随。"""
    ap = _ap()
    ssid = ap_cfg["ssid"] if ap_cfg else AP_SSID
    password = (ap_cfg["password"] if ap_cfg else AP_PASSWORD) or ""
    if password and len(password) < 8:
        print("警告: 热点密码不足 8 位，无法启用 WPA2，热点将以开放网络运行！")
        password = ""
    try:
        ap.config(
            essid=ssid,
            authmode=network.AUTH_WPA_WPA2_PSK if password else network.AUTH_OPEN,
            password=password,
            max_clients=AP_MAX_CLIENTS,
            channel=AP_CHANNEL,
        )
        if not ap.active():
            ap.active(True)
        # 等接口真正起来（active 返回 True 可能略早）
        for _ in range(20):
            if ap.active():
                break
            time.sleep_ms(100)
        print("回退热点已开启: %s (%s)  IP %s" % (ssid, password or "开放", ap.ifconfig()[0]))
    except Exception as e:
        print("热点启动失败:", e)


def _wifi_scan():
    """扫描周围路由器。返回 [(ssid_bytes, bssid, channel, rssi, authmode, hidden), ...]"""
    sta = _sta()
    was_active = sta.active()
    if not was_active:
        sta.active(True)
        time.sleep_ms(500)         # 等 STA 接口起来再扫
    try:
        return sta.scan()
    finally:
        if not was_active:
            sta.active(False)


def _sta_connect(ssid, pwd, progress=None):
    """连接路由器（阻塞，最长 STA_CONNECT_TIMEOUT 秒）。
    返回 (True, ip) 成功 / (False, 原因字符串) 失败。
    progress(秒) 回调用于网页显示连接进度。"""
    global sta_ssid, sta_connecting
    sta_connecting = True
    try:
        sta = _sta()
        if not sta.active():
            sta.active(True)
        sta.connect(ssid, pwd)
        deadline = time.ticks_ms() + STA_CONNECT_TIMEOUT * 1000
        i = 0
        while time.ticks_diff(deadline, time.ticks_ms()) > 0:
            time.sleep_ms(500)
            if sta.isconnected():
                sta_ssid = ssid
                ip = sta.ifconfig()[0]
                print("路由器已连接: %s -> %s" % (ssid, ip))
                return True, ip
            i += 1
            if progress and i % 2 == 0:
                progress(i * 500 // 1000)
        # 超时：从状态码判断原因
        reason = "timeout"
        try:
            st = sta.status()
            if st == network.STAT_WRONG_PASSWORD:
                reason = "wrong password"
            elif st in (network.STAT_NO_AP_FOUND,
                        network.STAT_NO_AP_FOUND_IN_AUTHMODE_THRESHOLD,
                        network.STAT_NO_AP_FOUND_IN_RSSI_THRESHOLD,
                        network.STAT_NO_AP_FOUND_W_COMPATIBLE_SECURITY):
                reason = "network not found"
            elif st in (network.STAT_CONNECT_FAIL, network.STAT_ASSOC_FAIL):
                reason = "connect fail"
            elif st == network.STAT_HANDSHAKE_TIMEOUT:
                reason = "handshake timeout"
        except Exception:
            pass
        try:
            sta.disconnect()
        except Exception:
            pass
        sta_ssid = None
        print("路由器连接失败: %s (%s)" % (ssid, reason))
        return False, reason
    finally:
        sta_connecting = False


def _wifi_auto_connect():
    """按保存的配置自动连接路由器（开机与主循环重试共用）。"""
    global _last_sta_attempt
    if saved_sta is None:
        return
    if _sta_connected():
        return
    print("自动连接路由器: %s ..." % saved_sta["ssid"])
    _sta_connect(saved_sta["ssid"], saved_sta["password"])
    _last_sta_attempt = time.ticks_ms()


def _wifi_status_lines():
    """生成 WIFI_STATUS 响应行（不含 DONE）。"""
    lines = []
    sta = _sta()
    if sta.active() and sta.isconnected():
        ip, mask, gw, dns = sta.ifconfig()
        lines.append("STA CONNECTED %s %s %s %s" % (
            _b64s((sta_ssid or "").encode("utf-8")), ip, gw, dns))
    elif sta.active():
        state = "CONNECTING" if sta_connecting else "DISCONNECTED"
        lines.append("STA %s %s %s %s %s" % (state, "", "0.0.0.0", "0.0.0.0", "0.0.0.0"))
    else:
        lines.append("STA OFF  0.0.0.0 0.0.0.0 0.0.0.0")
    try:
        ap = _ap()
        ap_ssid = ap.config("essid") if ap.active() else ""
        ap_ip = ap.ifconfig()[0] if ap.active() else "0.0.0.0"
        clients = len(ap.status("stations") or ())
        lines.append("AP %s %s %d" % (_b64s(str(ap_ssid).encode("utf-8")), ap_ip, clients))
    except Exception as e:
        lines.append("AP  0.0.0.0 0")
    lines.append("SAVED %s" % (_b64s(saved_sta["ssid"].encode("utf-8")) if saved_sta else ""))
    return lines


def _b64s(raw):
    return ubinascii.b2a_base64(raw).strip().decode("ascii")


# ---------------- BLE 初始化 ----------------
ble = None
led_handle = None
cmd_handle = None
data_handle = None
connected = False
conn_id = None         # 当前连接句柄
pending = []          # IRQ 收集到的 CMD 原始字节（list 避免与主循环竞争）
cmd_buf = bytearray() # 命令缓冲，按 \n 切分成一行行命令
w_name = None         # WRITE_BEGIN 状态
w_size = 0
w_buf = None
authed = False        # 是否已通过密码认证（每次连接都要重新认证）
auth_fails = 0        # 本次连接连续输错密码次数


def _init_ble():
    global ble, led_handle, cmd_handle, data_handle
    ble = bluetooth.BLE()
    ble.active(True)
    ble.config(mtu=517)          # 允许大 MTU（Chrome/Android 会协商到 512）
    ble.irq(_irq)

    led_svc = bluetooth.UUID(LED_SERVICE_UUID)
    led_char = bluetooth.UUID(LED_CHAR_UUID)
    file_svc = bluetooth.UUID(FILE_SERVICE_UUID)
    cmd_char = bluetooth.UUID(CMD_CHAR_UUID)
    data_char = bluetooth.UUID(DATA_CHAR_UUID)

    # 注意：所有服务必须在同一次 gatts_register_services 里注册，
    # 分两次调用会导致句柄冲突（本固件每次调用都从 16 重新分配）。
    ((led_handle,), (cmd_handle, data_handle)) = ble.gatts_register_services((
        (led_svc, ((led_char, bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE),)),
        (file_svc, (
            (cmd_char, bluetooth.FLAG_WRITE | bluetooth.FLAG_WRITE_NO_RESPONSE),
            (data_char, bluetooth.FLAG_READ | bluetooth.FLAG_NOTIFY),
        )),
    ))
    # CMD 允许一次写入较长内容（默认缓冲只有 20 字节）
    ble.gatts_set_buffer(cmd_handle, 1024, False)
    ble.gatts_write(data_handle, b"")
    print("GATT 服务注册完成: led=%s cmd=%s data=%s" % (led_handle, cmd_handle, data_handle))


def _adv_128(uuid_str):
    """128 位 UUID 转广播数据（小端字节序）。"""
    raw = bytes.fromhex(uuid_str.replace("-", ""))
    return bytes((17, 0x07)) + bytes(reversed(raw))


def _start_advertising():
    name = DEVICE_NAME.encode("utf-8")
    adv = b"\x02\x01\x06" + bytes((len(name) + 1, 0x09)) + name
    resp = _adv_128(FILE_SERVICE_UUID)          # 扫描响应里带文件服务 UUID
    ble.gap_advertise(100000, adv_data=adv, resp_data=resp)
    print("正在广播: %s" % DEVICE_NAME)


# ---------------- IRQ 处理（只做轻量工作） ----------------
def _irq(event, data):
    global connected, conn_id, led_user, led_dirty, authed, auth_fails
    if event == IRQ_CENTRAL_CONNECT:
        connected = True
        conn_id = data[0]
        authed = False          # 新连接必须重新输密码
        auth_fails = 0
        print("BLE 已连接 conn=%s" % (data[0],))
    elif event == IRQ_CENTRAL_DISCONNECT:
        connected = False
        conn_id = None
        led_user = None
        led_dirty = True
        print("BLE 已断开")
    elif event == IRQ_GATTS_WRITE:
        vh = data[1]
        if vh == led_handle:
            if not authed:
                return          # 未认证不响应 LED 写
            val = ble.gatts_read(led_handle)
            if len(val) >= 3:
                led_user = (val[0], val[1], val[2])
                led_dirty = True
                print("LED 设置为 rgb(%d,%d,%d)" % led_user)
        elif vh == cmd_handle:
            pending.append(bytes(ble.gatts_read(cmd_handle)))
    elif event == IRQ_GATTS_READ_REQUEST:
        pass  # 默认返回缓冲区内容


# ---------------- 命令处理 ----------------
def _notify(text):
    """把一行响应通过 DATA 特征 notify 出去。"""
    if not connected or conn_id is None:
        return
    try:
        line = (text + "\n").encode("utf-8")
        if len(line) > CHUNK_SIZE + 1:
            print("警告: 响应行超长被截断风险: %r" % text[:60])
        ble.gatts_notify(conn_id, data_handle, line)
    except Exception as e:
        print("notify 失败:", e)


def _const_time_eq(a, b):
    """常量时间字符串比较，避免长度/内容差异造成时序侧信道。"""
    if len(a) != len(b):
        return False
    res = 0
    for x, y in zip(a, b):
        res |= ord(x) ^ ord(y)
    return res == 0


def _cmd_auth(pwd):
    global authed, auth_fails
    if authed:
        _notify("AUTH OK")
        _notify("DONE")
        return
    if _const_time_eq(pwd, BLE_PASSWORD):
        authed = True
        auth_fails = 0
        _notify("AUTH OK")
        _notify("DONE")
        print("密码验证通过")
    else:
        auth_fails += 1
        _notify("ERR auth failed (%d/%d)" % (auth_fails, MAX_AUTH_FAILS))
        print("密码错误 %d/%d" % (auth_fails, MAX_AUTH_FAILS))
        if auth_fails >= MAX_AUTH_FAILS:
            time.sleep_ms(200)      # 等错误通知发出去再断开
            try:
                ble.gap_disconnect(conn_id)
            except Exception as e:
                print("断开失败:", e)


def _cmd_ping():
    _notify("PONG %s %s" % (DEVICE_NAME, VERSION))
    _notify("DONE")


# ---- 文件服务（同例程 03） ----
def _cmd_list():
    try:
        names = sorted(os.listdir("/"))
    except OSError as e:
        _notify("ERR list failed: %s" % e)
        return
    for name in names:
        try:
            st = os.stat("/" + name)
        except OSError:
            continue
        if st[0] & 0x4000:          # 目录
            _notify("D %s" % name)
        else:
            _notify("F %s %d" % (name, st[6]))
    _notify("DONE")


def _cmd_read(name):
    path = "/" + name
    try:
        st = os.stat(path)
    except OSError:
        _notify("ERR 404 %s" % name)
        return
    if st[0] & 0x4000:
        _notify("ERR 403 %s is a directory" % name)
        return
    size = st[6]
    raw_per_chunk = (CHUNK_SIZE - 2) // 4 * 3   # "B " 前缀 + base64 行
    _notify("READ %s %d" % (name, size))
    with open(path, "rb") as f:
        while True:
            data = f.read(raw_per_chunk)
            if not data:
                break
            b64 = ubinascii.b2a_base64(data).strip().decode("ascii")
            _notify("B " + b64)
            time.sleep_ms(2)        # 给 BLE 栈喘息，避免通知洪泛
    _notify("DONE")


def _cmd_size(name):
    try:
        st = os.stat("/" + name)
        _notify("SIZE %s %d" % (name, st[6]))
        _notify("DONE")
    except OSError:
        _notify("ERR 404 %s" % name)


def _cmd_del(name):
    path = "/" + name
    try:
        os.remove(path)
        _notify("OK deleted %s" % name)
        _notify("DONE")
    except OSError:
        try:
            os.rmdir(path)
            _notify("OK rmdir %s" % name)
            _notify("DONE")
        except OSError as e:
            _notify("ERR %s" % e)


def _cmd_write_begin(name, size_s):
    global w_name, w_size, w_buf
    try:
        w_size = int(size_s)
    except ValueError:
        w_size = 0
    if w_size > MAX_WRITE_SIZE:
        _notify("ERR size too large (max %d)" % MAX_WRITE_SIZE)
        _notify("DONE")
        w_name = None
        w_buf = None
        return
    # 名字清洗：去路径分隔符与 ".."，防写坏目录
    clean = name.replace("/", "_").replace("\\", "_").replace("..", "_").strip()
    w_name = clean or "unnamed"
    w_buf = bytearray()
    _notify("OK begin %s %d" % (w_name, w_size))
    _notify("DONE")


def _cmd_write_chunk(b64):
    global w_buf
    if w_buf is None:
        return
    try:
        raw = ubinascii.a2b_base64(b64)
    except Exception:
        return
    if len(w_buf) + len(raw) > w_size:
        return                          # 超出声明大小，丢弃多余部分
    w_buf += raw


def _cmd_write_end():
    global w_name, w_size, w_buf
    if w_buf is None:
        _notify("ERR no write in progress")
        _notify("DONE")
        return
    try:
        with open("/" + w_name, "wb") as f:
            f.write(w_buf)
        _notify("OK wrote %s %d bytes" % (w_name, len(w_buf)))
        print("已写入文件: %s (%d B)" % (w_name, len(w_buf)))
    except OSError as e:
        _notify("ERR %s" % e)
    _notify("DONE")
    w_name = None
    w_size = 0
    w_buf = None


# ---- WiFi 服务 ----
def _cmd_wifi_scan():
    try:
        res = _wifi_scan()
    except Exception as e:
        _notify("ERR scan failed: %s" % e)
        return
    for entry in res:
        ssid, _bssid, channel, rssi, auth, _hidden = entry
        _notify("N %d %d %d %s" % (auth, channel, rssi, _b64s(ssid)))
    _notify("DONE")


def _parse_b64_pair(rest):
    """从 "<b64ssid> <b64pwd>" 拆出 (ssid, pwd) 字符串。"""
    parts = rest.split(" ", 1)
    if len(parts) < 2:
        raise ValueError("usage: <b64ssid> <b64pwd>")
    ssid = ubinascii.a2b_base64(parts[0].strip()).decode("utf-8", "ignore")
    pwd = ubinascii.a2b_base64(parts[1].strip()).decode("utf-8", "ignore")
    return ssid, pwd


def _cmd_wifi_connect(rest):
    global saved_sta
    try:
        ssid, pwd = _parse_b64_pair(rest)
    except Exception as e:
        _notify("ERR bad args: %s" % e)
        return
    if not ssid:
        _notify("ERR empty ssid")
        return
    _notify("WIFI connecting %s" % ssid)
    ok, info = _sta_connect(ssid, pwd, progress=lambda sec: _notify("C %d" % sec))
    if ok:
        saved_sta = {"ssid": ssid, "password": pwd}
        _wifi_save_cfg()
        print("已保存路由器配置: %s" % ssid)
        _notify("WIFI OK %s" % info)     # info = IP
        _notify("DONE")
    else:
        _notify("ERR %s" % info)


def _cmd_wifi_disconnect():
    """仅断开连接，保留保存的配置（开机后还会自动重连）。"""
    global sta_ssid
    sta = _sta()
    try:
        if sta.active():
            sta.disconnect()
    except Exception as e:
        _notify("ERR %s" % e)
        _notify("DONE")
        return
    sta_ssid = None
    print("已断开路由器连接（配置保留）")
    _notify("OK wifi disconnected")
    _notify("DONE")


def _cmd_wifi_forget():
    """断开并删除保存的配置。"""
    global saved_sta, sta_ssid
    sta = _sta()
    try:
        if sta.active():
            sta.disconnect()
    except Exception:
        pass
    sta_ssid = None
    saved_sta = None
    _wifi_save_cfg()
    print("已删除路由器配置")
    _notify("OK wifi forgotten")
    _notify("DONE")


def _cmd_wifi_status():
    for line in _wifi_status_lines():
        _notify(line)
    _notify("DONE")


def _cmd_wifi_ap(rest):
    global ap_cfg
    try:
        ssid, pwd = _parse_b64_pair(rest)
    except Exception as e:
        _notify("ERR bad args: %s" % e)
        return
    if not ssid:
        _notify("ERR empty ssid")
        return
    ap_cfg = {"ssid": ssid, "password": pwd}
    _ap_start()                 # 立即生效
    _wifi_save_cfg()
    print("回退热点已重配: %s" % ssid)
    _notify("OK ap configured")
    _notify("DONE")


def _handle_cmd(line):
    if not line:
        return
    op, _, rest = line.partition(" ")
    op = op.upper().strip()
    # 认证门禁：除 AUTH 外所有命令必须先通过密码认证
    if op != "AUTH" and not authed:
        _notify("ERR auth required")   # ERR 行结束即无 DONE（与协议约定一致）
        return
    if op == "AUTH":
        _cmd_auth(rest.strip())
    elif op == "PING":
        _cmd_ping()
    elif op == "LIST":
        _cmd_list()
    elif op == "READ":
        _cmd_read(rest.strip())
    elif op == "SIZE":
        _cmd_size(rest.strip())
    elif op == "DEL":
        _cmd_del(rest.strip())
    elif op == "WRITE_BEGIN":
        name, _, size_s = rest.rpartition(" ")
        _cmd_write_begin(name.strip(), size_s.strip())
    elif op == "WRITE_CHUNK":
        _cmd_write_chunk(rest.strip())
    elif op == "WRITE_END":
        _cmd_write_end()
    elif op == "WIFI_SCAN":
        _cmd_wifi_scan()
    elif op == "WIFI_CONNECT":
        _cmd_wifi_connect(rest)
    elif op == "WIFI_DISCONNECT":
        _cmd_wifi_disconnect()
    elif op == "WIFI_FORGET":
        _cmd_wifi_forget()
    elif op == "WIFI_STATUS":
        _cmd_wifi_status()
    elif op == "WIFI_AP":
        _cmd_wifi_ap(rest)
    else:
        _notify("ERR unknown command: %s" % op)


def _drain_cmds():
    """把 pending 里的字节并入 cmd_buf，逐行执行命令。"""
    global cmd_buf
    if pending:
        for chunk in pending:
            cmd_buf += chunk
        pending.clear()
    while True:
        nl = cmd_buf.find(b"\n")
        if nl < 0:
            if len(cmd_buf) > 4096:      # 防呆：无换行且过长则清空
                cmd_buf = bytearray()   # 本固件 bytearray 无 clear()，重建空对象
            break
        line = bytes(cmd_buf[:nl])
        cmd_buf = cmd_buf[nl + 1:]   # bytearray 不支持 del 切片，用重切片移除已处理行
        try:
            _handle_cmd(line.decode("utf-8", "ignore").strip())
        except Exception as e:
            print("命令处理异常:", repr(line), e)
            _notify("ERR internal: %s" % e)


# ---------------- 主流程 ----------------
def main():
    global conn_id, _last_sta_attempt
    print("=" * 56)
    print("ESP32-S3 例程 04：BLE 网页控制台 + WiFi 配置（密码保护已开启）")
    print("设备名: %s  |  版本: %s  |  密码: %s" % (DEVICE_NAME, VERSION, BLE_PASSWORD))
    print("用浏览器打开 web/index.html（需 HTTPS）连接本设备，连接后先输密码")
    print("=" * 56)

    # 1) 回退热点先起来（永远在线，作为配置入口）
    _wifi_load_cfg()
    _ap_start()

    # 2) 按保存的配置自动连路由器（有界等待，连不上不阻塞太久）
    if saved_sta is not None:
        print("检测到已保存路由器配置: %s" % saved_sta["ssid"])
        _last_sta_attempt = time.ticks_ms()
        _wifi_auto_connect()

    # 3) BLE 服务
    _init_ble()
    _start_advertising()
    _led_tick()                     # 初始化 _last_led

    was_connected = False
    while True:
        _drain_cmds()
        _led_tick()
        apply_led()
        # 已保存配置且未连上 → 定期自动重连（路由器重启/断网自愈）
        if (saved_sta is not None and not _sta_connected() and not sta_connecting
                and time.ticks_diff(time.ticks_ms(), _last_sta_attempt) > STA_RETRY_INTERVAL * 1000):
            _wifi_auto_connect()
        if connected and not was_connected:
            # 刚连上：停止广播，避免被重复发现
            was_connected = True
            try:
                ble.gap_advertise(None)
            except Exception as e:
                print("停止广播失败:", e)
        elif not connected and was_connected:
            # 刚断开：恢复广播
            was_connected = False
            _start_advertising()
        gc.collect()
        time.sleep_ms(10)


if __name__ == "__main__":
    main()
