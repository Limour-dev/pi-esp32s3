# 例程 04：BLE 网页控制台 + WiFi 配置 —— Agent 指导手册

> 本手册写给「agent」。你的任务是引导小白运行本目录例程：
> 浏览器（Chrome/Edge）通过 **Web Bluetooth** 连接 ESP32-S3，在网页上
> 查看/操作板子 Flash 文件、控制 WS2812 灯珠，并**扫描周围路由器、让 ESP32
> 连接路由器（STA）、配置回退热点（AP）**。
> 前置条件：设备已按仓库根目录 `SETUP_GUIDE.md` 配好 MicroPython 环境，
> 例程 01 已确认 WS2812 灯珠接 GPIO48。

## 1. 文件结构

| 文件 | 作用 |
|------|------|
| `boot.py` | 看门狗：main.py 崩溃自动重启，保证 BLE 广播与热点不掉线 |
| `config.py` | 设备名 / UUID / 灯珠引脚 / 蓝牙密码 / 热点默认值 / 连接超时 |
| `main.py` | ESP32-S3 端 BLE GATT 服务器：文件服务 + LED 服务 + **WiFi 服务** |
| `web/index.html` | 网页端（Web Bluetooth 客户端，单文件，静态托管即可） |
| `test/` | 板端逻辑测试（`test_wifi_board.py`）+ 网页端模拟测试（`test_wifi_web.mjs`） |

**WiFi 配置（连哪个路由器、热点叫什么）不在 config.py 里**：通过网页 WiFi 面板
操作，保存到板子 Flash 的 `/wifi.json`，上电自动按保存的配置连接路由器。
改 `config.py` 的 `BLE_PASSWORD` / UUID / 设备名后，`web/index.html` 顶部的常量要同步改。

## 2. 架构说明（为什么这么设计）

- **网页不跑在板子上**：Web Bluetooth 要求 HTTPS 上下文，网页是独立静态文件，
  板子只广播 BLE。命令走 CMD 特征（写入 `\n` 结尾的 ASCII 行），响应走 DATA 特征 notify。
- **三个能力**：文件服务（同 03）、LED 服务（写 3 字节 RGB）、WiFi 服务（扫描/连接/状态/热点，复用同一对 CMD/DATA 特征，无需新 GATT 服务）。
- **热点永远开着（配置入口）**：ESP32 同时跑 AP+STA（并发模式），
  连上路由器时 AP 自动跟随路由器信道；连不上路由器时热点兜底。
- **⚠️ 无 NAT，热点不转发网络**：本固件 MicroPython 未编译 lwIP NAT，
  `dir(network)` 里没有 `NAT`。热点下的设备只能访问 ESP32 自身服务，
  **不能**通过 ESP32 上网（经典 WiFi 中继需换带 NAT 的固件，如 martin-ger/esp32_nat_router）。
  这是例程 04 与「中继」的本质区别，向用户讲清楚，别承诺能转发。
- **SSID/密码走 base64**：WiFi 名字可含空格/中文/任意字节，直接塞进行协议会破坏行解析，
  所以 `WIFI_SCAN`/`WIFI_CONNECT`/`WIFI_AP` 的参数一律 base64。
- **连接是阻塞的**：`WIFI_CONNECT` 在板端主循环里同步等待（默认最长 20 秒），
  期间 BLE 命令暂停处理（网页端该请求超时设 30 秒，并展示 `C <秒>` 进度行）。
  扫描同理（约 2-3 秒，网页超时 15 秒）。

## 3. 先确定串口（编号会变，用 by-id）

```bash
ls -l /dev/serial/by-id/
```
后面命令里的 `<PORT>` 用 by-id 完整路径替换。

## 4. 上传并运行（板子端）

```bash
python3 -m mpremote connect <PORT> cp boot.py :
python3 -m mpremote connect <PORT> cp config.py :
python3 -m mpremote connect <PORT> cp main.py :
python3 -m mpremote connect <PORT> reset
```

`main.py` 是开机自启文件名，复位后自动运行。串口应打印：

```
ESP32-S3 例程 04：BLE 网页控制台 + WiFi 配置（密码保护已开启）
设备名: ESP32S3-WIFI  |  版本: 1.0  |  密码: 1234
回退热点已开启: ESP32S3-AP (12345678)  IP 192.168.4.1
GATT 服务注册完成: led=16 cmd=19 data=21
正在广播: ESP32S3-WIFI
```

板载 WS2812 灯珠应显示**暗绿色**（广播中）。若之前保存过 `/wifi.json`，
会看到「自动连接路由器: <SSID> ...」并在成功后变**青色**。

> 上传注意：板上有看门狗 `boot.py`，`mpremote cp` 进 raw REPL 会软复位被挡，
> 属预期（见 EXPERIMENT_GUIDE 8.1 的可靠上传姿势）。

## 5. 部署网页（需要 HTTPS）

`web/index.html` 是零依赖单文件，任选一种 HTTPS 托管（GitHub Pages / Netlify /
Cloudflare Pages），或本地 `python3 -m http.server 8000` 后用 `localhost` 访问
（localhost 也算安全上下文，Web Bluetooth 可用）。

> ⚠️ 浏览器要求：**Chrome / Edge**（桌面版或 Android）；iOS Safari 不支持 Web Bluetooth。

## 6. 引导用户测试

