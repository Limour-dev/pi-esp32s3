# ESP32-S3 MicroPython 环境搭建指导手册

> **本手册的使用方式（给小白）**：你什么都不用懂，只需要把本手册**完整复制**发给一个全新的 agent（并告诉它"请按这份手册指导我完成配置"）。agent 会一步步指导你操作，直到 MicroPython 环境可用。
>
> **已实测环境**：Windows 宿主机 + VMware Workstation 虚拟机 + Ubuntu Linux 客户机 + ESP32-S3 开发板（CH343 USB 转串口芯片）。

---

## 0. 硬件与目标一览

| 项目 | 说明 |
|------|------|
| 开发板 | ESP32-S3，QFN56 封装，内嵌 8MB Octal PSRAM（即 ESP32-S3R8） |
| Flash | 16MB |
| 串口芯片 | WCH CH343（VID:PID = `1a86:55d3`），出厂工作在 CDC-ACM 模式 |
| 串口节点 | Linux 下识别为 `/dev/ttyACM0`（注意：**不是** ttyUSB0） |
| 目标环境 | MicroPython（最新稳定版）+ esptool 烧录 + mpremote 交互 |

---

## 1. 虚拟机 USB 直通（最关键的第一步）

**物理设备插在宿主机上 ≠ 虚拟机看得见**，必须手动直通。

VMware 操作步骤：

1. 确认开发板 USB 已插入宿主机。
2. VMware 菜单：**虚拟机 → 可移动设备 → [CH343 串口设备名] → 连接（断开与主机的连接）**
   - 设备名可能显示为 `QinHeng Electronics USB Single Serial` 或类似名称。
3. ⚠️ **不要**用「虚拟串口映射物理串口」的方式接入：VMware 的串口映射只支持真正的物理 COM 口，对 USB 转串口设备无效。直接做 USB 直通才有效。

直通后在 Linux 客户机里验证：

```bash
lsusb
# 应看到：Bus 0xx Device 0xx: ID 1a86:55d3 QinHeng Electronics USB Single Serial
```

看到 `1a86:55d3` 即表示直通成功。

---

## 2. 确认串口设备节点

```bash
ls -l /dev/ttyACM* /dev/ttyUSB*
ls -l /dev/serial/by-id/
```

- 正常应出现 `/dev/ttyACM0`。
- CH343 在 CDC-ACM 模式下被内核 `cdc_acm` 驱动直接接管，**无需安装任何驱动**。

### ⚠️ 串口节点编号会变

每次 USB 重新枚举（拔插、复位、重新直通），Linux 分配的编号会递增：`ttyACM0` → `ttyACM1` → ……

**永远优先使用稳定符号链接**（名字不会变）：

```bash
ls /dev/serial/by-id/
# usb-1a86_USB_Single_Serial_5CBC064671-if00 -> ../../ttyACM0
```

agent 调试时**不要硬编码 `ttyACM0`**，要用 by-id 或 glob 匹配当前节点。

---

## 3. 权限配置（dialout 组）

串口节点属于 `dialout` 组，普通用户需要加入：

```bash
sudo usermod -a -G dialout $USER
```

- 改完组需要**重新登录**才生效（GUI 注销重登 / 重启 / `su - $USER`）。
- 临时生效：`newgrp dialout`（仅当前 shell）。
- 单条命令：`sg dialout -c '命令'`。
- ⚠️ agent 若在加组之前就已启动，不会自动获得新组——agent 操作串口时可统一用 `sg dialout -c '...'` 包裹，或重启 agent 会话。

验证：`id` 输出里应包含 `dialout`。

---

## 4. 安装工具

```bash
pip install esptool mpremote pyserial
# 若环境隔离，用：
python3 -m pip install esptool mpremote pyserial
```

验证：

```bash
python3 -m esptool version
python3 -m mpremote version
```

---

## 5. 检测芯片（确认链路畅通）

```bash
python3 -m esptool --port /dev/ttyACM0 chip_id
```

期望输出包含：

```
Chip type:  ESP32-S3 (QFN56) (revision v0.2)
Features:   Wi-Fi, BT 5 (LE), Dual Core + LP Core, 240MHz
            Embedded PSRAM 8MB (AP_3v3)
```

- 看到 `ESP32-S3` 和 `Embedded PSRAM 8MB` 即表示链路正常。
- `Embedded PSRAM 8MB` 是关键判断：说明这是 **ESP32-S3R8**，后续固件必须选 Octal-SPIRAM 变体。

