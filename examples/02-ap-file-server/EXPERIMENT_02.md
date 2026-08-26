# 例程 02：WiFi 热点 + 文件浏览服务器 + LED 控制 实验记录

> 日期：2026-08-26
> 地点/环境：VMware 虚拟机 + Ubuntu + ESP32-S3 开发板（USB 直通）

## 1. 实验环境

| 项目 | 值 |
|------|-----|
| 开发板 | ESP32-S3（QFN56，8MB Octal PSRAM，16MB Flash） |
| 固件 | MicroPython v1.29.0（`ESP32_GENERIC_S3-SPIRAM_OCT` 变体） |
| 串口 | `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5CBC064671-if00`（by-id 路径） |
| 工具 | mpremote 1.29.0 / pyserial（临时诊断脚本） |

## 2. 实验目的

1. 参考商家 AP 例程，让板子开启 WiFi 热点，手机连接实测。
2. 提供一个 `ip:port` HTTP 服务，手机浏览器可查看板子 Flash 里的文件。
3. 在网页底部增加 WS2812 灯珠颜色控制（取色器 + 预设色 + 熄灭）。

## 3. 实验过程

### 3.1 首次实现

`examples/02-ap-file-server/` 下 `config.py`（热点名/密码/端口/WS2812 引脚）
+ `main.py`（AP 模式 + 极简 HTTP 文件服务器）。

- HTTP 服务器用 **raw socket** 实现（几十行），不引第三方 web 框架：
  固件里没有 microdot（`import microdot` 报 ImportError，/lib 也不存在），
  用 mip 装依赖反而增加不稳定因素。
- 路由：`/` 目录列表（HTML，带文件大小）→ `/文件名` 按 MIME 返回内容 → 其余 404。
- 状态灯复用例程 01 探测的 WS2812（GPIO48）：红=启动，绿=就绪，蓝=收到请求。

### 3.2 手机首次测试：两个问题

用户手机连上了热点、看到了文件列表，但暴露两个 bug：

**问题 A：热点是开放网络，手机没让输密码。**
- 诊断：打断服务器循环后用 `ap.config('authmode')` 查询 → 返回 **0（AUTH_OPEN）**。
- 结论：**本固件 `ap.config(password=...)` 不会自动启用加密**，
  必须显式设置 `authmode=network.AUTH_WPA_WPA2_PSK`。
- 修复：`start_ap()` 里按「密码非空 → WPA2/WPA，为空 → OPEN」显式传 authmode；
  并加密码长度守卫（<8 位无法 WPA2，降级开放并打印警告）。

**问题 B：点文件名报 `'module' object has no attribute 'path'`。**
- 原因：`mime_of()` 用了 `os.path.splitext()`，而本固件 **没有 os.path**：
  `hasattr(os, 'path')` 为 False，`import os.path` 也 ImportError。
- 修复：手写扩展名解析 `name.rfind('.')`。

修复后二次测试：手机弹出密码框（12345678），点 `boot.py` 能看到内容 ✅。

### 3.3 加 LED 控制功能

- 页面底部新增「💡 LED 控制（WS2812）」面板：
  取色器 `<input type=color>` + 设置颜色 / 熄灭 / 恢复绿色 + 7 个预设色按钮。
- 前端：`sendHex(hex)` 跳转 `/setled?hex=RRGGBB`（GET，实现简单，页面自动跳回列表）。
- 后端：新增 `/setled` 路由，解析 hex（或 r/g/b 参数）→ `set_led_user()` 设置并保持 → 302 跳回 `/`。
- 状态灯逻辑改造：`led_user = None`（未设置 → 绿=就绪，请求时蓝闪一下）；
  用户设置后 `restore_led()` 保持用户颜色，不再被请求闪烁覆盖。

三次测试：取色器/预设色/熄灭全部即时生效，颜色保持 ✅。

### 3.4 调试过程中的工具经验

- 服务器 accept 循环阻塞主线程后，`mpremote exec/ls` 均报
  `could not enter raw repl`——REPL 被占，属正常现象。
- 验证改用 pyserial 临时脚本（用后即删）：
  复位（**esptool 风格 DTR/RTS 序列**，简单 toggle 无效）→ 抓启动日志 →
  Ctrl-C 打断 → REPL 发诊断命令 → Ctrl-D 软复位恢复运行。
- 后台监听脚本（pyserial 轮询读串口写日志）用来捕捉手机接入记录
  （`客户端接入: ('192.168.4.2', 端口)`），验证用户真实连接。

## 4. 最终结论

- 热点：**ESP-AP / 12345678**，WPA2/WPA 加密（`authmode=4`），IP **192.168.4.1**。
- 服务：**http://192.168.4.1:80/**，文件列表 + 文件内容查看 + 底部 LED 控制全部工作。
- `main.py` 开机自动运行；改热点名/密码/端口只需编辑 `config.py`。
- 遗留问题：无。小瑕疵：用户把灯设成蓝色时，请求蓝闪不可见（无实际影响）。

## 5. 经验教训（重点）

1. **MicroPython ESP32 AP 密码不生效的坑**：`ap.config(password=...)` 在本固件
   **不会自动改加密方式**，必须显式 `authmode=network.AUTH_WPA_WPA2_PSK`。
   识别特征：手机连热点不弹密码框。验证：`ap.config('authmode')`
   （0=开放，4=WPA2/WPA）。
2. **这版固件没有 os.path**：`hasattr(os, 'path')` 为 False、
   `import os.path` 报 ImportError。取扩展名等路径操作一律手写，
   不要假设桌面 Python 的 os.path 可用。
3. **无限循环程序阻塞 REPL**：accept 循环占着主线程，
   mpremote exec/ls 进不了 raw REPL 是预期行为；诊断要走 pyserial：
   复位序列 → Ctrl-C → 命令 → Ctrl-D 恢复，比反复拔插靠谱。
4. **DTR/RTS 复位序列有讲究**：CH343 自动复位电路要吃 esptool 风格序列
   （EN 拉低 → 释放、GPIO0 拉高 → 正常启动），乱 toggle 可能完全不触发复位。
5. **pkill -f 自杀坑**：命令串里包含匹配模式会连自己所在的 shell 一起杀，
   无输出的「命令消失」多半是这个；用 `pkill -f "python3 _listen[.]py"` 这类
   `[.]` 转义避免自匹配。
6. **后台串口监听与 mpremote 互斥**：pyserial 非独占打开串口时，
   与 mpremote 并发会互相干扰（数据被监听进程吃掉、raw REPL 进不去），
   操作前先停监听、操作完再挂。
7. **零依赖优先**：microdot 之类框架固件里没有，raw socket 几十行实现
   文件服务 + 一个控制接口完全够用，少一个依赖少一类翻车。
