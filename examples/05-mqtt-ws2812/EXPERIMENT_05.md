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
   新增 **MQTT 配置**：网页 BLE 面板填写 broker 地址/端口/用户名/密码，保存到 `/mqtt.json`
   （路由器配置单独存 `/wifi.json`，互不影响）。
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
- 配置分开存：路由器 `/wifi.json`（`{"sta": {...}}`），MQTT `/mqtt.json`（`{"mqtt": {...}}`）；`MQTT_SET` 只要求成功保存，
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
- 板子当前 `/mqtt.json` 存有验证用的 `broker.emqx.io`（匿名）配置，用户首次上电会连公共 broker，
  属无害演示；接入自有 broker 时在网页面板覆盖保存即可。

## 4. 最终结论

- BLE 广播：**ESP32S3-MQTT**；WiFi 只走 STA，**无回退热点（AP 已移除）**。
- MQTT：TLS 8883 + 账号密码（匿名亦可），配置经网页 BLE 面板保存到 `/mqtt.json`（WiFi 在 `/wifi.json`），
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

## 6. CA 证书配置补充（ZeroSSL 实战问答）

> 2026-09-01 补充：用户实操时问到「broker 证书经常更新怎么办 / fullchain 怎么配 / 只想传根行不行」，结论如下（与 AGENT_GUIDE.md 第 9 节一致）。

- **`/mqtt_ca.pem` 的来源**：**用户手动上传**（网页 BLE 文件面板或 mpremote cp），固件无内置 CA 库（见 3.1.3 探测）。
- **ZeroSSL 证书链（2026-09-01 本仓库实测 `cdn-g.limour.top:8883`，`openssl s_client -showcerts` 抓链）**：
  `*.limour.top` → 中间 `ZeroSSL ECC DV SSL CA 2`（**ZeroSSL 自有中间**，不是 Sectigo 老中间）→ 根
  `Sectigo Public Server Authentication Root E46`（被 USERTrust ECC Certification Authority 交叉签名）。
  RSA 证书对应中间 `ZeroSSL RSA DV SSL CA 2`，根同为 Sectigo E46 系。
- **叶子续期不用重传**：服务器握手现发叶子 + 中间，板子只存中间 + 根；新叶子只要还是同一中间签的就能过。
  需要更新的只有三种情况：换 CA 供应商 / 中间证书轮换 / 根过期（根有效期一般十年以上，基本不用管）。
- **`fullchain.pem` 整个传上去就能用**（含叶子也无妨，校验时多余证书被忽略）；ZeroSSL 下载包里的 `ca_bundle.crt`（中间+根）最干净。
- **2026-09-01 已验证**：`openssl s_client -showcerts` 从线上抓的中间+根拼接文件（3264B）直接当 `/mqtt_ca.pem`，板子 TLS 校验通过（此前旧链报 `The certificate is not correctly signed by the trusted CA`）。
- **只传根可行**，前提是 broker 下发中间证书（Mosquitto / EMQX 默认都会）；broker 只发叶子时不成立，得把中间也带上。
- 提取根 / 从 broker 现抓链 / 传前验证的 openssl 命令，见 AGENT_GUIDE.md 第 9 节 9.2–9.4。

### 6.1 板子面板显示 CONNECTED 但 broker 上没有它（排查记录）

> 2026-09-01 用户实测：BLE 网页面板 MQTT 面板显示「状态 CONNECTED / 配置 cdn-g.limour.top:8883 / 用户 limour」，
> 但 MQTT Explorer 连上后只看到 `$SYS`，看不到任何 `esp32s3/` 主题。

排查（宿主机 paho 只读 probe，归档于 `test/test_mqtt_broker_probe.py`）：

1. 连接 `cdn-g.limour.top:8883`（TLS + 系统信任库 + 账号密码）→ `rc=Success`，凭据有效，broker 是 Mosquitto 2.1.2。
2. 订阅 `esp32s3/#`（22 秒）：**零条消息**——没有 `esp32s3/status` 也没有 `esp32s3/led/state` 的保留消息。
3. 订阅 `$SYS/broker/clients/connected`：`1`（只有 probe 自己）→ 中途变 `2`（另一客户端连上，但没发任何 esp32s3 消息，
   应为用户开着的 MQTT Explorer）。

结论与判断依据：

- **板子此刻不在这个 broker 上**。若板子在线，`clients/connected` 应 ≥2 且连上时会发两条保留消息
  （`esp32s3/status=online` + `esp32s3/led/state`，见 main.py `_mqtt_connect`）。
- **连 `offline` 保留消息都没有** → 板子从未成功连上过这个 broker（或 broker 重启清过保留且板子没重连成功）。
  LWT 触发也会留下 `esp32s3/status=offline` 保留消息。
- 网页面板的「CONNECTED」是**过期状态**（Web Bluetooth 面板轮询到的是之前某时刻的状态）。
- `$SYS` 任何 broker 都有，**「看得到 $SYS」不能证明连对了**；要看 `$SYS/broker/clients/connected` 在线数
  和 `esp32s3/#` 保留消息。

