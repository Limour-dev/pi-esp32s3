# config.py —— LED 引脚配置
#
# 请先运行 scan_leds.py 完成探测，再把结果填到下面。
# 探测方法见同目录 AGENT_GUIDE.md。

# ---- 普通单色 LED ----
# 每个元素是一个元组：(GPIO 引脚, 是否高电平有效)
#   True  = 引脚输出高电平时 LED 亮
#   False = 引脚输出低电平时 LED 亮
# 例：一颗蓝灯接 GPIO2、高电平点亮 -> USER_LEDS = [(2, True)]
#     板上没有普通 LED -> USER_LEDS = []
USER_LEDS = [
    # (2, True),
]

# ---- WS2812 可寻址 RGB 灯珠 ----
WS2812_PIN = 48    # 数据线 GPIO
WS2812_NUM = 1     # 串联灯珠数量
