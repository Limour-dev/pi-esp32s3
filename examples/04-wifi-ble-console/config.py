# config.py —— 例程 04：BLE 网页控制台 + WiFi 配置 配置
#
# 改这里的值即可自定义设备名/UUID/灯珠参数/热点/连接参数，改完重新上传并复位板子。
# 注意：如果改了 UUID 或设备名，web/index.html 里对应的常量也要同步改。
#
# WiFi 连接配置（连哪个路由器、热点叫什么）**不在本文件里**：
# 通过网页（BLE）的「WiFi 设置」面板操作，会保存到板子 Flash 的 /wifi.json，
# 上电自动按保存的配置连接路由器。

# ---- BLE 设备名（网页搜索时按此前缀过滤）----
DEVICE_NAME = "ESP32S3-WIFI"

# ---- 状态灯（WS2812），例程 01 探测确认：灯珠接 GPIO48 ----
WS2812_PIN = 48
WS2812_NUM = 1

# ---- GATT 服务/特征 UUID（128 位，避免与标准服务冲突）----
# LED 服务：网页写 3 字节 RGB 控制灯珠
LED_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
LED_CHAR_UUID    = "0000fff1-0000-1000-8000-00805f9b34fb"
# 文件服务：CMD 写入命令，DATA 以 notify 返回响应（WiFi 命令也走这条通道）
FILE_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CMD_CHAR_UUID     = "0000ffe1-0000-1000-8000-00805f9b34fb"
DATA_CHAR_UUID    = "0000ffe2-0000-1000-8000-00805f9b34fb"

# ---- 蓝牙密码（应用层认证）----
# 连接后必须先发 AUTH <password> 才能使用文件/LED/WiFi 服务。
# 注意：BLE 无配对时通道不加密，密码是明文传输，
#       这层认证只防误连/普通围观，防不了嗅探重放。
BLE_PASSWORD = "1234"

# ---- 协议参数 ----
CHUNK_SIZE = 180        # 每条 notify 响应行的最大字节数（含前缀）

# ---- 回退热点（配置入口）----
# 热点**永远开着**：连不上路由器、或想换个环境时，热点始终可用。
# 注意：本固件无 NAT，热点下的设备只能访问 ESP32 自身服务，
#       不能转发路由器的网络（见 AGENT_GUIDE / EXPERIMENT 记录）。
AP_SSID = "ESP32S3-AP"          # 默认热点名（可通过网页 WiFi 面板修改，保存在 /wifi.json）
AP_PASSWORD = "12345678"        # 热点密码（WPA2 要求至少 8 位；空字符串 "" = 开放网络）
AP_MAX_CLIENTS = 4              # 热点允许同时连接的设备数量
AP_CHANNEL = 1                  # 初始信道 1~13；STA 连上路由器后 AP 自动跟随路由器信道

# ---- WiFi 连接参数 ----
STA_CONNECT_TIMEOUT = 20        # 连接路由器的最长等待秒数（网页连接/开机自连均适用）
STA_RETRY_INTERVAL = 30         # 开机后若保存过路由器配置且未连上，每隔多少秒重试一次
WIFI_CFG_FILE = "/wifi.json"    # 保存路由器/热点配置的文件（板子 Flash 根目录）