**后续进展（同日复盘，两个根因都已定位并修复）**：

1. **根因一：板子根本没连 WiFi**——查板子 Flash，`/wifi.json` 只有 `mqtt` 键、没有 `sta`
   （路由器配置丢失，最可能是网页点过「忘记配置」）。无 WiFi → 无 NTP 校时 → MQTT 连不上。
   用网页 BLE 面板重配 `Redmi_719_2.4G_8` 后恢复。
2. **根因二：TLS 证书校验失败**——网页 MQTT 面板报「The certificate is not correctly signed by the trusted CA」。
   板子 `/mqtt_ca.pem` 里装的是旧文档写错的链；用 `openssl s_client -showcerts` 从线上抓真实链，
   拼 `ZeroSSL ECC DV SSL CA 2`（中间）+ `Sectigo Public Server Authentication Root E46`（根）
   共 3264 字节传上去，TLS 校验通过、MQTT 秒连。
3. **修复验证**（probe 实测）：`esp32s3/status=online`（保留）+ `esp32s3/led/state=#00b4b4`，
   `$SYS/broker/clients/connected` 2→3，exit=0。板端日志：路由器 Redmi_719_2.4G_8（192.168.88.242）
   → NTP 校时 → MQTT 已连接 cdn-g.limour.top:8883。
4. **顺带重构**：MQTT 配置从 `/wifi.json` 拆到独立 `/mqtt.json`（config.py `MQTT_CFG_FILE`），
   WiFi 与 MQTT 配置互不影响；板子上旧 `wifi.json` 里的 mqtt 键已迁移。

### 6.2 MQTT Explorer 实操记录（Retain 控制 + 重启自动恢复）

> 2026-09-01 用户在 MQTT Explorer 上实际控制板子，验证「Retain 控制 → 重启 → 自动执行」：

1. MQTT Explorer 连接 `cdn-g.limour.top:8883`（TLS + 账号密码），已能看到 `esp32s3` 树：
   `esp32s3/status=online`、`esp32s3/led/state` 两条保留消息。
2. **Publish** 面板往 `esp32s3/led` 发布 `0,1,0` 并勾选 **Retain** → 灯珠立刻变色
   （该板 WS2812 功率高，通道值 1 肉眼可见）。
3. 重启板子（软复位）→ 完整自动流程（串口日志实录）：
   ```
   检测到已保存路由器配置: Redmi_719_2.4G_8
   路由器已连接: Redmi_719_2.4G_8 -> 192.168.88.242
   NTP 校时完成: (2026, 8, 31, 10, 11, 41)
   MQTT 已连接: cdn-g.limour.top:8883 | 订阅 esp32s3/led 控制灯珠
   MQTT LED 设置为 rgb(0,1,0)   ← 订阅时收到 Retain 消息，立即执行
   ```
4. broker 侧确认（probe）：`esp32s3/status=online`、`esp32s3/led=0,1,0`（Retain 控制消息仍在）、
   `esp32s3/led/state=#000100`（板子回发，与执行结果一致）。
5. **结论**：Retain 控制消息实现「颜色持久化」——板子每次上电/重连都恢复最后 Retain 的颜色；
   发**空消息 + Retain** 可清除（回到指示灯状态色，见 §7）。
6. 顺带优化：指示灯状态色缩亮到 0-10（`config.INDICATOR_BRIGHTNESS`），见 §7 表格。

## 7. 灯状态说明（指示灯颜色速查）

| 状态 | 显示色（缩亮后） | 源色 0-255 | 含义 |
|------|----------------|-----------|------|
| 广播中 | 暗绿 `(0,2,0)` | `(0,40,0)` | 板子正常运行、BLE 可被搜索；未连 BLE、未连 WiFi |
| BLE 已连接 | 蓝 `(0,0,3)` | `(0,0,80)` | 网页/手机已连上 BLE（此时停止广播） |
| 正在连路由器 | 橙 `(10,5,0)` | `(255,120,0)` | STA 连接中（约 20 秒超时，失败自动重试） |
| 路由器已连接 | 青 `(0,7,7)` | `(0,180,180)` | WiFi 已通，接着 NTP 校时 → 自动连 MQTT |
| 用户色 | 按指令 0-255 | — | 网页 BLE 或 MQTT `esp32s3/led` 设置的颜色 |

说明：

- 指示灯状态色默认按 `config.INDICATOR_BRIGHTNESS`（默认 10）从 0-255 等比缩小
  （`main._dim_indicator`），避免高功率灯珠刺眼；**用户控制的颜色不受影响**，仍走 0-255。
- **用户色优先于状态色**：只要设置过用户色（BLE 或 MQTT），状态色不显示；
  清掉 Retain 控制消息（发空消息 + Retain）或 `MQTT_FORGET` 后回到状态色。
- 优先级顺序（`main._led_state()`）：用户色 → BLE 已连接(蓝) → 连路由中(橙) → 路由已连(青) → 广播(暗绿)。
