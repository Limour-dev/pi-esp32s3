# main.py —— 例程 03：BLE 文件服务 + WS2812 LED 控制
#
# 功能：ESP32-S3 作为 BLE 外设（GATT 服务器），提供两个服务：
#   1. 文件服务：列出 / 目录文件、读取 / 写入 / 删除文件
#   2. LED 服务：网页直接写 3 字节 RGB 控制 WS2812 灯珠
# 网页客户端见 web/index.html（Web Bluetooth，需 HTTPS 才能用）。
#
# BLE 协议（ASCII 文本行，\n 结尾，经 CMD 特征写入；响应经 DATA 特征 notify）：
#   每条命令的响应都以 DONE 行结束（出错则 ERR 行结束，无 DONE）。
#   PING                 -> PONG <name> <version> ... DONE
#   LIST                 -> F <name> <size> | D <name> 每项一行 ... DONE
#   READ <name>          -> READ <name> <size> / B <base64> ... / DONE
#   SIZE <name>          -> SIZE <name> <size> ... DONE
#   DEL <name>           -> OK ... DONE
#   WRITE_BEGIN <name> <size>   -> OK begin ... DONE
#   WRITE_CHUNK <base64>         无响应（多次发送，累计到声明大小）
#   WRITE_END            -> OK ... DONE
#
# 状态灯（WS2812，GPIO48）：
#   暗绿 = 广播中待连接；蓝 = 已连接；用户设置颜色后保持用户色；
#   断开后恢复暗绿。

import gc
import os
import time
import ubinascii
import bluetooth
import neopixel
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
    CHUNK_SIZE = config.CHUNK_SIZE
except ImportError:
    DEVICE_NAME = "ESP32S3-FS"
    WS2812_PIN = 48
    WS2812_NUM = 1
    LED_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
    LED_CHAR_UUID = "0000fff1-0000-1000-8000-00805f9b34fb"
    FILE_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
    CMD_CHAR_UUID = "0000ffe1-0000-1000-8000-00805f9b34fb"
    DATA_CHAR_UUID = "0000ffe2-0000-1000-8000-00805f9b34fb"
    CHUNK_SIZE = 180

VERSION = "1.0"
MAX_WRITE_SIZE = 512 * 1024  # 网页写入文件的最大字节数，防 OOM

# ---------------- BLE 事件码 ----------------
# 本固件（v1.29.0 ESP32 变体）未导出 IRQ_* 常量，按 MicroPython 官方
# modbluetooth.h 的事件编号硬编码兜底；标准编号多年来未变。
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
led_dirty = False      # 标记需要应用颜色（IRQ 里只置位，主循环里写灯）


def set_color(r, g, b):
    for i in range(WS2812_NUM):
        np[i] = (r, g, b)
    np.write()


def apply_led():
    global led_dirty
    if not led_dirty:
        return
    led_dirty = False
    if led_user is not None:
        set_color(*led_user)
    elif connected:
        set_color(0, 0, 80)       # 已连接：蓝
    else:
        set_color(0, 40, 0)       # 广播中：暗绿


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

    # 注意：两个服务必须在同一次 gatts_register_services 里注册，
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
    global connected, conn_id, led_user, led_dirty
    if event == IRQ_CENTRAL_CONNECT:
        connected = True
        conn_id = data[0]
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

def _cmd_ping():
    _notify("PONG %s %s" % (DEVICE_NAME, VERSION))
    _notify("DONE")

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


def _handle_cmd(line):
    if not line:
        return
    op, _, rest = line.partition(" ")
    op = op.upper().strip()
    if op == "PING":
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
    global conn_id
    print("=" * 56)
    print("ESP32-S3 例程 03：BLE 文件服务 + WS2812 LED 控制")
    print("设备名: %s  |  版本: %s" % (DEVICE_NAME, VERSION))
    print("用浏览器打开 web/index.html（需 HTTPS）连接本设备")
    print("=" * 56)
    _init_ble()
    _start_advertising()
    set_color(0, 40, 0)     # 广播中：暗绿
    was_connected = False
    while True:
        _drain_cmds()
        apply_led()
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
