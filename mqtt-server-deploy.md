# MQTT Broker (Eclipse Mosquitto) Docker 自部署指南

> 目标：在一台 Linux 服务器上用 Docker Compose 部署带 **TLS 加密 + 用户名密码认证** 的 Mosquitto MQTT Broker，支持自动证书续期，并给出 ESP32 类设备的连接示例。
> 本文档是自包含的：任何具备 shell/Docker 基础的新手或全新 AI agent 按步骤执行即可完成部署。

---

## 0. 部署架构

```
                    ┌─────────────────────────────────────────────┐
  ESP32 / PC 客户端 ──TLS(8883)──▶  mosquitto 容器 (@Linux 服务器) │
  Web 客户端       ──WSS(8084)──▶                                │
                    └─────────────────────────────────────────────┘
```

- **端口**：`8883` = MQTT over TLS（主用）；`8084` = WebSocket over TLS（浏览器/网页端用）
- **认证**：用户名 + 密码（`allow_anonymous false`）
- **证书**：由外部机制（如 GCP Workload Certificate、acme.sh、certbot）自动更新到"源证书目录"，本方案用**每日定时脚本**把证书复制为 broker 可读的低权限副本，并通过 SIGHUP 让 mosquitto 热重载
- **持久化**：会话、保留消息落盘到 `data/`

---

## 1. 前置条件

| 项 | 要求 |
|---|---|
| 服务器 | Linux (Debian/Ubuntu 均可)，已安装 Docker + Docker Compose |
| 域名 | 一个域名（如 `mqtt.example.com`），A 记录解析到服务器公网 IP |
| 证书 | 该域名的 TLS 证书（`.crt/.pem` + `.key`），建议通配符证书；**证书链需完整**（叶子+中间+根，`grep -c 'BEGIN CERTIFICATE' cert.pem` 应 ≥ 2） |
| 证书更新 | 证书文件由脚本/系统服务自动刷新（下文称"源证书目录"，文件权限为 `root:600` 也无妨） |
| 防火墙 | 放行入站 TCP `8883`（和 `8084`，如需要 WSS） |

> 无域名/证书时的临时方案：`openssl req -x509 ...` 自签一张证书；客户端需把该证书作为 CA 传入（见 7.2 节）。
> 无域名/证书时的临时方案：`openssl req -x509 ...` 自签一张证书；客户端需把该证书作为 CA 传入（见第 6 节 MicroPython 示例）。
---

## 2. 目录规划

```
~/app/quic/        # 源证书目录：证书由外部机制自动更新（如 my.cert / my.key）
~/app/mqtt/        # 本部署目录
├── docker-compose.yml
├── sync-certs.sh          # 每日证书同步脚本
├── config/mosquitto.conf  # broker 配置
├── config/passwd          # 用户密码文件（mosquitto_passwd 生成）
├── certs/cert.pem         # 证书低权限副本（自动同步生成）
├── certs/key.pem          # 私钥低权限副本（自动同步生成）
├── data/                  # 持久化数据（属主 UID 1883）
└── log/                   # 日志（属主 UID 1883）
```

> 路径 `~/app` 仅为示例，可换任意路径，但 compose 中相对路径以 compose 文件所在目录为基准。

---

## 3. 创建目录与配置文件

```bash
mkdir -p ~/app/mqtt/config ~/app/mqtt/data ~/app/mqtt/log ~/app/mqtt/certs
# 关键：data/log 目录必须让容器内 mosquitto 用户(UID 1883)可写，否则持久化会失败
chown -R 1883:1883 ~/app/mqtt/data ~/app/mqtt/log
```

### 3.1 `~/app/mqtt/docker-compose.yml`

```yaml
services:
  mosquitto:
    image: eclipse-mosquitto:2
    container_name: mosquitto
    restart: always
    ports:
      - '8883:8883'   # MQTTS (MQTT over TLS)
      - '8084:8084'   # WSS  (WebSocket over TLS)
    volumes:
      - ./config:/mosquitto/config
      - ./data:/mosquitto/data
      - ./log:/mosquitto/log
      - ./certs/cert.pem:/mosquitto/certs/cert.pem   # 低权限副本，由 sync-certs.sh 维护
      - ./certs/key.pem:/mosquitto/certs/key.pem
```

### 3.2 `~/app/mqtt/config/mosquitto.conf`

