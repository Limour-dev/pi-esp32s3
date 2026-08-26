# config.py —— 例程 03：BLE 文件服务 + WS2812 LED 控制 配置
#
# 改这里的值即可自定义设备名/UUID/灯珠参数，改完重新上传本文件并复位板子。
# 注意：如果改了 UUID 或设备名，web/index.html 里对应的常量也要同步改。

# ---- BLE 设备名（网页搜索时按此前缀过滤）----
DEVICE_NAME = "ESP32S3-FS"

# ---- 状态灯（WS2812），例程 01 探测确认：灯珠接 GPIO48 ----
WS2812_PIN = 48
WS2812_NUM = 1

# ---- GATT 服务/特征 UUID（128 位，避免与标准服务冲突）----
# LED 服务：网页写 3 字节 RGB 控制灯珠
LED_SERVICE_UUID = "0000fff0-0000-1000-8000-00805f9b34fb"
LED_CHAR_UUID    = "0000fff1-0000-1000-8000-00805f9b34fb"
# 文件服务：CMD 写入命令，DATA 以 notify 返回响应
FILE_SERVICE_UUID = "0000ffe0-0000-1000-8000-00805f9b34fb"
CMD_CHAR_UUID     = "0000ffe1-0000-1000-8000-00805f9b34fb"
DATA_CHAR_UUID    = "0000ffe2-0000-1000-8000-00805f9b34fb"

# ---- 协议参数 ----
CHUNK_SIZE = 180        # 每条 notify 响应行的最大字节数（含前缀）
# 说明：BLE MTU 协商后一般为 512（Chrome/Android 均会协商到 ≥256），
#       CHUNK_SIZE 留足余量即可；Web Bluetooth 客户端行长度不能超过它。
