# 例程 03：BLE 文件服务 + WS2812 LED 控制 实验记录

> 日期：2026-08-26
> 地点/环境：VMware 虚拟机 + Ubuntu + ESP32-S3 开发板（USB 直通）

## 1. 实验环境

| 项目 | 值 |
|------|-----|
| 开发板 | ESP32-S3（QFN56，8MB Octal PSRAM，16MB Flash） |
| 固件 | MicroPython v1.29.0（`ESP32_GENERIC_S3-SPIRAM_OCT` 变体） |
| 串口 | `/dev/serial/by-id/usb-1a86_USB_Single_Serial_5CBC064671-if00`（by-id 路径） |
| 工具 | mpremote 1.29.0 / esptool 5.3.1 / pyserial / Node（网页协议模拟测试） |
| 客户端 | 用户手机 + Chrome/Edge（Web Bluetooth，页面挂 HTTPS） |

## 2. 实验目的

1. ESP32-S3 作 BLE GATT 服务器：暴露文件服务（列表/查看/下载/删除/上传板子 Flash 文件）与 LED 服务（写 3 字节 RGB 控制 WS2812）。
2. 网页端（Web Bluetooth 客户端，单文件，需 HTTPS）远程连接操作，含中文暗色 UI + 日志面板。
3. 全流程验证：扫描 → 连接 → 文件操作 → LED 变色，稳定不掉线。

## 3. 实验过程

### 3.1 架构设计

- **网页不跑在板子上**：Web Bluetooth 强制要求 HTTPS 上下文，板子做不了 TLS，所以网页是独立静态文件（`web/index.html`），挂 GitHub Pages/Netlify 等任意 HTTPS 托管，板子只广播 BLE。
- **两个 GATT 服务**：LED 服务（`fff0`/`fff1`，写 3 字节 RGB）+ 文件服务（`ffe0`：CMD 特征写命令，DATA 特征 notify 返回）。
- **行协议 + base64**：命令是 `\n` 结尾 ASCII 行，每条命令响应以 `DONE` 收尾（出错 `ERR` 收尾）；文件内容 base64 分块传，网页拼回后 `atob`。选 base64 是因为 BLE 通知按 MTU 分片，base64 把任意二进制变成安全文本行，无需自己拼分片边界。

### 3.2 GATT 注册的坑：必须一次注册全部服务

最初分两次 `gatts_register_services()`（LED 一次、文件服务一次），实测发现**两次调用句柄冲突**：每次调用都从句柄 16 重新分配，两个服务的特征句柄重复（都拿到 16），IRQ 分派错乱。

验证：一次调用返回嵌套元组 `((16,), (19, 21))`，三个句柄互不相同。改为一次注册后 `led=16 cmd=19 data=21` 稳定。

### 3.3 固件怪癖探测（板端实测）

- **IRQ 常量未导出**：`dir(bluetooth)` 里没有 `IRQ_CENTRAL_CONNECT` 等，用 `getattr(ble, name, 数字兜底)`（1/2/3/4，与官方一致）。
- **`bytes[::-1]` 不可用**：MicroPython bytes 只支持 step=1 切片，UUID 转小端用 `bytes(reversed(raw))`。
- **`ubinascii.a2b_base64` 对非 4 倍数长度抛 `incorrect padding`**：网页端每块 168 字符（4 的倍数），板端读文件每块 `(CHUNK_SIZE-2)//4*3` 字节，两边对齐。
- `ble.config(mtu=517)` 可用（默认 256），Chrome/Android 会协商到 512。

### 3.4 网页协议端到端模拟测试（Node 无 BLE 环境）

VM 无蓝牙适配器，无法真机连 BLE。方案：**Node + vm 模块模拟 Web Bluetooth API 和一台行为与 main.py 完全一致的假设备**，驱动页面真实 JS，验证协议。

暴露并修复的真实 bug：

1. **`request()` 只认 `DONE`/`ERR` 收尾**：设备对 PING/DEL/WRITE_BEGIN/WRITE_END/SIZE 的回复是单行（PONG/OK/SIZE）没有 `DONE` → 网页一直等到超时。修复：main.py 所有回复补发 `DONE`。
2. **`writeValue` 同步抛异常泄漏请求状态**：未连接时 `cmdChar` 为 null，`cmdChar.writeValue()` 在 Promise executor 里同步抛 TypeError，`.catch` 不执行，`req` 永不清理 → 后续所有命令报「已有请求进行中」。修复：`request()` 里 try/catch + 显式清理 `req`。
3. 模拟测试覆盖：连接/列表/查看/上传/删除/LED/断开；二进制（133/134/512B）与空文件往返全部字节级一致。

### 3.5 上板实测：两个致命问题

