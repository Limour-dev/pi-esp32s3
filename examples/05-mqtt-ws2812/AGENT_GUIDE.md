# 例程 05：BLE 网页控制台 + WiFi + MQTT（WS2812 控制）—— Agent 指导手册

> 本手册写给「agent」。你的任务是引导小白运行本目录例程：
> 浏览器（Chrome/Edge）通过 **Web Bluetooth** 连接 ESP32-S3，在网页上
> 查看/操作板子 Flash 文件、控制 WS2812 灯珠、**扫描/连接路由器（STA）**，
> 并**配置 MQTT（TLS 8883 + 账号密码）**——配置好后，任何 MQTT 客户端发布
> `#RRGGBB` 或 `r,g,b` 到控制主题即可点亮灯珠。
> 本例程在例程 04 基础上**移除了回退热点（AP）**，联网全部走 STA。
> 前置条件：设备已按仓库根目录 `SETUP_GUIDE.md` 配好 MicroPython 环境，
> 例程 01 已确认 WS2812 灯珠接 GPIO48。

## 1. 文件结构

| 文件 | 作用 |
|------|------|
| `boot.py` | 看门狗：main.py 崩溃自动重启（同 03/04） |
| `config.py` | 设备名 / UUID / 灯珠引脚 / 蓝牙密码 / WiFi 参数 / **NTP 参数（服务器、超时）** / **MQTT 参数（端口、主题、CA 文件、TLS 开关）** |
| `main.py` | ESP32-S3 端 BLE GATT 服务器：文件服务 + LED 服务 + WiFi 服务 + **MQTT 客户端** |
| `umqtt/` | 自带的 MQTT 客户端库（micropython-lib `umqtt.simple`，本固件 **无内置 mqtt 模块**，必须随代码上传） |
| `web/index.html` | 网页端（Web Bluetooth 客户端，单文件，静态托管即可）：WiFi 面板 + **MQTT 面板** |
| `test/` | 板端逻辑测试（`test_mqtt_board.py`）+ 网页端模拟测试（`test_mqtt_web.mjs`） |

**WiFi/MQTT 连接配置不在 config.py 里**：通过网页面板操作，路由器配置保存到板子 Flash 的 `/wifi.json`
（内容 `{"sta": {...}}`），MQTT 配置保存到 `/mqtt.json`（内容 `{"mqtt": {...}}`），上电自动按保存的配置连路由器、再连 MQTT。
改 `config.py` 的 `BLE_PASSWORD` / UUID / 设备名 / MQTT 主题后，`web/index.html` 顶部常量要同步改。

## 2. 架构说明（为什么这么设计）

- **网页不跑在板子上**：Web Bluetooth 要求 HTTPS 上下文，网页是独立静态文件，板子只广播 BLE。
  命令走 CMD 特征（写入 `\n` 结尾的 ASCII 行），响应走 DATA 特征 notify（同 03/04）。
- **三个面板、四个能力**：文件服务（同 03）、LED 服务（写 3 字节 RGB）、WiFi 服务
  （扫描/连接/状态/断开/忘记，复用 CMD/DATA 特征）、MQTT 服务（配置/状态，同通道）。
- **无回退热点**：例程 04 的 AP（回退热点）已移除。断网时设备无法从热点配置——
  配置入口是 **BLE 网页控制台**（本来也是 04 的主要入口，AP 只是兜底，删掉不损失主链路）。
- **MQTT 依赖 STA**：`_mqtt_tick()` 只有路由器已连接时才建连，断网自动断开、恢复后自动重连。
- **TLS 证书校验依赖系统时钟**：本板 RTC 无电池，上电时钟停在 2000 年，证书会报
  “validity starts in the future”。因此 WiFi 就绪后自动 **NTP 校时**（`ntptime`，失败每 30 秒重试）；
  `MQTT_TLS_VERIFY=True` 且时钟未校准时，MQTT 不会发起连接（状态显示“等待 NTP 校时”）。
