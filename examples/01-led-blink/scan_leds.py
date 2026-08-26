# scan_leds.py —— LED 引脚自动探测脚本
#
# 用途：不知道板子 LED 接在哪个 GPIO 时，用本脚本依次点亮候选引脚，
#       让用户观察开发板，确认哪个引脚让灯亮，再把结果填进 config.py。
#
# 用法（agent 执行，用户盯板子）：
#   python3 -m mpremote connect <PORT> run scan_leds.py

import gc
import time
from machine import Pin
import neopixel

# 候选 WS2812 引脚（按常见程度排序；已避开 flash/PSRAM 与 strapping 引脚）
WS2812_CANDIDATES = [48, 21, 2, 8, 38, 47, 1, 18, 14, 42, 17, 5]

# 候选普通 LED 引脚（同上，避开 0/3/45/46 strapping 与 26~37 flash/PSRAM）
LED_CANDIDATES = [2, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16,
                  17, 18, 21, 38, 39, 40, 41, 42, 47, 48]


def scan_ws2812():
    print("=" * 56)
    print("阶段 1/2：扫描 WS2812 RGB 灯珠")
    print("每个候选引脚会点亮红色 2 秒。")
    print("请盯住板上的 RGB 灯珠，记下「哪个引脚让它变红」。")
    print("=" * 56)
    for p in WS2812_CANDIDATES:
        print(f"\n>>> 测试 GPIO{p}：红色 2 秒 <<<")
        try:
            np = neopixel.NeoPixel(Pin(p), 1)
            np[0] = (255, 0, 0)
            np.write()
            time.sleep(2)
            np[0] = (0, 0, 0)
            np.write()
            del np
            gc.collect()
        except Exception as e:
            print(f"    GPIO{p} 异常：{e}")
        time.sleep(0.5)
    print("\n阶段 1 结束。RGB 灯在哪个引脚时变红，那个引脚就是 WS2812_PIN。")


def scan_led():
    print("\n" + "=" * 56)
    print("阶段 2/2：扫描普通单色 LED")
    print("每个候选引脚快速闪烁 3 次（高→低 循环）。")
    print("请盯住除 RGB 外的单色 LED，记下「哪个引脚让它闪烁」")
    print("以及「高电平时亮」还是「低电平时亮」。")
    print("（若某引脚让 RGB 灯珠乱闪，那是 WS2812 数据线被驱动，忽略即可。）")
    print("=" * 56)
    for p in LED_CANDIDATES:
        print(f"\n>>> 测试 GPIO{p}：闪烁 3 次 <<<")
        try:
            pin = Pin(p, Pin.OUT)
            for _ in range(3):
                pin.value(1)
                time.sleep(0.4)
                pin.value(0)
                time.sleep(0.4)
            del pin
            gc.collect()
        except Exception as e:
            print(f"    GPIO{p} 异常：{e}")
        time.sleep(0.3)
    print("\n阶段 2 结束。记下让单色 LED 闪烁的引脚及其点亮电平。")


print("LED 引脚自动探测开始，全程约 90 秒，请观察开发板。")
scan_ws2812()
scan_led()
print("\n探测完成。请把结果填入 config.py（见 AGENT_GUIDE.md）。")