```conf
# ===== 监听器 =====
# 如需明文 MQTT(仅建议内网调试)取消注释，并在 compose 中映射 1883:
# listener 1883 0.0.0.0

# MQTTS: MQTT over TLS (公网主入口)
listener 8883 0.0.0.0
certfile /mosquitto/certs/cert.pem
keyfile /mosquitto/certs/key.pem

# WSS: WebSocket over TLS
listener 8084 0.0.0.0
protocol websockets
certfile /mosquitto/certs/cert.pem
keyfile /mosquitto/certs/key.pem

# ===== 安全 =====
allow_anonymous false
password_file /mosquitto/config/passwd

# ===== 持久化 =====
persistence true
persistence_location /mosquitto/data/

# ===== 日志 =====
log_dest stdout
log_type error
log_type warning
log_type notice
log_type information
```

### 3.3 生成密码文件

```bash
cd ~/app/mqtt
# 先生成随机密码，再写进密码文件
MQTT_PASS=$(openssl rand -base64 18 | tr -d '/+=' | head -c 16)
echo "你的 MQTT 密码: $MQTT_PASS"   # 记下来
docker run --rm --entrypoint mosquitto_passwd \
  -v "$(pwd)/config:/config" eclipse-mosquitto:2 \
  -c -b /config/passwd <你的用户名> "$MQTT_PASS"

# 关键：passwd 属主必须改为 mosquitto 用户，否则容器内读不到 → 启动即崩溃
chown 1883:1883 ~/app/mqtt/config/passwd
```

> 之后添加用户：去掉 `-c` 参数再次执行 `mosquitto_passwd`。
> 修改密码：`docker compose exec mosquitto mosquitto_passwd /mosquitto/config/passwd <用户名>`

---

## 4. 证书同步方案

背景：源证书由外部机制自动刷新（通常写为 `root:600`，容器内 mosquitto 用户 UID 1883 读不了）。解决方案是**每日把证书复制成低权限副本**，再让 mosquitto 通过 SIGHUP 热重载，无需重启容器。

### 4.1 `~/app/mqtt/sync-certs.sh`

```bash
#!/bin/bash
# 把源证书目录的证书同步为 mqtt/certs 低权限副本，并通知 mosquitto 重载(SIGHUP)
# 由 cron 每日调用；证书未变化时自动跳过
set -euo pipefail

SRC_CERT=/root/app/quic/my.cert          # ← 改成你的源证书路径(证书)
SRC_KEY=/root/app/quic/my.key            # ← 改成你的源证书路径(私钥)
DST_DIR=/root/app/mqtt/certs
DST_CERT="$DST_DIR/cert.pem"
DST_KEY="$DST_DIR/key.pem"

mkdir -p "$DST_DIR"

# 源证书未变化则跳过
if [ -f "$DST_CERT" ] && [ -f "$DST_KEY" ] \
   && [ "$SRC_CERT" -ot "$DST_CERT" ] && [ "$SRC_KEY" -ot "$DST_KEY" ]; then
    exit 0
fi

# install 设置属主(1883=mosquitto)与权限: cert 644, key 600
install -m 644 -o 1883 -g 1883 "$SRC_CERT" "$DST_CERT"
install -m 600 -o 1883 -g 1883 "$SRC_KEY" "$DST_KEY"
echo "$(date '+%F %T') cert synced"

# mosquitto 运行中则发 SIGHUP 热重载 TLS 证书
if docker inspect -f '{{.State.Running}}' mosquitto 2>/dev/null | grep -q '^true$'; then
    docker kill --signal=HUP mosquitto >/dev/null 2>&1 && echo "$(date '+%F %T') HUP sent"
fi
```

### 4.2 安装脚本 + 定时任务（每日一次）

```bash
chmod +x ~/app/mqtt/sync-certs.sh
~/app/mqtt/sync-certs.sh                     # 首次手动执行，生成低权限副本
ls -la ~/app/mqtt/certs/                     # 确认 cert.pem 644 / key.pem 600，属主 1883

# cron 每天 03:00 同步（频率可按证书更新周期调整）
(crontab -l 2>/dev/null; echo '0 3 * * * /root/app/mqtt/sync-certs.sh >> /var/log/mqtt-cert-sync.log 2>&1') | crontab -
crontab -l
```

> 为什么不是直接 bind mount 源证书？因为源证书被外部机制刷新时会重置为 `root:600`，mosquitto 用户读不到，且 `:ro` 挂载后容器内也无法 chown（会报 `Read-only file system`）。副本方案最稳。
> SIGHUP 即可热重载证书（mosquitto 2.x 支持），无需 `docker compose restart`。

---

## 5. 启动与健康检查

```bash
cd ~/app/mqtt
docker compose up -d
sleep 5
docker compose ps          # 期望 STATUS = Up，不要出现 Restarting
docker compose logs --tail 20   # 期望最后一行 "mosquitto version 2.1.2 running"
```