**问题 A：BLE 调试助手和网页都扫不到设备。**
- 诊断：串口能连上且 REPL 空闲 → main.py 根本没在运行。原因是我之前 `mpremote run` 前台测试被 timeout 杀掉后脚本停在 REPL，一直没复位，用户测的时候板子没广播。
- 处理：复位重启。另外加了 **看门狗 `boot.py`**：main.py 崩溃/被中断后 3 秒自动重启，保证广播不掉线；Ctrl-C 可跳出进 REPL 调试。

**问题 B：连接成功但 4 秒后断开（GATT 就绪 → 断开 → PING 超时）。**
- 板端日志抓到崩溃：
  ```
  File "main.py", line 355, in _drain_cmds
  TypeError: 'bytearray' object doesn't support item deletion
  ```
- 根因：网页连接后发第一条命令 `PING`，板子 `_drain_cmds` 里 `del cmd_buf[:nl+1]`——**MicroPython 的 bytearray 不支持 `del` 切片删除**（CPython 可以）。崩溃后看门狗重启板子 → BLE 断开。
- 之前模拟测试没发现，是因为测试直接调 `_handle_cmd`，绕过了 `_drain_cmds` 这条真实接收路径。
- 修复：`cmd_buf = cmd_buf[nl+1:]` 重切片替代。
- 顺带发现：本固件 **`bytearray` 没有 `.clear()`**（>4096 防呆分支会崩），改为重建空对象。

### 3.6 修复后验证

- 走真实接收路径（`pending` 进字节 → `_drain_cmds` 解析执行）验证：PING/WRITE_BEGIN/CHUNK/END/SIZE/READ/DEL 全部正常，多块命令一条龙不崩。
- **60KB 模式化二进制多分块写入 + 读回：字节级一致**（`match: True`）。
- 4096 防呆分支正常（灌 5000 字节无换行 → 清空 → 后续命令照常）。
- 用户实测：连接稳定、文件列表加载、查看/上传/删除/LED 全部正常 ✅。

### 3.7 调试工具经验

- mpremote 每次进 raw REPL 会**软复位**，软复位后看门狗又拉起 main.py，REPL 一直忙，`exec/cp/ls` 全报 `could not enter raw repl`——属预期行为。
- 上板调试流程：esptool 硬复位（正确释放 DTR/RTS）→ 启动窗口内狂发 Ctrl-C 打断看门狗 → 进 REPL；或 pyserial 手动 raw REPL（Ctrl-A，不软复位）执行诊断代码。
- 曾用 pyserial 乱 toggle DTR/RTS 把芯片带进 DOWNLOAD 模式（`boot:0x0` 卡死），esptool 硬复位可救回。

## 4. 最终结论

- BLE 广播：**ESP32S3-FS**，服务 `led=16 cmd=19 data=21`；连接/断开状态灯：暗绿=广播，蓝=已连接，用户色=LED 指令，断开恢复暗绿。
- 文件服务：列表/查看/下载/删除/上传全通，60KB 二进制往返字节级一致；上传上限默认 512KB。
- 网页端：单文件零依赖，HTTPS 托管即用；Chrome/Edge（桌面+Android）可用，iOS Safari 不支持。
- 板子文件：`boot.py`（看门狗）+ `config.py` + `main.py`，上电自启。
- 遗留问题：无。实测全程未再掉线。

## 5. 经验教训（重点）

1. **`bytearray` 不支持 `del buf[:n]` 切片删除**（CPython 可以，MicroPython 抛 `TypeError`）。识别特征：连接后第一次发命令就断开/看门狗反复重启。修复用重切片 `buf = buf[n:]`。这是本次「连上 4 秒就断」的头号坑。
2. **`bytearray` 没有 `.clear()`**：清空用 `buf = bytearray()` 重建，不要想当然。
3. **测试必须走真实调用路径**：直接调 `_handle_cmd` 测协议逻辑，测不到 `_drain_cmds` 的接收解析崩溃。上板前应模拟「字节进 pending → 主循环 drain → 处理」的完整链路（Node 假设备 + 板端 drain 测试双管齐下）。
4. **mpremote 进 raw REPL 会软复位**：软复位会重跑 boot.py/main.py，加上看门狗后 REPL 永远忙。别反复试 mpremote，直接 pyserial 硬复位 + 启动窗口 Ctrl-C 打断。
5. **DTR/RTS 复位时序有讲究**：乱 toggle 会把芯片带进 DOWNLOAD 模式（串口显示 `boot:0x0 (DOWNLOAD)` + `waiting for download`，静默无输出），用 esptool 的复位序列最稳。
6. **看门狗价值大**：用户遇到崩溃时板子 3 秒自愈重新广播，不用断电重插；但调试时要记得它的存在（Ctrl-C 可跳出）。
7. **分两次 `gatts_register_services` 句柄冲突**：必须一次注册全部服务，返回值是嵌套元组 `((led,), (cmd, data))`。
8. **网页 request/response 引擎按 `DONE` 收尾判定**：单行回复后面必须补 `DONE`；`writeValue` 同步异常要 try/catch 并清理请求状态，否则永久「已有请求进行中」。