- **TLS 校验的 CA 必须上传**：本固件（v1.29.0）**没有内置 CA 证书库**（固件里只有格式串，
  无根证书）。`MQTT_TLS_VERIFY=True` 时把服务器 CA 的 PEM 上传为 `/mqtt_ca.pem`
  （公网 CA 如 Let's Encrypt 的完整链：叶子+中间+根）。自签证书临时调试可设 `MQTT_TLS_VERIFY=False`；
  `/mqtt_ca.pem` 怎么配、要不要跟着证书更新，详见第 9 节。
- **账号密码走 base64**：broker 地址/用户名/密码可能与空格/中文/任意字节无关，但为与
  SSID 一致，`MQTT_SET` 一律 base64 传输；**用户名/密码可为空**（匿名 broker），
  板端解析允许缺省空参数。
- **灯珠控制协议**：板子订阅 `config.MQTT_LED_TOPIC`（默认 `esp32s3/led`），
  消息 `#RRGGBB` / `#RGB` 或 `r,g,b`（如 `255,0,0`、`128, 0, 255`）；
  当前颜色发布到 `esp32s3/led/state`（保留消息，新订阅者立即拿到当前色）；
  上线/离线发布 `esp32s3/status`（保留消息 + LWT）。
  MQTT 与网页设置的“用户色”同优先级，后设置者生效；BLE 断开只清 BLE 设的颜色，MQTT 色保留。

## 3. 先确定串口（编号会变，用 by-id）

```bash
ls -l /dev/serial/by-id/
```

## 4. 上传并运行（板子端）

```bash
# 注意：板上有看门狗 boot.py，mpremote cp 进 raw REPL 会软复位被挡（属预期）。
# 可靠姿势：pyserial 先 Ctrl-C 打断看门狗进 REPL，再手动进 raw REPL（Ctrl-A）用 base64 写入，
# 见 examples/03-ble-file-led/EXPERIMENT_03.md 3.7 节与例程 05 的 EXPERIMENT_05.md。
python3 -m mpremote connect <PORT> cp boot.py :
python3 -m mpremote connect <PORT> cp config.py :
python3 -m mpremote connect <PORT> cp main.py :
python3 -m mpremote connect <PORT> cp -r umqtt :        # 必须！板子没有内置 mqtt 模块
# 如需证书校验：把 CA 的 PEM 上传为 /mqtt_ca.pem（或用网页文件面板上传）
python3 -m mpremote connect <PORT> reset
```

`main.py` 是开机自启文件名，复位后自动运行。串口应打印：

```
ESP32-S3 例程 05：BLE 网页控制台 + WiFi + MQTT（WS2812 控制，密码保护已开启）
设备名: ESP32S3-MQTT  |  版本: 1.0  |  密码: 1234
MQTT 控制主题: esp32s3/led  （消息 #RRGGBB 或 r,g,b；TLS 端口 8883，账号密码认证）
MQTT 配置通过网页 BLE 面板保存（无默认值）；CA 证书文件: /mqtt_ca.pem
...
检测到已保存路由器配置: <SSID>
NTP 校时完成: ...          # 之后才会连 MQTT（TLS 校验需要正确时间）
MQTT 连接 <broker>:8883 ...
MQTT 已连接: <broker>:8883 | 订阅 esp32s3/led 控制灯珠
```

板载 WS2812 灯珠：广播中**暗绿**，路由器连上后**青色**；若之前保存过 MQTT 配置则继续连 broker。

## 5. 部署网页（需要 HTTPS）

`web/index.html` 是零依赖单文件，任选一种 HTTPS 托管（GitHub Pages / Netlify /
Cloudflare Pages），或本地 `python3 -m http.server 8000` 后用 `localhost` 访问。
⚠️ 浏览器要求：**Chrome / Edge**（桌面版或 Android）；iOS Safari 不支持 Web Bluetooth。

