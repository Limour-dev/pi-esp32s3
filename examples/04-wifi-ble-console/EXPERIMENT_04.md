# 例程 04：BLE 网页控制台 + WiFi 配置 实验记录

> 日期：2026-08-26
> 地点/环境：VMware 虚拟机 + Ubuntu + ESP32-S3 开发板（USB 直通）

## 1. 实验环境

| 项目 | 值 |
|------|-----|
| 开发板 | ESP32-S3（QFN56，8MB Octal PSRAM，16MB Flash） |
| 固件 | MicroPython v1.29.0（`ESP32_GENERIC_S3-SPIRAM_OCT` 变体） |
| 串口 | `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5CBC064671-if00`（by-id 路径） |
| 工具 | mpremote 1.29.0（SerialTransport 直连）/ pyserial / Node（网页协议模拟测试） |
| 客户端 | 用户手机 + Chrome/Edge（Web Bluetooth，页面挂 HTTPS） |

## 2. 实验目的

1. 在例程 03（BLE 网页控制台：文件 + LED）基础上，新增 **WiFi 服务**：
   扫描周围路由器、连接路由器（STA）、查看状态、配置回退热点（AP）。
2. 路由器/热点配置持久化到 `/wifi.json`，上电自动连接 + 断线自动重连。
3. 澄清并如实落地「热点转发路由器网络」的限制：本固件无 NAT，热点只作配置入口。

## 3. 实验过程

### 3.1 前置探测：热点转发到底能不能做？（关键决策点）

用户需求含「广播的热点转发路由器的网络」（经典 WiFi 中继）。先探测固件能力：

- **板端探测**：`dir(network)` 只有 `WLAN / country / hostname / ipconfig / phy_mode`，
  **没有 `NAT`**。
- **网络查证**：Micropython 官方讨论 #11907 明确「no way in micropython to instruct
  LWIP to do NAT, routing or other low-level network stuff」；NAT 中继方案
  （martin-ger/esp32_nat_router 等）都是 ESP-IDF 编译期启用 lwIP NAT 的自定义固件，
  非 MicroPython 主线的能力。
- **并发 AP+STA 实测可用**：AP 起在 192.168.4.1，STA 再激活，两接口共存正常；
  STA 连上路由器后 AP 信道自动跟随（标准并发行为）。

结论：**纯 MicroPython 无法做 IP 层转发**。与用户确认后按方案 2 实现：
**只做扫描 + 连接路由器 + 热点降级为配置入口，不做转发**（用户已确认选择）。

### 3.2 架构设计

- 复用例程 03 的 BLE 协议（CMD 写命令 / DATA notify 响应 / AUTH 认证 / DONE 收尾），
  WiFi 命令走同一对特征，无需新 GATT 服务。
- 新命令：`WIFI_SCAN` / `WIFI_CONNECT <b64ssid> <b64pwd>` / `WIFI_DISCONNECT` /
  `WIFI_FORGET` / `WIFI_STATUS` / `WIFI_AP <b64ssid> <b64pwd>`。
- **SSID/密码一律 base64**：实测本机周围就有中文/带空格的 SSID，直接塞行协议会断行。
- 热点永远开着（回退配置入口），`/wifi.json` 存路由器+热点配置，上电自连，
  主循环每 `STA_RETRY_INTERVAL` 秒自动重连。
- 状态灯扩展：用户色 > BLE 已连（蓝）> 正在连路由器（橙）> 路由器已连（青）> 广播中（暗绿）。

### 3.3 板端逻辑测试（宿主 mock，先于上板）

`test/test_wifi_board.py`：mock `network.WLAN`（可编程的成功/错密码/找不到网络）、
BLE、硬件模块，走 `_drain_cmds` 真实接收路径。覆盖：认证门禁、扫描（含中文 SSID
base64）、连接成功→`wifi.json` 落盘、错密码/找不到网络 → 正确 ERR 原因且**不覆盖
已保存配置**、状态行格式、断开保留配置、忘记清配置、热点重配落盘、配置读回、自动重连。
第一次跑挂是因为 CPython `time` 没有 `ticks_ms/ticks_diff`，测试里补桩解决。
一个断言起初写错：以为「错密码后 saved_sta 应为 None」，实际设备行为是**失败不触碰
已保存配置**（只有成功才写、FORGET 才清），修正断言而非改代码。

### 3.4 网页端模拟测试（Node + vm）

`test/test_wifi_web.mjs`：假设备实现 WiFi/认证/文件命令，驱动 `web/index.html` 真实 JS。
18 项全过：连接认证 → 自动刷状态、扫描列表渲染（信号/认证/信道）、点击列表项填入 SSID、
连接成功（进度行 + IP）与失败、状态刷新、断开、忘记、热点重配。
一个测试写法坑：mock DOM 惰性创建元素，测试直接 `els.wifiPwd.value=...` 会 undefined——
输入值改在 sandbox 内 `document.getElementById(...)` 设置。

### 3.5 上板实测（真机验证）

上传 boot/config/main 三件套后复位，启动横幅正确：
```
回退热点已开启: ESP32S3-AP (12345678)  IP 192.168.4.1
GATT 服务注册完成: led=16 cmd=19 data=21
正在广播: ESP32S3-WIFI
```

