#!/usr/bin/env python3
"""按 EXPERIMENT_GUIDE.md 8.1 的可靠姿势上传代码到板子：不软复位绕开看门狗。"""
import sys, time
from mpremote.transport_serial import SerialTransport

PORT = "/dev/serial/by-id/usb-1a86_USB_Single_Serial_5CBC064671-if00"
FILES = ["config.py", "main.py"]   # 相对本脚本所在目录

t = SerialTransport(PORT, baudrate=115200, timeout=1)
t.serial.dtr = False
t.serial.rts = False                       # 释放复位线
for _ in range(30):
    t.serial.write(b"\x03"); time.sleep(0.05)   # Ctrl-C 打断看门狗进 REPL

t.enter_raw_repl(soft_reset=False)         # 不软复位

for name in FILES:
    with open(name, "rb") as f:
        data = f.read()
    t.fs_writefile(name, data)             # 自带分块 + paste 协议
    print("WROTE %s (%d bytes)" % (name, len(data)))

t.exit_raw_repl()
t.serial.write(b"\x04")                    # 软复位跑应用
print("done, reset.")
