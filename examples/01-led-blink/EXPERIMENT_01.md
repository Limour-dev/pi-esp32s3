# 例程 01：点灯实验记录（测试所有 LED 与 WS2812）

> 日期：2026-08-26
> 地点/环境：VMware 虚拟机 + Ubuntu + ESP32-S3 开发板（USB 直通）

## 1. 实验环境

| 项目 | 值 |
|------|------|
| 开发板 | ESP32-S3（QFN56，8MB Octal PSRAM，16MB Flash） |
| 固件 | MicroPython v1.29.0（`ESP32_GENERIC_S3-SPIRAM_OCT` 变体） |
| 串口 | `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5CBC064671-if00`（by-id 路径，重枚举不变号） |
| 工具 | mpremote 1.29.0 |

## 2. 实验目的

1. 探测板载 LED 分别接在哪些 GPIO（WS2812 灯珠 + 普通单色 LED）。
2. 把探测结果填入 `config.py`。
3. 上传并运行 `main.py`，验证 WS2812 逐色 + 彩虹显示正常。

## 3. 实验过程

### 3.1 探测（scan_leds.py，全程约 90 秒）

```
python3 -m mpremote connect <PORT> run scan_leds.py
```

- **阶段 1（WS2812）**：依次点亮 12 个候选引脚红色 2 秒。
  - 结果：**GPIO48 时 RGB 灯珠变红** → `WS2812_PIN = 48`。
- **阶段 2（普通 LED）**：依次让 24 个候选引脚闪烁 3 次。
  - 结果：用户看到「有灯在闪」，但**记不住具体引脚**。

### 3.2 重扫阶段 2（scan_led_only.py，临时脚本，已删除）

针对「记不住引脚」的问题，重跑只含阶段 2 的脚本，并把闪烁节奏放慢（0.5s on/off）、加大打印提示。
结果：用户仍然难以在 24 个引脚中追踪 —— **让小白全程盯 24 个引脚逐一闪烁，这个方案不现实**。

### 3.3 线索：商家提供的资料

商家给了如下代码：

```python
pin12 = machine.Pin(12, machine.Pin.OUT)
pin12.value(0)
pin13 = machine.Pin(13, machine.Pin.IN, machine.Pin.PULL_UP)
print(pin13.value())
while True:
    print(pin13.value())
    pin12.value(0)
    time.sleep_ms(500)
    pin12.value(1)
    time.sleep_ms(500)
    print("End of Loop")
```

**分析**：这是一个**继电器控制演示**——GPIO12 每 500ms 翻转电平驱动继电器线圈，GPIO13 上拉输入读回继电器状态做反馈。曾一度怀疑板上有继电器模块，打算做 GPIO12/13 针对性验证。

### 3.4 真相：板上只有 PWR/TX/RX 状态灯 + WS2812

用户仔细查看板子后确认：板上只有 **PWR 灯（电源常亮）、TX 灯、RX 灯（串口通信时闪烁）**，**没有独立用户单色 LED**。

之前的「看到灯闪」其实是 **TX 灯**——`mpremote run` 执行期间板子持续向串口打印（`>>> 测试 GPIOxx <<<`），TX 灯随打印狂闪，与任何 GPIO 无关，纯属误导。

对照 AGENT_GUIDE 的说明：「若整块板子从头到尾没有任何灯亮，说明该板没有此类灯，对应配置留空/跳过」。

### 3.5 配置与验证

`config.py` 最终值（与探测前默认值一致，无需修改）：

```python
USER_LEDS = []      # 板上无独立单色 LED
WS2812_PIN = 48     # 探测确认：GPIO48
WS2812_NUM = 1      # 1 颗灯珠
```

上传并运行：

```bash
python3 -m mpremote connect <PORT> cp config.py :
python3 -m mpremote connect <PORT> cp main.py :
python3 -m mpremote connect <PORT> run main.py
```

输出摘要：

```
未配置普通 LED（config.USER_LEDS 为空），跳过。
WS2812 在 GPIO48，共 1 颗，逐色测试：
  红 绿 蓝 黄 青 品红 白
彩虹循环约 10 秒 ...
WS2812 测试完成，已熄灭。
全部测试完成。剩余内存: 8316208
```

**用户确认：7 色 + 彩虹 + 熄灭，表现完美。**

## 4. 最终结论

- WS2812 灯珠在 **GPIO48**，数量 1 颗，功能正常。
- 板上**无独立用户单色 LED**，`USER_LEDS = []`。
- 剩余内存约 7.9MB（8MB PSRAM 正常发挥）。
- `main.py` 已上传到板子，**每次复位/上电会自动运行点灯例程**（不想自启可 `mv main.py led_test.py` 改名）。

## 5. 经验教训（重点）

1. **探测脚本的交互设计**：让小白全程盯 24 个引脚逐一闪烁并记住编号，几乎不可能完成。更好的做法是
   - 优先查厂家资料/原理图缩小候选范围；
   - 或做成「一次只测一个引脚、用户确认后跳过」的交互式流程；
   - 或按候选概率排序，先测最可能的几个。
2. **区分状态灯与用户 LED**：开发板上的 **PWR（常亮）/ TX / RX（通信闪烁）** 是串口/电源状态灯，不是用户可编程 LED。`mpremote run` 期间板子持续打印会让 TX 灯狂闪，极易被误认。发现「有灯闪但对应不上引脚」时，应优先怀疑 TX/RX 状态灯。
3. **厂家资料是双刃剑**：商家给的继电器 demo 提供了 GPIO12/13 的线索，但**必须实测验证**——本例实际板上并无继电器，资料对应的可能是另一款板子/外设。
4. **串口用 by-id 路径**：`/dev/serial/by-id/...` 比 `/dev/ttyACM0` 稳定，重枚举不飘号，多命令执行时不易连错设备。
5. **探测顺序要避开敏感引脚**：候选列表已避开 flash/PSRAM（26~37）与 strapping 引脚（0/3/45/46），避免探测过程干扰启动。
6. **验证要「眼见为实」**：WS2812 探测的判定标准简单可靠——候选引脚点亮红色 2 秒，灯珠在哪变红就是哪。颜色顺序（红绿蓝黄青品红白）也是验证程序正确性的好手段。
