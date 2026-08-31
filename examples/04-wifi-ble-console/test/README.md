# 测试（WiFi 配置 / BLE 网页控制台）

两个测试都不需要真硬件，在宿主机器上即可跑。

| 文件 | 测什么 | 怎么跑 |
|------|--------|--------|
| `test_wifi_board.py` | 板端 `main.py` 的 WiFi 逻辑：认证门禁、扫描（含中文 SSID）、连接成功/错密码/找不到网络、`/wifi.json` 持久化、断开保留配置、忘记配置、热点重配、配置读回、自动重连。mock BLE/network/硬件模块，走 `_drain_cmds` 真实接收路径 | `python3 test/test_wifi_board.py` |
| `test_wifi_web.mjs` | 网页端 `web/index.html` 的真实 JS：连接认证 → 自动刷状态、扫描列表渲染（信号/认证类型）、点击列表项填入 SSID、连接成功（含进度行）与失败、手动刷新状态、断开、忘记、热点重配。Node `vm` + 假 BLE 设备（行为对齐 `main.py`），无需浏览器 | `node test/test_wifi_web.mjs` |

## 前提

- `test_wifi_board.py`：Python 3（宿主机），`main.py` 在上一级目录。`config.py` 会被真实加载（sys.path 指向例程根），测试只把 `WIFI_CFG_FILE` 指向临时文件、缩短 `STA_CONNECT_TIMEOUT`。
- `test_wifi_web.mjs`：Node 18+（用 `import.meta.url` 定位 `web/index.html`），无需任何 npm 依赖。

## 说明

- 假设备中的密码 `1234`、设备名 `ESP32S3-WIFI`、热点 `ESP32S3-AP` 与 `config.py` 默认值一致；改配置后需同步改测试里的 `PWD` / 假设备响应。
- SSID/密码走 base64：板端 `ubinascii`、网页端 `btoa/atob`、测试端 `Buffer`，三端编码一致。
- 测试覆盖了「连接失败不改已保存配置」这一行为：`WIFI_CONNECT` 失败只回 `ERR`，不触碰 `saved_sta`（只有成功才保存，`WIFI_FORGET` 才清除）。