可选：查 Flash 型号/容量：

```bash
python3 -m esptool --port /dev/ttyACM0 flash_id
```

---

## 6. 烧录 MicroPython 固件

### 6.1 选择正确固件变体（重要）

到 https://micropython.org/download/ESP32_GENERIC_S3/ 找最新稳定版，**必须选 `SPIRAM_OCT`（Octal-SPIRAM）变体**：

- 本板是内嵌 8MB Octal PSRAM 的 ESP32-S3R8。
- 选错变体（普通版或 `SPIRAM` 版）会导致 PSRAM 识别不到，只剩几百 KB 内存。

下载示例（版本号/日期以当时最新为准）：

```bash
mkdir -p ~/mpy-esp32s3 && cd ~/mpy-esp32s3
curl -sL -o fw.bin "https://micropython.org/resources/firmware/ESP32_GENERIC_S3-SPIRAM_OCT-<日期>-<版本>.bin"
```

### 6.2 擦除并烧录

```bash
cd ~/mpy-esp32s3
python3 -m esptool --port /dev/ttyACM0 --baud 460800 erase_flash
python3 -m esptool --port /dev/ttyACM0 --baud 460800 write-flash -z 0x0 fw.bin
```

- 固件写入地址固定为 `0x0`。
- 烧录结束应看到 `Hash of data verified.` 和 `Hard resetting via RTS pin...`。

---

## 7. 验证 MicroPython 环境

```bash
python3 -m mpremote connect /dev/ttyACM0 exec "
import os, gc, esp
print(os.uname())
print('Flash:', esp.flash_size())
b = bytearray(4*1024*1024)
print('4MB 大块内存分配成功，PSRAM 可用')
print('剩余内存:', gc.mem_free())
"
```

期望结果：

- `release='1.29.0'`（或当时最新版）
- `Flash: 16777216`（16MB）
- 能成功分配 4MB 大块内存（证明 8MB PSRAM 可用）
- 剩余内存约 8.3MB

看到以上输出即代表**环境配置全部完成**。

---

## 8. 排错速查

| 现象 | 排查 |
|------|------|
| `lsusb` 看不到 `1a86:55d3` | USB 未直通进虚拟机，回到第 1 节做「可移动设备 → 连接」 |
| 看到 `1a86` 但没有 /dev/ttyACM* | `dmesg` 查看枚举日志；确认内核 `cdc_acm` 已加载 |
| `Permission denied` | 未加入 dialout 组或未重新登录，见第 3 节 |
| esptool 连不上、无响应 | ① 端口被占（`fuser -v /dev/ttyACM*`）② 节点编号变了，用 by-id 重新定位 |
| 烧录后 PSRAM 只有几百 KB | 固件选错变体，必须用 `SPIRAM_OCT` |
| 串口编号一直递增 | 正常现象（重枚举所致），始终用 by-id 定位 |

---

## 9. 日常操作速查

```bash
# 定位当前节点（编号可能变，用这个）
ls -l /dev/serial/by-id/

# 打开交互式 REPL（Ctrl+] 退出）
python3 -m mpremote connect /dev/ttyACM0

# 运行一段代码
python3 -m mpremote connect /dev/ttyACM0 exec "print(1+1)"

# 上传文件到板子
python3 -m mpremote connect /dev/ttyACM0 cp main.py :

# 列出板子上的文件
python3 -m mpremote connect /dev/ttyACM0 ls

# 重新烧录固件
cd ~/mpy-esp32s3
python3 -m esptool --port /dev/ttyACM0 --baud 460800 write-flash -z 0x0 fw.bin
```

---

## 10. 本次实测记录（2026-08，供 agent 参考）

- 固件：MicroPython v1.29.0（2026-08-24），`ESP32_GENERIC_S3-SPIRAM_OCT` 变体
- 工具版本：esptool v5.3.1 / mpremote 1.29.0 / pyserial 3.5
- 芯片：ESP32-S3 QFN56 rev v0.2，8MB Octal PSRAM，16MB Flash，40MHz 晶振
- 设备序列号：`5CBC064671`；by-id 名：`usb-1a86_USB_Single_Serial_5CBC064671-if00`
- 固件下载地址：https://micropython.org/resources/firmware/ESP32_GENERIC_S3-SPIRAM_OCT-20260824-v1.29.0.bin