REPL 里把 `_notify` 换成 print、`pending` 塞真实命令串，驱动真实命令路径：

- **WIFI_SCAN**：真实扫到 11 个网络（Redmi_719_2.4G_8 -24dBm、ifudan.cn、E715、
  隐藏网络等），行格式 `N auth ch rssi b64` 正确，隐藏网络 b64 为空串正常。
- **WIFI_CONNECT（错密码打真实路由器）**：进度行 `C 1..C 12` 逐秒输出后
  `ERR wrong password`——状态码判因路径（`STAT_WRONG_PASSWORD`）真机验证通过。
- **WIFI_AP 重配 + 持久化**：改热点为 `ESP04-AP2` 后立即生效，`/wifi.json` 落盘；
  **软复位后应用自动加载该配置**（重启横幅直接起 `ESP04-AP2`），持久化闭环验证。
- **WIFI_STATUS**：`STA OFF / AP <b64> 192.168.4.1 0 / SAVED` 行格式正确。

### 3.6 一个「伪 bug」的排除过程

中途出现过 `WIFI_AP` 报 `Wifi Invalid Mode`、AP 状态异常。追查后确认：不是代码问题，
是**上一次失败的验证会话**（`exec` 内置 follow 超时 5s，代码 12 秒连接跑不完，
TransportError 后脚本没退出 raw REPL，板子停在半执行状态）把 AP 弄进了坏状态。
干净软复位后再测：`_ap_start()` 幂等重配、AP 激活中改 ESSID、恢复默认全部正常。
教训：**中断的 REPL 会话会污染 WiFi 状态，验证要「先软复位再进 REPL」**。

### 3.7 遗留/未验证项

- 真机「连接路由器成功」路径未实测（虚拟机环境拿不到真实路由器密码）：
  成功分支由 mock 测试覆盖，且 STA 连接 API 是标准行为；上板验证了同一条代码路径的
  失败分支（含状态码判因）。
- Web Bluetooth 真机端到端未测（VM 无蓝牙适配器，同 03）：靠 Node 假设备模拟 +
  板端真实命令路径双通道覆盖。

## 4. 最终结论

- BLE 广播：**ESP32S3-WIFI**，服务 `led=16 cmd=19 data=21`；认证密码默认 `1234`。
- WiFi 服务全通（上板实测）：扫描（真实 11 网络）、连接（错密码判因正确）、
  状态、热点重配、配置持久化 + 开机自动恢复。
- 热点永远在线（配置入口，192.168.4.1），**不转发网络**（无 NAT，设计确认如此）。
- 状态灯：暗绿=广播，蓝=BLE 已连，橙=正在连路由器，青=路由器已连，用户色优先。
- 文件/LED 服务与例程 03 完全一致（复用代码，回归无忧）。
- 测试归档：`test/test_wifi_board.py`（板端逻辑）、`test/test_wifi_web.mjs`（网页端），
  宿主可独立跑通，无需真硬件。

## 5. 经验教训（重点）

1. **先探测固件能力再承诺功能**：NAT 转发这类需求，先 `dir(network)` 探明，再查官方
   issue（#11907）确认「MicroPython 主线条没有 NAT」，最后与用户确认降级方案——
   探测证据 + 决策记录写进实验记录，避免做出「转发」的虚假承诺。
2. **中断的 REPL 会话会污染 WiFi/AP 状态**（`Wifi Invalid Mode` 假警报）：诊断顺序应为
   「软复位 → 等应用完整启动 → 再 Ctrl-C 进 REPL → 干净测试」。识别特征：AP 状态异常、
   `config('essid')` 返回默认值（ESP_XXXXXX）而非配置值。
3. **`exec` 内置 follow 超时约 5 秒**：长命令（扫描 3s + 连接 12s）会超时抛
   TransportError 且**不清理会话**，把板子留在半执行态；改用 `exec_raw_no_follow` +
   手动读输出（等待 `\x04` EOF 标记，串口 timeout 放宽到 40-60s）。
4. **SSID 必须 base64 过行协议**：中文/空格/隐藏网络 SSID 都会破坏文本行协议；
   base64 后板端/网页/测试三端（`ubinascii` / `btoa-atob` / `Buffer`）编码一致。
5. **失败连接不覆盖已保存配置**：`WIFI_CONNECT` 只有成功才写 `wifi.json`，
   失败只回 `ERR <原因>`——这是对用户友好的语义（配置不会因一次手误被清掉），
   测试断言要匹配真实语义而非直觉。
6. **WiFi 命令是阻塞的，网页超时与进度行要配套**：扫描 15s、连接 30s 超时；
   板端连接期间用 `C <秒>` 进度行推送，网页实时显示，体验可接受。
7. **并发 AP+STA 是标准能力但信道跟随**：STA 连上路由器后 AP 信道自动被拉到
   路由器信道，属正常并发行为，不是 bug。
8. **复用 03 全套协议经验**：DONE 收尾、bytearray 无 del/clear、一次注册全部
   GATT 服务、IRQ 轻量、断开 reject 挂起请求等坑全部继承规避，main.py 结构同源，
   回归成本低。