## 6. 引导用户测试

1. 板子上电（main.py 自动跑，灯珠暗绿 = 广播中）。
2. Chrome/Edge 打开部署好的页面 → 连接设备 → 选 `ESP32S3-MQTT` → 输密码（默认 `1234`）。
3. **WiFi 面板**：扫描路由器 → 点击结果填入 SSID → 填密码 → 连接 → 日志出现进度行与
   “已连接路由器，IP: …”，状态面板显示 STA 已连接，灯珠变**青色**；配置已存 `/wifi.json`，
   上电自动重连。
4. **MQTT 面板**：填 broker 地址（如 `mqtt.example.com`）、端口（默认 `8883`）、用户名、密码
   →「保存并连接」。若 `MQTT_TLS_VERIFY=True`：需先把服务器 CA 的 PEM 上传为 `/mqtt_ca.pem`
   （配置方法与 ZeroSSL/公网证书实战见第 9 节），否则 MQTT_STATUS 会显示证书校验错误。成功后状态面板
   `MQTT CONNECTED`，灯珠无变化（MQTT 只响应控制消息）。
5. **MQTT 控制灯珠**：任意 MQTT 客户端（MQTT Explorer / paho / 手机 App）连接同一 broker
   （TLS 8883 + 账号密码），向 `esp32s3/led` 发布：
   - `#ff0000` → 灯珠变红
   - `0, 255, 0` → 灯珠变绿
   - `#000000` → 熄灭
   - 非法内容（如 `bogus`）→ 被忽略，颜色不变
   订阅 `esp32s3/led/state` 可实时看到当前颜色（保留消息，新订阅立即拿到）。
6. 顺带验证（同例程 03）：文件列表/查看/下载/上传/删除、LED 选色即时变色。

## 7. 排错速查

| 现象 | 排查 |
|------|------|
| 页面提示「不支持 Web Bluetooth」 | 换 Chrome/Edge；确认 HTTPS 或 localhost |
| 搜不到设备 | 板子是否上电且 main.py 在跑（灯珠暗绿）；另一台设备连着时已停广播；距离太远 |
| 连接后提示输密码 / 密码错误 | 密码是 `config.py` 的 `BLE_PASSWORD`（默认 `1234`），连错 3 次自动断开 |
| 连不上路由器 | 看串口日志原因：`wrong password` / `network not found` / `handshake timeout` |
| MQTT 状态显示「等待 NTP 校时」 | 路由器没外网（NTP 走 UDP 123）；或刚开机正在校时，稍等 30 秒内自动重试 |
| MQTT 连接失败：证书时间错误 | 板子 RTC 无电池，等 NTP 校时完成（看串口 `NTP 校时完成`）；校时失败查路由器外网 |
| MQTT 连接失败：证书校验失败 | 本固件无内置 CA：上传服务器 CA 链到 `/mqtt_ca.pem`（网页文件面板即可，方法与验证见第 9 节）；或临时设 `MQTT_TLS_VERIFY=False` |
| 面板显示 CONNECTED，但 broker 上没板子 | 状态是旧的：板子已掉线（WiFi 断 / broker 重启 / 掉电）。用 `test/test_mqtt_broker_probe.py` 连 broker 确认在线数与 `esp32s3/#` 保留消息；板子断线后 10 秒自动重连，查串口日志当前 MQTT 状态与错误 |
| MQTT 连接失败：`not authorized` / 无权限 | broker 用户名/密码错（Mosquitto `allow_anonymous false`） |
| MQTT 连上但灯不亮 | 主题是否一致（默认 `esp32s3/led`，可在 config.py 改）；消息格式 `#RRGGBB` 或 `r,g,b`；订阅的是否是同一 broker 的同一 topic |
| 重启后不自动连 MQTT | 确认保存过配置（`/mqtt.json` 有 `mqtt` 键）；WiFi 要先通（`/wifi.json` 有 `sta`）；`MQTT_RETRY_INTERVAL` 默认 10 秒，稍等 |
| `MQTT_STATUS` 显示最近错误 | 网页 MQTT 面板底部会显示 `MQTT_ERR`（base64 解码后的文字） |
| REPL 连不上（mpremote exec 报错） | 看门狗 + 主循环占着主线程，属正常；Ctrl-C 打断或用复位 |
| 想恢复例程 04 | 重新上传 `examples/04-wifi-ble-console/` 的 boot/config/main 三个 py |
| `/wifi.json` / `/mqtt.json` 里有明文密码 | 是（Flash 明文保存），BLE 空口也是明文；只防误连不防嗅探，别存重要密码 |

