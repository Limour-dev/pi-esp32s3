# 测试（WiFi + MQTT 配置 / BLE 网页控制台 / WS2812 控制）

两个测试都不需要真硬件，在宿主机器上即可跑。

| 文件 | 测什么 | 怎么跑 |
|------|--------|--------|
| `test_mqtt_board.py` | 板端 `main.py` 的 WiFi+MQTT 逻辑：认证门禁、WiFi 扫描/连接/断开/忘记/状态（**无 AP 行**）、MQTT_SET/MQTT_FORGET/MQTT_STATUS、MQTT 连接状态机（WiFi 就绪才连、TLS 上下文 + CA 加载、订阅灯珠主题、收消息控灯（`#RRGGBB` / `r,g,b` / 非法负载忽略 / 非灯珠主题忽略）、状态与上线发布、check_msg 断线检测、自动重连、连接失败错误记录、配置读回与持久化、BLE 断开只清 BLE 色。mock BLE/network/ssl/umqtt/硬件模块，走 `_drain_cmds` 真实接收路径 | `python3 test/test_mqtt_board.py` |
| `test_mqtt_web.mjs` | 网页端 `web/index.html` 的真实 JS：连接认证 → 自动刷 WiFi/MQTT 状态、WiFi 扫描列表渲染/点击填入/连接成功（含进度行）与失败/状态刷新/断开/忘记、MQTT 保存配置（含 host/port 校验）/状态刷新/忘记配置、WiFi 面板**不再显示热点**。Node `vm` + 假 BLE 设备（行为对齐 `main.py`），无需浏览器 | `node test/test_mqtt_web.mjs` |

## 前提

- `test_mqtt_board.py`：Python 3（宿主机），`main.py` 在上一级目录。`config.py` 会被真实加载（sys.path 指向例程根），测试只把 `WIFI_CFG_FILE`/`MQTT_CA_CERT_FILE` 指向临时文件、缩短 `STA_CONNECT_TIMEOUT`、`MQTT_RETRY_INTERVAL=0`（断线立即重试）。
- `test_mqtt_web.mjs`：Node 18+（用 `import.meta.url` 定位 `web/index.html`），无需任何 npm 依赖。

## 说明

- 假设备中的密码 `1234`、设备名 `ESP32S3-MQTT`、MQTT broker `mqtt.example.com:8883`（用户 `testuser`）、灯珠主题 `esp32s3/led` 与 `config.py` 默认值一致；改配置后需同步改测试里的 `PWD` / 假设备响应。
- SSID/密码/host/账号一律 base64：板端 `ubinascii`、网页端 `btoa/atob`、测试端 `Buffer`，三端编码一致。
- 测试覆盖「连接失败不改已保存配置」「MQTT 只有 WiFi 就绪才连接」「非法灯珠消息被忽略」等行为约定。
