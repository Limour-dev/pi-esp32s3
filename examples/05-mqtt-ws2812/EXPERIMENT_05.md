# 例程 05：BLE 网页控制台 + WiFi + MQTT（WS2812 控制）实验记录

> 日期：2026-08-31
> 地点/环境：VMware 虚拟机 + Ubuntu + ESP32-S3 开发板（USB 直通）

## 1. 实验环境

| 项目 | 值 |
|------|-----|
| 开发板 | ESP32-S3（QFN56，8MB Octal PSRAM，16MB Flash） |
| 固件 | MicroPython v1.29.0（`ESP32_GENERIC_S3-SPIRAM_OCT` 变体） |
| 串口 | `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5CBC064671-if00`（by-id 路径） |
| 工具 | mpremote 1.29.0 / pyserial / paho-mqtt（宿主机端到端测试）/ Node（网页协议模拟） |
| 路由器 | 用户真实路由器 `Redmi_719_2.4G_8`（例程 04 已保存配置，板子直接继承） |
| MQTT broker（验证用） | `broker.emqx.io:8883`（公网 EMQX，TLS，匿名；验证 CA 用真实证书链） |

## 2. 实验目的

1. 在例程 04（BLE 网页控制台：文件 + LED + WiFi）基础上，**移除回退热点（AP）**，
   新增 **MQTT 配置**：网页 BLE 面板填写 broker 地址/端口/用户名/密码，保存到 `/wifi.json`。
2. MQTT 使用 **TLS（端口 8883）+ 账号密码认证**；配置好后板子订阅主题，
   **通过 MQTT 消息控制 WS2812 灯珠**（`#RRGGBB` / `r,g,b`），并回发当前颜色状态。
3. 宿主机 mock 测试 + 真机 + 公网 broker 全链路验证（真实 TLS 握手）。

## 3. 实验过程

### 3.1 前置探测（决定技术选型的关键三步）

1. **板子有没有 MQTT 库？** pyserial 进 REPL `import mqtt` → `ImportError: no module named 'mqtt'`。
   结论：**必须自带客户端**。采用 micropython-lib 的 `umqtt.simple`（2024 版，支持
   `ssl=SSLContext` 直传，`MQTTClient(client_id, server, port, user, password, keepalive, ssl)`），
   以 `umqtt/` 包的形式随代码上传。
2. **TLS 能不能用？** `import ssl` → OK，`SSLContext` 有 `load_verify_locations / verify_mode / wrap_socket`。
3. **固件有没有内置 CA 库？** `strings ~/mpy-esp32s3/fw.bin | grep -c "BEGIN CERTIFICATE"` → **1**，
   且那只是 mbedTLS 的格式串（还有 "The certificate has been revoked..." 等错误文案），
   **没有根证书库**。结论：`MQTT_TLS_VERIFY=True` 必须把 CA 链上传为 `/mqtt_ca.pem`
   用 `load_verify_locations(cadata=...)` 加载；否则只能 `MQTT_TLS_VERIFY=False`。

### 3.2 架构设计

- 复用例程 04 的 BLE 协议（CMD 写命令 / DATA notify 响应 / AUTH 认证 / DONE 收尾）。
- 新命令：`MQTT_SET <b64host> <port> <b64user> <b64pass>`、`MQTT_FORGET`、`MQTT_STATUS`
  （返回 `MQTT <state>` / `MQTT_CFG <b64host> <port> <b64user>` / `MQTT_LED <b64topic>`
  / 可选 `MQTT_ERR <b64err>`）。
- `/wifi.json` 扩展为 `{"sta": {...}, "mqtt": {...}}`；`MQTT_SET` 只要求成功保存，
  连接由主循环 `_mqtt_tick()` 状态机驱动：WiFi 就绪才连 → 订阅灯珠主题 → 保活（check_msg +
  keepalive/2 的 ping）→ 断线按 `MQTT_RETRY_INTERVAL`（10s）重连。
- 灯珠控制：MQTT 订阅消息 `#RRGGBB`/`#RGB`/`r,g,b` → 解析 → 与 BLE 用户色同优先级
  （`led_user_src` 区分来源，BLE 断开只清 BLE 色）；当前颜色发布到 `esp32s3/led/state`
  （保留消息），上线/离线发布 `esp32s3/status`（保留 + LWT）。
