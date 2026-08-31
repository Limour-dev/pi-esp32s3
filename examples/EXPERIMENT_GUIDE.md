# 实验记录归档指导手册（供 agent 使用）

> 本手册定义本仓库的「记录归档」习惯：**每个例程实验完成（或告一段落）后，agent 必须把过程、结论、踩坑写进一份实验记录 md，随代码一起归档**。
>
> 参考范本：`examples/01-led-blink/EXPERIMENT_01.md`
> 配套手册：`examples/01-led-blink/AGENT_GUIDE.md`（指导「怎么做任务」）

## 1. 为什么要有实验记录

| 痛点 | 记录的价值 |
|------|-----------|
| 换新 agent / 新机器接手，环境要重新摸索 | 记录里写明环境、串口、命令，接手即用 |
| 踩过的坑（如 TX 灯误判）转头就忘 | 经验教训沉淀下来，下次不再踩 |
| 探测结论（如 WS2812=GPIO48）无据可查 | 结论 + 依据（探测过程）可追溯、可复核 |
| 代码只能说明「能跑」，说不清「为什么这样配」 | 记录解释配置来源，避免后人乱改 |

原则一句话：**代码归档的是「结果」，记录归档的是「为什么」。**

## 2. 何时写

- **每个例程实验完成 / 验证通过后**，立即写，趁记忆新鲜。
- 实验**中途失败并换方向**（如本次探测方式推翻重来）也要记，失败路径同样有价值。
- 记录写在例程目录内，与代码同目录归档，不另开目录。

## 3. 文件命名约定

```
examples/<NN>-<name>/
├── AGENT_GUIDE.md        # 做任务前给 agent 的指导（已有约定，不变）
├── EXPERIMENT_<NN>.md    # 实验记录（本次约定，新增）
├── test/                 # 可复用测试脚本（本次约定，新增）
│   ├── test_*.py         # 例：板端逻辑 mock 测试
│   ├── test_*.mjs        # 例：网页端端到端模拟
│   └── README.md         # 每个文件「测什么 + 怎么跑」
├── config.py
├── main.py
└── ...
```

- 文件名：`EXPERIMENT_<例程编号>.md`，如 `EXPERIMENT_01.md`。
- 若同一例程有多次迭代实验，用 `EXPERIMENT_01_v2.md` 或追加章节，**不要覆盖**原记录。
- **可复用的测试脚本必须归档到例程目录的 `test/` 子目录**（与代码同目录，不另开目录）：
  - 例：板端逻辑 mock 测试（`test/test_board.py`）、网页端端到端模拟（`test/test_web.mjs`）、broker 连通性探测（例程 05 的 `test/test_mqtt_broker_probe.py`）——按例程实际需要命名，不要求统一。
  - **联网/在线探测脚本也可归档**（例：连真实 broker 验证板子是否在线、保留消息是否存在）；**凭据一律走命令行参数，不写死在文件里**。
  - 测试必须**可独立运行**：路径用相对定位（`.py` 用 `__file__` 找上级目录的 `main.py`，`.mjs` 用 `import.meta.url` 找 `../web/index.html`），不写死绝对路径。
  - 在 `test/README.md` 写清每个文件「测什么 + 怎么跑」；测试里用到的参数（如密码、设备名、引脚号）与 `config.py` 保持一致并在 README 注明。
- 一次性调试脚本、草稿**不归档**（用完即删，如本次的 `scan_led_only.py`）——区分标准：能重跑验证逻辑的才进 `test/`，仅探测用的一次性脚本不留。
## 4. 记录模板

```markdown
# 例程 <NN>：<标题> 实验记录

> 日期：<YYYY-MM-DD>
> 环境：<虚拟机/物理机 + 系统 + 板子接入方式>

## 1. 实验环境
| 项目 | 值 |
|------|-----|
| 开发板 | <型号/芯片/PSRAM/Flash> |
| 固件 | <版本/变体> |
| 串口 | <by-id 完整路径> |
| 工具 | <mpremote/esptool 版本> |

## 2. 实验目的
<1-3 条，一句话一条>

## 3. 实验过程
<按时间顺序还原，含：
 - 关键命令（可复现）
 - 探测/验证方法与结果
 - 遇到的问题与解决方向
 - 中间误判也要记>

## 4. 最终结论
<配置最终值、功能验证结果、遗留问题（如有）>

## 5. 经验教训（重点）
<编号列表：
 - 踩过的坑 + 识别特征
 - 有效的方法论（下次直接复用）
 - 给后来 agent 的提醒>
```

## 5. 内容质量检查项（写完后自查）