## 8. 已踩过的坑（实现时别重犯）

1. **本固件无内置 `mqtt` 模块**：v1.29.0 `import mqtt` 报 `ImportError`，必须随代码上传
   `umqtt/`（micropython-lib 的 `umqtt.simple`，2024 版 API：`MQTTClient(client_id, server,
   port, user, password, keepalive, ssl=SSLContext)`）。
2. **TLS 证书校验需要正确系统时间**：RTC 无电池上电停在 2000 年，mbedTLS 报
   “The certificate validity starts in the future”。必须先 NTP 校时；`MQTT_TLS_VERIFY=True`
   且时钟未校准时**不要**发起连接（白费 TLS 握手），状态提示“等待 NTP 校时”。
3. **本固件无内置 CA 证书库**：固件二进制里只有格式串（`-----BEGIN CERTIFICATE-----` 出现 1 次），
   无根证书。校验必须 `load_verify_locations(cadata=CA链)`。
4. **`MQTT_SET` 空用户名/密码会折叠**：`rest.strip()` 后 `split(" ")` 只剩 2 段 → 老代码判
   `len<4` 直接拒绝匿名 broker。修复：只要求前两段（host/port），user/pass 用
   `len(parts) > i and parts[i].strip()` 判空，缺省为空字符串。
5. **CPython/MicroPython `time.localtime()` 元组长度不同**（9 vs 8）：解包会抛 ValueError，
   被 except 吞掉 → 时钟判定永远 False → MQTT 永远不连。用 `time.localtime()[0]` 取下标。
6. **umqtt `check_msg` 的 socket 非阻塞语义**：TLS 下无数据时可能返回 None 或抛
   `OSError(EAGAIN/ETIMEDOUT)`，代码对 errno 11/116 放行，其余视为断线重连。
7. **`import main` 拿的是内存里旧模块**：上传新 main.py 后 REPL 里直接 `import main`
   仍是旧代码，必须 `sys.modules.pop('main', None)` 再 import（或软复位让看门狗重载）。
8. **mpremote cp 会被看门狗挡住**：软复位后 main.py 立刻占住 REPL。可靠上传：
   pyserial Ctrl-C 打断 → Ctrl-A 进 raw REPL → base64 分块写文件（见 EXPERIMENT_05 记录）。
9. **复用 03/04 的坑**：GATT 服务一次注册、`bytearray` 无 del/clear、IRQ 只做轻量工作
   （LED 用户色只置脏标记，颜色发布放到主循环 `apply_led` 里做，避免 IRQ 里做 TLS 网络 IO）、
   每条命令响应以 `DONE` 收尾、断开时 reject 挂起请求——本目录 main.py 已全部遵守。

## 9. CA 证书配置详解（/mqtt_ca.pem 的来龙去脉）

`/mqtt_ca.pem` **不是固件自带的**：本固件无内置根证书库（见第 2 节与第 8 节第 3 条），
需要把服务器 CA 链的 PEM **手动上传**到板子 Flash 根目录（网页 BLE 文件面板「上传文件到板子」，
或 `mpremote cp`）。`MQTT_TLS_VERIFY=True` 时每次 TLS 连接都用 `load_verify_locations(cadata=...)` 读它。