- 颜色发布在**主循环 `apply_led()`** 里做（置 `led_pub_dirty` 标记），不在 BLE IRQ 里做
  （IRQ 里做 TLS socket IO 是禁忌）。

### 3.3 测试中暴露并修复的三个真 bug（关键）

1. **`MQTT_SET` 空用户名/密码被拒绝**：`rest.strip()` 后 `split(" ")` 把尾部空参数折叠，
   `len(parts)<4` 直接拒——匿名 broker（如 emqx 公网）配不上。修复：只强制 host/port 两段，
   user/pass 用 `len(parts) > i and parts[i].strip()` 判空补默认。
   修复前宿主测试就拦住了（"3 参数被拒"用例失败），符合「mock 先行」的价值。
2. **时钟判定在 CPython 上恒 False**：`y, ..., wd, yd = time.localtime()` 解包——CPython 返回
   9 元组、MicroPython 返回 8 元组，宿主上抛 ValueError 被 except 吞 → `_clock_sane()` 永远 False
   → 时钟门禁永远挡着 MQTT 连接 → 宿主测试实例数为 0。修复：`time.localtime()[0]` 只取下标。
3. **真机 TLS 首连失败：「The certificate validity starts in the future」**：RTC 无电池，
   上电时钟停在 2000-01-01，mbedTLS 按系统时间校验证书 notBefore → 报“证书有效期从未来开始”。
   修复：WiFi 就绪后 **NTP 校时**（`ntptime.settime()`，失败 30s 重试）；并且
   `MQTT_TLS_VERIFY=True` 且时钟未校准时**不发起连接**（状态提示“等待 NTP 校时”），
   避免浪费 TLS 握手。真机验证：校时后 RTC 显示 `(2026, 8, 31, 0, 9, ...)`，MQTT 连上。

### 3.4 宿主测试（先于上板）

- `test/test_mqtt_board.py`：mock BLE/network/ssl/umqtt/ntptime/硬件，走 `_drain_cmds` 真实路径。
  覆盖：认证门禁、WiFi 扫描/连接/断开/忘记/状态（**断言无 AP 行**）、MQTT_SET 保存与参数校验
  （含匿名 broker 空凭据）、MQTT_STATUS 格式、MQTT 连接状态机（WiFi 断不连 / 时钟未校时不连 /
  连接参数与 CA 加载 / 订阅主题 / 上线发布 / 控灯 `#RRGGBB`、`r,g,b` / 非法负载与无关主题忽略 /
  BLE 断开只清 BLE 色 / check_msg 断线检测 / 自动重连 / 连接失败错误记录 / 配置读回 / FORGET / 持久化）。
- `test/test_mqtt_web.mjs`：假设备驱动 `web/index.html` 真实 JS。25 项全过：连接认证 →
  自动刷 WiFi+MQTT 状态、WiFi 面板全流程（扫描/填入/连接成功失败/断开/忘记）、MQTT 面板
  （保存配置/校验/状态刷新/忘记），并断言 **WiFi 状态面板不再显示热点**。
- 全部通过后上板。

### 3.5 上板实测（真机 + 公网 broker 全链路）

1. **上传**：mpremote cp 被看门狗挡住（软复位后 main.py 占住 REPL，预期）。
   用 pyserial raw REPL（Ctrl-A）+ base64 分块写入 5 个文件（boot/config/main/umqtt 两文件），
   全部 `WROTE ... OK`。
2. **启动**：横幅正确（例程 05、ESP32S3-MQTT、主题/端口/CA 提示）；继承例程 04 保存的
   `Redmi_719_2.4G_8` 自动连上（192.168.88.242）。
3. **NTP + MQTT**：校时完成 → `MQTT 连接 broker.emqx.io:8883` → 首次因时钟报证书时间错误 →
   校时后重试成功 → `MQTT 已连接`。REPL 查 `main.mqtt_state` = `connected`。
