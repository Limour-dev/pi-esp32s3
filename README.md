# pi-esp32s3

ESP32-S3 开发板的 MicroPython 开发项目。

## 硬件信息

| 项目 | 说明 |
|------|------|
| 芯片 | ESP32-S3（QFN56，revision v0.2） |
| PSRAM | 8MB Octal PSRAM（内嵌，即 ESP32-S3R8） |
| Flash | 16MB |
| 串口芯片 | WCH CH343（VID:PID `1a86:55d3`，CDC-ACM 模式） |
| 串口节点 | `/dev/ttyACM0`（by-id：`usb-1a86_USB_Single_Serial_5CBC064671-if00`） |

## 环境状态

- ✅ MicroPython v1.29.0 已烧录（`ESP32_GENERIC_S3-SPIRAM_OCT` 变体，适配 8MB Octal PSRAM）
- ✅ esptool / mpremote / pyserial 已安装
- ✅ 8MB PSRAM 实测可用，Flash 16MB
- 固件文件：`~/mpy-esp32s3/fw.bin`

## 环境搭建 / 排错

全新机器或全新 agent 接手时，请阅读 **[SETUP_GUIDE.md](SETUP_GUIDE.md)**（从虚拟机 USB 直通到 MicroPython 验证的完整步骤，含排错速查）。小白可直接把该手册发给新 agent，让其按手册指导完成全部配置。

## 快速开始

```bash
# 定位当前串口节点（编号可能变化）
ls -l /dev/serial/by-id/

# 打开交互式 REPL（Ctrl+] 退出）
python3 -m mpremote connect /dev/ttyACM0

# 运行代码
python3 -m mpremote connect /dev/ttyACM0 exec "print('hello esp32s3')"

# 上传文件到板子
python3 -m mpremote connect /dev/ttyACM0 cp main.py :

# 重新烧录固件
cd ~/mpy-esp32s3
python3 -m esptool --port /dev/ttyACM0 --baud 460800 write-flash -z 0x0 fw.bin
```

## 目录结构

```
pi-esp32s3/
├── README.md          # 本文件（项目说明 + 快速开始）
├── SETUP_GUIDE.md     # 环境搭建指导手册（供新 agent / 小白使用）
└── (待添加) main.py   # MicroPython 主程序
```