- [ ] 命令完整可复现（`<PORT>` 占位符或真实路径都行，但别漏参数）
- [ ] 结论有依据：每个配置值都对应一段探测/验证过程
- [ ] 经验教训不是泛泛而谈，而是「识别特征 + 应对方法」（例：TX 灯狂闪 → 怀疑状态灯而非用户 LED）
- [ ] 明确区分**事实**（探测到的）与**推测**（怀疑的），推测要标注待验证
- [ ] 可复用的测试脚本已归档进 `test/`（含 `README.md`），且从例程目录能独立跑通
- [ ] 临时文件已清理，目录只留归档物

## 6. 与 AGENT_GUIDE.md 的分工

| 文件 | 面向 | 内容 |
|------|------|------|
| `AGENT_GUIDE.md` | **实验前**，指导 agent 按流程执行任务 | 步骤、命令、判定标准、排错速查 |
| `EXPERIMENT_<NN>.md` | **实验后**，记录发生了什么 | 实际过程、结果、经验教训 |

两者互补：GUIDE 说「该怎么做」，EXPERIMENT 记「实际做成什么样、坑在哪」。改 GUIDE 会改变未来行为，改 EXPERIMENT 只影响历史记录——**别把经验写进 GUIDE，也别把流程写进 EXPERIMENT**。

## 7. agent 执行约定（写入本仓库的默认习惯）

1. 完成一个例程实验后，**默认**向用户确认是否需要归档记录；用户说「用这种记录归档习惯」或默认同意时，直接按本手册生成 `EXPERIMENT_<NN>.md`。
2. 记录写完展示给用户确认，并清理临时文件。
3. 后续例程（02、03…）沿用同样约定。

## 8. 上板实测通用经验（串口/BLE 例程适用）

> 以下坑在 03 例程上板实测中验证，跨例程通用，先记在这里省得每个例程重踩。

### 8.1 上传与 REPL（有看门狗 boot.py 时）

- **看门狗会挡 mpremote**：`mpremote cp/exec` 进 raw REPL 会软复位，软复位后 main.py 又占住 REPL → `could not enter raw repl`，属预期，别反复重试。
- **可靠上传姿势**：宿主 Python 直接复用 mpremote 的 `SerialTransport`，**关键是不软复位**：

```python
from mpremote.transport_serial import SerialTransport
t = SerialTransport(PORT, baudrate=115200, timeout=1)
t.serial.dtr = False; t.serial.rts = False   # 打开后释放复位线
for _ in range(25): t.serial.write(b"\x03"); time.sleep(0.05)  # Ctrl-C 打断看门狗进 REPL
t.enter_raw_repl(soft_reset=False)   # 不软复位，绕开看门狗
t.fs_writefile("main.py", data)      # 自带 256B 分块 + raw paste 协议
t.exit_raw_repl(); t.serial.write(b"\x04")  # 软复位跑应用
```

- **别手搓 raw paste**：MicroPython raw REPL 的 paste 是带窗口协商的协议（Ctrl-E 后设备回 `R\x01`+窗口大小），直接 Ctrl-E+数据+Ctrl-D 会卡死；用 `SerialTransport.exec/fs_writefile` 即可。
- **Ctrl-C 能打断看门狗**：boot.py 看门狗是 `while` 循环 + `except KeyboardInterrupt`，狂发 `\x03` 就能进 REPL。

### 8.2 诊断与复位

- **乱 toggle DTR/RTS 会把芯片带进 DOWNLOAD 模式**（`boot:0x0` 卡死、串口完全静默、应用无响应）。救回：`esptool.py --port <PORT> chip_id`（结束时自动 hard reset 回正常启动）。
- **串口静默 ≠ 设备死了**：应用正常运行（广播/服务中）时串口只在启动瞬间打印，之后静默是正常的。确认存活：发 Ctrl-D（软复位）看重启横幅，或发 Ctrl-C 看是否进 REPL。

### 8.3 真机验证手法

- REPL 里把 `_notify` 换成 print、直接往 `pending` 塞字节驱动 `_drain_cmds()`，即可在真机跑通真实命令解析路径（不必真连 BLE）。
- 验证完软复位恢复应用运行。

### 8.4 调试脚本细节

- 串口调试脚本一律 `python3 -u`：非 tty 时 stdout 全缓冲，被 timeout 杀掉时日志全丢（exit 124 + 空日志）。
- bytes 字面量不能含非 ASCII（`b"正在广播"` 直接 SyntaxError），串口匹配用 ASCII 标记如 `b"ESP32S3-FS"`。
- miniterm 需要 tty，stdin 被重定向时起不来（termios error）；直接写 pyserial 脚本代替。
