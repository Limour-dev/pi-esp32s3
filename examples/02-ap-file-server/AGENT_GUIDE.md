# 例程 02：WiFi 热点 + 文件浏览服务器 + LED 控制 —— Agent 指导手册

> 本手册写给「agent」。你的任务是引导小白运行本目录例程：
> 板子开 WiFi 热点，手机连上后浏览器访问 http://192.168.4.1 看文件列表、
> 点开文件内容、在页面底部控制 WS2812 灯珠颜色。
> 前置条件：设备已按仓库根目录 `SETUP_GUIDE.md` 配好 MicroPython 环境，
> 且例程 01 已确认 WS2812 灯珠接 GPIO48。

## 1. 文件结构

| 文件 | 作用 |
|------|------|
| `config.py` | 热点名/密码/端口/WS2812 引脚配置（小白可自行改） |
| `main.py` | 开启 AP + HTTP 文件服务器 + `/setled` LED 控制接口 |

## 2. 先确定串口（编号会变，用 by-id）

```bash
ls -l /dev/serial/by-id/
```

后面命令里的 `<PORT>` 用 by-id 完整路径替换。

## 3. 执行流程

### 第 1 步：上传并复位

```bash
python3 -m mpremote connect <PORT> cp config.py :
python3 -m mpremote connect <PORT> cp main.py :
```

`main.py` 是开机自启文件名，上传后复位即自动运行：
```bash
python3 -m mpremote connect <PORT> reset
```

### 第 2 步：确认启动日志

复位后串口应打印：
```
WiFi 热点已开启: ESP-AP (密码: 12345678)
HTTP 服务器已启动: http://192.168.4.1:80/
```

### 第 3 步：引导用户手机测试

1. 手机 WiFi 连接热点 `ESP-AP`，密码 `12345678`（应弹出密码框）。
2. 浏览器打开 `http://192.168.4.1`。
3. 验证三点：
   - 看到文件列表（boot.py / config.py / main.py 带大小）；
   - 点文件名能查看内容（如 boot.py）；
   - 滚动到页面底部「LED 控制」面板：取色器/预设色/熄灭，灯珠即时变色并保持。

## 4. 排错速查

| 现象 | 排查 |
|------|------|
| 手机连热点不弹密码框 | `start_ap()` 里漏了 `authmode=`，必须显式 `network.AUTH_WPA_WPA2_PSK`（见下方坑 1） |
| 点文件报 `'module' object has no attribute 'path'` | 本固件无 `os.path`，扩展名解析用 `mime_of()` 里的手写 `rfind('.')`，别改回 `os.path.splitext`（见坑 2） |
| 手机搜不到热点 | 板子未上电 / 距离太远 / 密码少于 8 位被降级为开放网络 |
| 改热点名/密码/端口 | 编辑 `config.py` 后重新上传 + 复位 |
| REPL 连不上（mpremote exec 报 could not enter raw repl） | `main.py` 的 accept 循环占着主线程，属正常；验证用 pyserial 脚本或先 Ctrl-C |
| 想恢复例程 01 点灯 | 重新上传 `examples/01-led-blink/` 的 `main.py` |

## 5. 已踩过的坑（实现时别重犯）

1. **AP 密码不生效**：本固件 `ap.config(password=...)` 不会自动改加密方式，
   必须同时显式 `authmode=network.AUTH_WPA_WPA2_PSK`（密码为空则 `AUTH_OPEN`）。
   验证：`ap.config('authmode')`，0=开放，4=WPA2/WPA。
2. **没有 `os.path`**：`hasattr(os, 'path')` 为 False、`import os.path` 报 ImportError，
   取扩展名用手写 `name.rfind('.')`。
3. **无限循环时 REPL 不可用**：服务器 accept 循环阻塞主线程，
   `mpremote exec/ls` 进不了 raw REPL；需要诊断时用 pyserial 脚本：
   复位（esptool 风格 DTR/RTS 序列）→ Ctrl-C 打断 → 发命令 → Ctrl-D 软复位恢复运行。
4. **后台串口监听**：pyserial 非独占打开时与 mpremote 并发会互相干扰，操作前先停监听进程。