### 5.1 验证 TLS 握手（服务器本机）

```bash
echo | timeout 10 openssl s_client -connect 127.0.0.1:8883 -servername <你的域名> 2>&1 \
  | grep -E 'CONNECTED|subject=|issuer=|Verify return'
# 期望: Verify return code: 0 (ok)
```

### 5.2 验证公网连通（本地机器执行）

```bash
echo | timeout 10 openssl s_client -connect <你的域名>:8883 -servername <你的域名> 2>&1 \
  | grep -E 'CONNECTED|Verify return'
# 如果卡在 "Connecting to <IP>" 无响应 → 检查云厂商防火墙是否放行 8883
```

### 5.3 端到端测试（paho-mqtt，任意有 Python 的机器）

```bash
pip install paho-mqtt
```

```python
# mqtt_test.py  — 把 <域名>/<用户名>/<密码> 替换成你的
import ssl, time, paho.mqtt.client as mqtt

HOST, PORT, USER, PASS = "<你的域名>", 8883, "<用户名>", "<密码>"
got = []

def on_connect(c, u, f, rc, p=None):
    print(f"connect rc={rc} ({mqtt.connack_string(rc)})")
    if rc == 0:
        c.subscribe("test/topic", qos=1)

def on_subscribe(c, u, mid, rc, p=None):
    print("subscribed, publishing...")
    c.publish("test/topic", "hello mqtt tls!", qos=1)

def on_message(c, u, m):
    got.append(m.payload.decode()); print("received:", m.payload.decode()); c.disconnect()

ctx = ssl.create_default_context()   # 公网 CA 签发的证书直接用系统 CA 校验
c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
c.tls_set_context(ctx)
c.username_pw_set(USER, PASS)
c.on_connect, c.on_subscribe, c.on_message = on_connect, on_subscribe, on_message
c.connect(HOST, PORT, keepalive=30)
c.loop_start(); time.sleep(5); c.loop_stop()
print("PASS" if got else "FAIL")
```

> 注意：必须在 **on_subscribe 回调之后**再 publish，否则消息会因订阅未建立而丢失。

### 5.4 GUI 客户端连接（MQTT Explorer，Windows/macOS/Linux）

下载：https://mqtt-explorer.com/ （免费版仅支持 MQTT 3.1.1，Mosquitto 2.x 兼容，无碍）

点击左上角 **Add new connection**，按如下填写：

| 字段 | 值 |
|---|---|
| Name | 随意，如 `my-mqtt` |
| Host | `<你的域名>` |
| Port | `8883` ⚠️ 不是默认的 1883 |
| Username | `<用户名>` |
| Password | `<密码>` |

**TLS 开关位置**：在 **Name 输入框旁边**的加密选择处（下拉/按钮），选择 **SSL/TLS** —— 它不在 Advanced 折叠区里。

- CA 文件、客户端证书等选项**全部留空**：公网 CA（ZeroSSL/Let's Encrypt）签发的证书由 MQTT Explorer 内置系统 CA 自动校验
- 连接成功后：Topics 面板右键 **Add Topic** 输入 `test/#` 即可订阅实时消息；左上角 **Publish** 按钮可手动发消息测试
- 报错排查：`Connection lost/timeout` → 检查云防火墙是否放行 8883；`not authorized` → 账号密码错误
---

## 6. ESP32 / 单片机 MicroPython 客户端示例

```python
import network, ssl, mqtt, time

# ---- WiFi ----
wlan = network.WLAN(network.STA_IF)
wlan.active(True)
wlan.connect("<WiFi名>", "<WiFi密码>")
while not wlan.isconnected():
    time.sleep(0.5)

# ---- MQTT over TLS ----
context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
# 公网 CA(如 ZeroSSL/Let's Encrypt)签发的证书: 可尝试不传 cadata, 用固件内置 CA 校验;
# 若报错或使用自签证书: 把服务器证书(或自建 CA)的 PEM 文本填入:
# context.load_verify_locations(cadata=b"-----BEGIN CERTIFICATE-----\n...\n-----END CERTIFICATE-----")

client = mqtt.MQTTClient(
    host="<你的域名>",      # server_hostname 必须与证书 CN/SAN 匹配! 自签证书为 IP 时用 IP 连接
    port=8883,
    username="<用户名>",
    password="<密码>",
    ssl_context=context,
)
client.connect()
client.subscribe("test/topic")

def cb(topic, msg):
    print(topic, msg)
client.set_callback(cb)
client.publish("test/topic", "hello from esp32")

while True:
    client.check_msg()
    time.sleep(1)
```