### 9.1 用正经 CA（ZeroSSL / Let's Encrypt 等）签的证书

证书链 = 叶子 + 中间 + 根，客户端校验实际用到的只有**中间 + 根**（叶子是服务器握手时现发的）。
以本仓库实测（2026-09-01，`openssl s_client -showcerts` 抓 `cdn-g.limour.top:8883`）的 ZeroSSL 链为例：

```
CN=*.limour.top                                   ← 叶子（服务器握手现发）
  └─ ZeroSSL ECC DV SSL CA 2                     ← 中间（ZeroSSL 自有中间，不是 Sectigo 老中间）
       └─ Sectigo Public Server Authentication Root E46   ← 根（被 USERTrust ECC Certification Authority 交叉签名）
```

- **ZeroSSL 现在用自有中间证书**：ECC 证书 → `ZeroSSL ECC DV SSL CA 2`，RSA 证书 → `ZeroSSL RSA DV SSL CA 2`；
  根是 Sectigo 的 `Sectigo Public Server Authentication Root E46`（又被 USERTrust ECC 交叉签名，任选其一作锚点都行）。

**最简单：把 `fullchain.pem`（或 ZeroSSL 下载包里的 `ca_bundle.crt`）整个传为 `/mqtt_ca.pem` 即可**，
文件里多余的证书（含叶子）校验时自动忽略，不用裁剪。

**叶子证书经常续期/更换不影响 `/mqtt_ca.pem`**：服务器每次握手现发叶子 + 中间，板子只存中间 + 根；
只要新叶子还是同一张中间签的，链就照常通过——续期 N 次都不用重传。
只有三种情况才需要更新：**换 CA 供应商**、**中间证书轮换**（CA 弃用旧中间签发新中间）、**根证书过期**
（根有效期一般十年以上，基本不用管；具体以 9.4 验证命令实测为准）。

### 9.2 只想传根证书

可以，前提：**broker 必须把中间证书随握手一起下发**（Mosquitto / EMQX 等标准 broker 默认都会）。
那样链是 `叶子(服务器发) → 中间(服务器发) → 根(板子存)`，只存根即可通过。
若 broker 配得简陋只发叶子不发中间，则必须把中间也放进 `/mqtt_ca.pem`（传整个 bundle 最稳）。

从 `ca_bundle.crt` 里提取根（subject == issuer 的自签名那张）：

```bash
csplit -f ca_ -b '%d.pem' ca_bundle.crt '/-----BEGIN CERTIFICATE-----/' '{*}'
rm -f ca_0.pem
for f in ca_*.pem; do echo "== $f =="; openssl x509 -in "$f" -noout -subject -issuer; done
```

RSA / ECC 证书的中间/根不同（ZeroSSL：ECC 中间 `ZeroSSL ECC DV SSL CA 2` / RSA 中间 `ZeroSSL RSA DV SSL CA 2`，根都是 Sectigo E46 系），选错会报 unknown CA；以 9.3 抓到的实际链为准。

### 9.3 从 broker 现抓链（不挑 CA，保证顺序）

```bash
echo | openssl s_client -connect <broker域名>:8883 -showcerts 2>/dev/null \
  | awk '/-----BEGIN CERTIFICATE-----/{f=1} f' > ca_bundle.pem
```

### 9.4 传之前先验证（30 秒）

```bash
openssl s_client -connect <broker域名>:8883 \
  -CAfile /path/to/mqtt_ca.pem -verify_return_error </dev/null 2>&1 | grep "Verify return code"
```

`Verify return code: 0 (ok)` → 上传必通。

> 别用 `MQTT_TLS_VERIFY=False` 图省事：TLS 校验的意义就在于防中间人冒充 broker，
> 关掉后 MQTT 账号密码等于裸奔。CA 链几年才动一次，维护成本很低。
