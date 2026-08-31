# config.py —— 例程 05：BLE 网页控制台 + WiFi + MQTT（WS2812 控制）配置
#
# 改这里的值即可自定义设备名/UUID/灯珠参数/MQTT 主题/连接参数，改完重新上传并复位板子。
# 注意：如果改了 UUID 或设备名，web/index.html 里对应的常量也要同步改。
#
# WiFi 与 MQTT 的**连接配置不在这里**：
# 通过网页（BLE）的「WiFi 设置」/「MQTT 配置」面板操作：
# 路由器配置保存到板子 Flash 的 /wifi.json（sta），MQTT 配置保存到 /mqtt.json（mqtt），
# 上电自动按保存的配置连路由器、再连 MQTT broker。

# ---- BLE 设备名（网页搜索时按此前缀过滤）----
DEVICE_NAME = "ESP32S3-MQTT"

# ---- 状态灯（WS2812），例程 01 探测确认：灯珠接 GPIO48 ----
WS2812_PIN = 48
WS2812_NUM = 1

# ---- GATT 服务/特征 UUID（128 位，避免与标准服务冲突）----
# LED 服务：网页写 3 字节 RGB 控制灯珠
LED_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
LED_CHAR_UUID    = "0000fff1-0000-1000-8000-00805f9b34fb"
# 文件服务：CMD 写入命令，DATA 以 notify 返回响应（WiFi/MQTT 命令也走这条通道）
FILE_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CMD_CHAR_UUID     = "0000ffe1-0000-1000-8000-00805f9b34fb"
DATA_CHAR_UUID    = "0000ffe2-0000-1000-8000-00805f9b34fb"

# ---- 蓝牙密码（应用层认证）----
# 连接后必须先发 AUTH <password> 才能使用文件/LED/WiFi/MQTT 服务。
# 注意：BLE 无配对时通道不加密，密码是明文传输，
#       这层认证只防误连/普通围观，防不了嗅探重放。
BLE_PASSWORD = "1234"

# ---- 协议参数 ----
CHUNK_SIZE = 180        # 每条 notify 响应行的最大字节数（含前缀）

# ---- WiFi 连接参数（STA 连路由器；无回退热点）----
STA_CONNECT_TIMEOUT = 20        # 连接路由器的最长等待秒数（网页连接/开机自连均适用）
STA_RETRY_INTERVAL = 30         # 开机后若保存过路由器配置且未连上，每隔多少秒重试一次
WIFI_CFG_FILE = "/wifi.json"    # 保存路由器配置的文件（板子 Flash 根目录）
                                # 内容: {"sta": {...}}（明文，勿存重要密码）
MQTT_CFG_FILE = "/mqtt.json"    # 保存 MQTT 配置的文件（与 WiFi 分开，互不影响）
                                # 内容: {"mqtt": {"host","port","user","password"}}（明文）

# ---- NTP 校时参数（TLS 证书校验依赖正确系统时间）----
NTP_HOST = "ntp.aliyun.com"   # NTP 服务器（阿里云；也可换 ntp.tencent.com / pool.ntp.org）
NTP_TIMEOUT = 8              # 单次校时超时秒数

# ---- MQTT 参数（broker 地址/端口/账号/密码经网页 BLE 面板配置，保存在 /mqtt.json 的 "mqtt" 键）----
MQTT_PORT = 8883                # TLS 端口（默认，网页面板可改）
MQTT_TLS_VERIFY = True          # 校验服务器证书。True 时把服务器 CA 的 PEM 上传为 MQTT_CA_CERT_FILE；
                                # 自签证书临时调试可设 False（不校验，有中间人风险）
MQTT_CA_CERT_FILE = "/mqtt_ca.pem"  # 服务器 CA 证书文件（公网 CA 或自签 CA，PEM 文本）
MQTT_CLIENT_ID = "esp32s3-mqtt"     # 默认客户端 ID；实际用 STA MAC 尾部生成唯一后缀
MQTT_LED_TOPIC   = "esp32s3/led"          # 订阅：控制灯珠。消息 #RRGGBB 或 r,g,b（如 255,0,0）
MQTT_STATE_TOPIC = "esp32s3/led/state"    # 发布：当前灯珠颜色（保留消息，订阅即知当前色）
MQTT_STATUS_TOPIC = "esp32s3/status"      # 发布：online/offline（保留消息 + LWT）
MQTT_KEEPALIVE = 30             # broker 心跳周期（秒）
MQTT_CONNECT_TIMEOUT = 8        # 单次 MQTT 连接（含 TLS 握手）超时秒数
MQTT_RETRY_INTERVAL = 10        # 断线/失败后每隔多少秒重试一次连接