4. **端到端灯控回环（宿主机 paho + TLS）**：
   - 订阅 `esp32s3/led/state` + `esp32s3/status` → 收到保留消息 `online` 和当前色 `#00b4b4`（青）；
   - 发布 `#ff0000` → 收到 `#ff0000`；发布 `0,255,0` → 收到 `#00ff00`；
   - 发布 `bogus` → 状态**不变**（非法负载忽略，真机验证）；
   - 发布 `128, 0, 255` → 收到 `#8000ff`。
   全链路（公网 broker TLS 8883 → 板子 TLS 校验 CA → 订阅 → 控灯 → 状态回发）**PASS**。

### 3.6 遗留/未验证项

- **真实 Mosquitto（用户名密码认证）未验证**：用公网匿名 broker 验证了 TLS+订阅+控灯；
  账号密码路径由宿主测试覆盖（MQTTClient 收到 user/password 字节），且 broker 侧认证是
  标准行为。用户按其 `mqtt-server-deploy.md` 部署的 8883+TLS+账号密码可直接使用。
- Web Bluetooth 真机端到端未测（VM 无蓝牙适配器，同 03/04）：靠 Node 假设备模拟 +
  板端真实命令路径双通道覆盖。
- 板子当前 `/wifi.json` 存有验证用的 `broker.emqx.io`（匿名）配置，用户首次上电会连公共 broker，
  属无害演示；接入自有 broker 时在网页面板覆盖保存即可。

## 4. 最终结论

- BLE 广播：**ESP32S3-MQTT**；WiFi 只走 STA，**无回退热点（AP 已移除）**。
- MQTT：TLS 8883 + 账号密码（匿名亦可），配置经网页 BLE 面板保存到 `/wifi.json`，
  上电 WiFi 就绪后自动连接、断线自动重连。
- 灯珠控制：订阅 `esp32s3/led`，消息 `#RRGGBB`/`r,g,b`；状态回发 `esp32s3/led/state`（保留），
  上线/离线 `esp32s3/status`（保留 + LWT）。真机全链路验证通过。
- 前置条件写清：固件无内置 mqtt 模块（需带 `umqtt/`）；无内置 CA 库（需上传 CA 链或关校验）；
  TLS 校验依赖 NTP 校时。
- 测试归档：`test/test_mqtt_board.py`（板端）、`test/test_mqtt_web.mjs`（网页端），宿主独立跑通。

## 5. 经验教训（重点）

1. **先探固件能力再设计**：三步探测（mqtt 模块？ssl？CA 库？）决定了整个方案——
   带库、传 CA、NTP 校时。`strings fw.bin | grep -c BEGIN` 这种“二进制里有没有根证书”的
   探测方法可复用。
2. **RTC 无电池 → TLS 证书时间校验必挂**：识别特征就是 mbedTLS 报
   “The certificate validity starts in the future”。先 NTP 校时再连 TLS；且在代码里
   **主动门禁**（时钟不可信就不连），比“连了再失败”体验好。
3. **微控制器代码也要写成宿主可测**：`time.localtime()` 元组长度差异（CPython 9 vs MicroPython 8）
   这种坑，宿主测试直接暴露，不用上板。写成“只取下标”的兼容写法。
4. **行协议的空参数折叠**：`rest.strip().split(" ")` 会把尾部空参数吃掉——所有“参数可空”
   的命令都要用 `len(parts) > i` 判空，而不是定长校验。
5. **`import main` 拿旧模块**：REPL 里改完文件后 `import main` 仍是内存里的旧代码，
   必须 `sys.modules.pop('main', None)` 再 import（或软复位）。识别特征：改了代码行为不变。
6. **上传姿势再确认**：看门狗挡 mpremote cp；pyserial Ctrl-C 打断 → Ctrl-A raw REPL →
   base64 分块写文件最稳（同 03 的结论，本次再次验证）。
7. **保留消息 + LWT 是好设计**：新订阅者立即拿到当前颜色（`state` 保留）与设备在线状态
   （`status` 保留 + offline LWT），让“设备当前色”可被任何客户端查询。
8. **IRQ 里不做网络 IO**：BLE IRQ 收到颜色只置脏标记，发布放主循环——TLS socket 写
   在 IRQ 里会阻塞/重入，是隐患。