> MicroPython 老库 `umqtt.simple` 对应写法：`MQTTClient(..., ssl=True, ssl_params={"server_hostname": "<域名>", "cert_reqs": ssl.CERT_REQUIRED, "cadata": ca_pem_bytes})`。`cadata` 必须是 `bytes`。
> TLS 握手较耗内存/时间(1~3 秒)，`keepalive` 必须 > 0。

---

## 7. 常见坑清单（本方案实测踩过）

| # | 现象 | 原因 | 解决 |
|---|---|---|---|
| 1 | 容器反复 `Restarting`，日志 `password-file: Error: Unable to open pwfile` | passwd 文件属主 root:600，mosquitto 用户(UID 1883)读不到 | `chown 1883:1883 config/passwd` |
| 2 | 日志 `Error: Unable to load server key file ... Permission denied` | 私钥属主 root:600 | 用证书副本方案（第 4 节），副本属主 1883:1883、权限 600 |
| 3 | 容器内 chown 报 `Read-only file system` | 证书卷挂了 `:ro` | 副本方案不需要挂源证书，天然规避 |
| 4 | 自定义 entrypoint 报 `exec: illegal option -c` | 自定义 entrypoint 与镜像 `/docker-entrypoint.sh` 的 `exec "$@"` 冲突 | 不要覆盖 entrypoint，用默认的（副本方案后已无需自定义） |
| 5 | 客户端连不上，提示无权限 | mosquitto 2.x 默认**没有** listener，必须显式配置 `listener 8883` + 认证 | 见 mosquitto.conf |
| 6 | 公网连不上，`openssl s_client` 卡在 Connecting | 云厂商防火墙未放行端口 | 控制台放行 TCP 8883/8084 |
| 7 | 测试脚本 publish 后收不到消息 | 订阅尚未建立就发布 | 在 `on_subscribe` 回调里 publish |
| 8 | TLS 报 hostname mismatch | `server_hostname`/连接域名与证书 CN/SAN 不一致 | 用证书上的域名连接，或自签证书时 IP 直连 |
| 9 | compose 启动时警告 `version is obsolete` | compose 新版忽略 `version:` 字段 | 删掉 `version: '3.9'` 行即可 |
| 10 | 证书续期后 broker 仍用旧证书 | mosquitto 启动时才读证书 | 发 SIGHUP 热重载：`docker kill --signal=HUP mosquitto`（脚本已内置） |
| 11 | 挂载的 data/log 目录写入失败 | 目录属主 root，容器内 UID 1883 无写权限 | `chown -R 1883:1883 data log` |

---

## 8. 日常运维

```bash
cd ~/app/mqtt
docker compose ps                          # 状态
docker compose logs -f --tail 50           # 实时日志
docker compose exec mosquitto mosquitto_passwd /mosquitto/config/passwd <用户名>   # 改密码
docker kill --signal=HUP mosquitto         # 手动热重载证书（无需重启）
docker compose restart                     # 重启
```

- **数据备份**：`~/app/mqtt/data/` 下的 `mosquitto.db` 为会话/保留消息数据，`~/app/mqtt/config/passwd` 为账号数据
- **安全建议**：公网部署务必开启 TLS + 密码认证（本方案默认）；如需内网明文调试，单独加 1883 listener 并限制来源

---

## 9. 快速部署速查（全程命令）

```bash
# 1) 目录与权限
mkdir -p ~/app/mqtt/{config,data,log,certs} && chown -R 1883:1883 ~/app/mqtt/{data,log}

# 2) 写入 docker-compose.yml / config/mosquitto.conf / sync-certs.sh（见上文），
#    并把 sync-certs.sh 中的源证书路径改为你的实际路径

# 3) 生成密码
docker run --rm --entrypoint mosquitto_passwd -v ~/app/mqtt/config:/config \
  eclipse-mosquitto:2 -c -b /config/passwd <用户名> <密码>
chown 1883:1883 ~/app/mqtt/config/passwd

# 4) 首次同步证书 + 定时任务
chmod +x ~/app/mqtt/sync-certs.sh && ~/app/mqtt/sync-certs.sh
(crontab -l 2>/dev/null; echo '0 3 * * * /root/app/mqtt/sync-certs.sh >> /var/log/mqtt-cert-sync.log 2>&1') | crontab -

# 5) 启动并验证
cd ~/app/mqtt && docker compose up -d && docker compose ps
echo | openssl s_client -connect <域名>:8883 -servername <域名> 2>&1 | grep 'Verify return'
```
