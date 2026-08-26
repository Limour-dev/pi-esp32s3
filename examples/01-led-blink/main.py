# main.py —— 例程 01：点灯（测试所有 LED 与 WS2812）
#
# 运行前请先运行 scan_leds.py 完成探测，并把结果填进 config.py。
# 本文件名为 main.py，上传到板子后开机/复位会自动运行。

import gc
import time
from machine import Pin
import neopixel
import config


def _hsv_to_rgb(h):
    """色相(0~360) -> RGB，用于彩虹循环。"""
    h %= 360
    sector = h // 60
    f = h / 60 - sector
    q = int(255 * (1 - f))
    t = int(255 * f)
    if sector == 0:
        return (255, t, 0)
    if sector == 1:
        return (q, 255, 0)
    if sector == 2:
        return (0, 255, t)
    if sector == 3:
        return (0, q, 255)
    if sector == 4:
        return (t, 0, 255)
    return (255, 0, q)


def test_user_leds():
    """闪烁所有普通单色 LED。"""
    if not config.USER_LEDS:
        print("未配置普通 LED（config.USER_LEDS 为空），跳过。")
        return
    for gpio, active_high in config.USER_LEDS:
        on = 1 if active_high else 0
        off = 0 if active_high else 1
        level = "高电平" if active_high else "低电平"
        print(f"闪烁 GPIO{gpio}（{level}点亮）3 次 ...")
        pin = Pin(gpio, Pin.OUT)
        for _ in range(3):
            pin.value(on)
            time.sleep(0.3)
            pin.value(off)
            time.sleep(0.3)
        del pin


def test_ws2812():
    """WS2812：逐色显示 + 彩虹循环。"""
    np = neopixel.NeoPixel(Pin(config.WS2812_PIN), config.WS2812_NUM)
    colors = [
        ("红", (255, 0, 0)),
        ("绿", (0, 255, 0)),
        ("蓝", (0, 0, 255)),
        ("黄", (255, 255, 0)),
        ("青", (0, 255, 255)),
        ("品红", (255, 0, 255)),
        ("白", (255, 255, 255)),
    ]
    print(f"WS2812 在 GPIO{config.WS2812_PIN}，共 {config.WS2812_NUM} 颗，逐色测试：")
    for name, rgb in colors:
        print(f"  {name} {rgb}")
        for i in range(config.WS2812_NUM):
            np[i] = rgb
        np.write()
        time.sleep(0.6)

    print("彩虹循环约 10 秒 ...")
    for step in range(100):
        for i in range(config.WS2812_NUM):
            np[i] = _hsv_to_rgb(step * 3.6 + i * 60)
        np.write()
        time.sleep(0.1)

    for i in range(config.WS2812_NUM):
        np[i] = (0, 0, 0)
    np.write()
    print("WS2812 测试完成，已熄灭。")


print("=" * 56)
print("ESP32-S3 点灯例程：测试所有 LED 与 WS2812")
print("=" * 56)
test_user_leds()
print()
test_ws2812()
print()
gc.collect()
print("全部测试完成。剩余内存:", gc.mem_free())
