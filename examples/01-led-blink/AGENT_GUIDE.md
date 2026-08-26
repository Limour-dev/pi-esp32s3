# 例程 01：点灯（测试所有 LED 与 WS2812）—— Agent 指导手册

> 本手册写给「agent」。你的任务是引导小白运行本目录的点灯例程，
> 并把探测到的 LED 引脚填进 config.py。
> 前置条件：设备已按仓库根目录 `SETUP_GUIDE.md` 配好 MicroPython 环境。

## 1. 文件结构

| 文件 | 作用 |
|------|------|
| `config.py` | LED 引脚配置（探测后填写） |
| `scan_leds.py` | 自动探测脚本：依次点亮候选引脚，由用户观察确认 |
| `main.py` | 点灯主程序：闪烁普通 LED + WS2812 逐色/彩虹 |

## 2. 先确定串口（编号会变，用 by-id）

```bash
ls -l /dev/serial/by-id/
# 例：usb-1a86_USB_Single_Serial_5CBC064671-if00 -> ../../ttyACM0
```

后面命令里的 `<PORT>` 用 by-id 完整路径替换，例如：
`/dev/serial/by-id/usb-1a86_USB_Single_Serial_5CBC064671-if00`
（也可直接填当时的 `/dev/ttyACM0`，但注意重枚举会变号。）

## 3. 执行流程

### 第 1 步：探测引脚（需要用户盯板子）

```bash
python3 -m mpremote connect <PORT> run scan_leds.py
```

脚本分两阶段，全程约 90 秒：

- **阶段 1 扫描 WS2812**：每个候选引脚点亮红色 2 秒。
- **阶段 2 扫描普通 LED**：每个候选引脚闪烁 3 次。

**引导用户**：请用户全程盯着开发板，记录两点：

1. 「RGB 灯珠」在哪个 GPIO 时**变红** → 这就是 `WS2812_PIN`。
2. 「单色 LED」在哪个 GPIO 时**闪烁** → 这是普通 LED 引脚，并确认是
   **高电平时亮**（active_high=True）还是**低电平时亮**（False）。
   - 若整块板子从头到尾没有任何灯亮，说明该板没有此类灯，对应配置留空/跳过。

### 第 2 步：填写 config.py

把第 1 步结果写进 `config.py`：

- `WS2812_PIN` = 探测到的引脚；`WS2812_NUM` = 灯珠数量（一般 1）。
- `USER_LEDS` = 普通 LED 列表，如 `[(2, True)]`；没有就 `[]`。

### 第 3 步：上传并运行

```bash
python3 -m mpremote connect <PORT> cp config.py :
python3 -m mpremote connect <PORT> cp main.py :
python3 -m mpremote connect <PORT> run main.py
```

### 第 4 步：验证

预期现象：

- 普通 LED（若有）闪烁 3 次；
- WS2812 依次显示 红→绿→蓝→黄→青→品红→白，随后彩虹循环约 10 秒，最后熄灭；
- 串口打印「全部测试完成」与剩余内存。

## 4. 排错速查

| 现象 | 排查 |
|------|------|
| WS2812 不亮 | ① 引脚填错，重跑 scan_leds.py ② 灯珠数量不对 |
| 普通 LED 不亮 | active_high 写反了，交换 True/False 再试 |
| 阶段 2 中 RGB 灯乱闪 | 那是 WS2812 数据线被当普通 IO 驱动，忽略即可 |
| `ImportError: no module named 'config'` | 第 3 步没先 `cp config.py :` |
| 端口连接失败 | 端口被占或编号变了，重新 `ls -l /dev/serial/by-id/` |

## 5. 进阶：开机自动运行点灯

`main.py` 是 MicroPython 开机自动执行的约定文件名，所以第 3 步 `cp main.py :`
之后，开发板每次复位/上电都会自动跑点灯例程。

若不想自动运行，把文件改名为 `main.py` 以外的名字（如 `led_test.py`）再 `run`。
