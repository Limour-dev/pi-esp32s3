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

## 离开 / 断电前检查（拔线备忘）

**直接拔掉 USB 即可，无强制步骤**，但建议按下面顺序快速确认，避免端口被占或残留进程：

```bash
# 1. 确认无进程占用串口（无输出即安全，可拔）
fuser -v /dev/ttyACM0

# 2. 确认无后台串口监听脚本残留（调试时用过的 pyserial 脚本等）
pgrep -af "python3 _listen[.]py"

# 3. 确认 git 工作区干净（可选）
git status
```

拔线后须知：

- 代码已存在板子 Flash 里（`boot.py` / `config.py` / `main.py`），**上电自动运行 `main.py`**；
  若不想自启，插回后执行 `python3 -m mpremote connect <PORT> mv main.py <其他名字>` 改名即可。
- 重新插入后 **VMware USB 直通要重连**（虚拟机 → 可移动设备 → 连接），见 SETUP_GUIDE 第 1 节。
- 串口节点号会变（`ttyACM0` → `ttyACM1`…），始终用 by-id 定位：`ls -l /dev/serial/by-id/`。

## 目录结构

```
pi-esp32s3/
├── README.md                  # 项目说明 + 快速开始
├── SETUP_GUIDE.md             # 环境搭建指导手册（供新 agent / 小白使用）
└── examples/
    └── 01-led-blink/          # 例程 1：点灯（测试所有 LED + WS2812）
        ├── AGENT_GUIDE.md     # 给 agent 的指导
        ├── config.py          # LED 引脚配置（探测后填写）
        ├── scan_leds.py       # LED 引脚自动探测脚本
        └── main.py            # 点灯主程序
    └── 02-ap-file-server/     # 例程 2：WiFi 热点 + 文件浏览服务器 + LED 控制
        ├── AGENT_GUIDE.md     # 给 agent 的指导
        ├── config.py          # 热点名/密码/端口/WS2812 引脚配置
        └── main.py            # AP + HTTP 文件服务器 + /setled LED 控制
    └── 03-ble-file-led/       # 例程 3：BLE 网页控制台（文件 + LED）
    └── 04-wifi-ble-console/   # 例程 4：BLE 网页控制台 + WiFi 配置（含回退热点 AP）
    └── 05-mqtt-ws2812/        # 例程 5：BLE 网页控制台 + WiFi + MQTT（TLS 8883 控制 WS2812，无 AP）
```
