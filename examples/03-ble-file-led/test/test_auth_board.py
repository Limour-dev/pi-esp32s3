# test_auth_board.py —— 板端认证逻辑测试：在宿主 Python 上 mock BLE/硬件模块，
# 直接驱动 main.py 的 _drain_cmds 真实接收路径，验证密码认证门禁与防爆破断开。
# 运行：python3 test/test_auth_board.py
import os
import sys
import types
import time as _t

# 宿主没有 time.sleep_ms，补一个短桩（缩短 200ms 的断开前等待）
_t.sleep_ms = lambda ms: _t.sleep(min(ms / 1000.0, 0.05))

# 让 import main 找到例程根目录
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


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

import main  # noqa: E402

main.ble = FakeBle()
main.conn_id = 99
main.notified = []
main._notify = lambda t: main.notified.append(t)


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


# ---- 认证门禁 ----
chk("未认证 LIST 被门禁（ERR 无 DONE）", drain(["LIST"]) == ["ERR auth required"])
chk("未认证 READ 被门禁", drain(["READ x"]) == ["ERR auth required"])

# ---- 三次错误 → 自动断开 ----
chk("错密码 1", drain(["AUTH bad"]) == ["ERR auth failed (1/3)"])
chk("错密码 2", drain(["AUTH bad"]) == ["ERR auth failed (2/3)"])
chk("错密码 3 → 自动断开", drain(["AUTH bad"]) == ["ERR auth failed (3/3)"])

# ---- 正确密码解锁 ----
chk("对密码", drain(["AUTH 1234"]) == ["AUTH OK", "DONE"])
chk("认证后 LIST 正常", drain(["LIST"])[-1] == "DONE")
chk("重复 AUTH 幂等", drain(["AUTH 1234"]) == ["AUTH OK", "DONE"])

# ---- 新连接重置认证 ----
main.authed = False
main._irq(main.IRQ_CENTRAL_CONNECT, (1,))
chk("新连接重置认证", main.authed is False and main.auth_fails == 0)
chk("重连后 PING 被门禁", drain(["PING"]) == ["ERR auth required"])

print("\n板端认证:", "全部通过 ✅" if ok else "有失败 ❌")
sys.exit(0 if ok else 1)