1. 板子上电（main.py 自动跑，灯珠暗绿 = 广播中，热点 ESP32S3-AP 已开启）。
2. Chrome/Edge 打开部署好的页面 → 连接设备 → 选 `ESP32S3-WIFI` → 输入密码（默认 `1234`）。
3. 验证 WiFi 面板：
   - **扫描路由器**：出现附近 WiFi 列表（信号条、加密类型、信道），点击某项自动填入 SSID；
   - **连接路由器**：填密码 → 连接 → 日志出现进度行与「已连接路由器，IP: …」；
     成功后状态面板显示 STA 已连接，灯珠变**青色**；路由器配置已存 `/wifi.json`；
   - **重启板子**：上电自动按保存配置连路由器（验证持久化 + 自动重连）；
   - **断开（保留配置）/ 忘记配置**：断开连接但保留配置；忘记则删除配置并断开；
   - **回退热点**：改热点名/密码 → 应用，立即生效（手机搜新热点名）；
   - **限制演示**：手机连上 ESP32 的热点，浏览器打开 http://192.168.4.1 之类只能访问
     ESP32 自身（本固件无 NAT，不能上网）——如实告知用户。
4. 顺带验证（同例程 03）：文件列表/查看/下载/上传/删除、LED 选色即时变色。

## 7. 排错速查

| 现象 | 排查 |
|------|------|
| 页面提示「不支持 Web Bluetooth」 | 换 Chrome/Edge；确认 HTTPS 或 localhost |
| 搜不到设备 | 板子是否上电且 main.py 在跑（灯珠暗绿）；另一台设备连着时已停广播；距离太远 |
| 连接后提示输密码 / 密码错误 | 密码是 `config.py` 的 `BLE_PASSWORD`（默认 `1234`），连错 3 次自动断开 |
| 扫描超时 / 扫不到路由器 | 板子离路由器太远；扫描要 2-3 秒别急着点；BLE 与 WiFi 共用一个射频，扫描期间 BLE 可能短暂不稳 |
| 连接路由器一直失败 | 看串口日志的原因：`wrong password`（密码错）、`network not found`（路由器不在范围/开了 MAC 过滤）、`handshake timeout`（信号差/信道拥挤）；20 秒超时是默认值 |
| 连接成功但没保存 | 只有成功才写 `/wifi.json`；失败不会覆盖已有配置 |
| 断电后不自动连 | 确认之前连接成功过（`/wifi.json` 存在）；`STA_RETRY_INTERVAL` 默认 30 秒，上电后稍等 |
| 热点改名后旧名没了 | 正常，热点是同一个接口换了名字；用新名搜 |
| 热点下的设备上不了网 | 本固件无 NAT，热点不转发网络（设计如此，见第 2 节） |
| 命令超时 | 板子在忙（扫描/连接阻塞中）；一次只操作一个动作 |
| REPL 连不上（mpremote exec 报错） | 看门狗 + 主循环占着主线程，属正常；Ctrl-C 打断或用复位 |
| 想恢复例程 03 | 重新上传 `examples/03-ble-file-led/` 的三个 py 文件 |
| `wifi.json` 里有明文密码 | 是（Flash 明文保存），BLE 空口也是明文；只防误连不防嗅探，别存重要密码 |

## 8. 已踩过的坑（实现时别重犯）

1. **MicroPython 无 NAT**：`dir(network)` 实测没有 `NAT`（Micropython#11907 官方也确认
   「no way in micropython to instruct LWIP to do NAT」）。「热点转发网络」在纯 MicroPython
   上做不了，只能并发 AP+STA 让热点访问 ESP32 自身；要真中继得换固件（ESP-IDF + NAT / martin-ger 项目）。
2. **AP+STA 并发时信道自动跟随**：STA 连上路由器后，AP 被挤到路由器同一信道，
   AP 的 `channel` 配置只在未连 STA 时生效；这是并发模式的正常行为，别当成 bug。
3. **`_ap_start()` 对已激活 AP 重配没问题**（实测幂等），但注意别在 AP 半启动时打断
   （watchdog 重启窗口内狂按 Ctrl-C 会让 AP 停在坏状态，报 `Wifi Invalid Mode`；
   干净重启一次即可恢复，不是代码 bug）。
4. **SSID 必须 base64 过行协议**：路由器名可含空格/中文/不可见字节；中文 SSID 实测
   （本机周围就有）直接塞行协议会断行。板端 `_b64s()`、网页 `btoa/atob`、测试 `Buffer` 三端一致。
5. **WiFi 命令是阻塞的**：扫描 2-3 秒、连接最长 20 秒，期间 BLE 主循环暂停；
   网页端对应请求超时要放宽（扫描 15s、连接 30s），并利用 `C <秒>` 进度行缓解等待焦虑。
6. **错误状态码判因**：`sta.status()` 在超时后能区分 `STAT_WRONG_PASSWORD` /
   `STAT_NO_AP_FOUND` / `STAT_CONNECT_FAIL` 等，用状态码给用户报原因比「timeout」有用。
7. **只读配置在文件、写死在 config.py 要分清**：路由器/热点配置是用户数据放 `/wifi.json`
   （明文，文档明示），设备名/UUID/密码这类「出厂值」放 `config.py`。
8. **复用 03 的坑**：`gatts_register_services` 一次注册全部服务；`bytearray` 不支持
   `del` 切片和 `.clear()`；IRQ 里只 append 字节；每条命令响应以 `DONE` 收尾；
   网页 `writeValue` 同步异常要 try/catch；断开时 reject 挂起请求——本目录 main.py 已全部遵守。
