# 例程 03：BLE 文件服务 + WS2812 LED 控制 —— Agent 指导手册

> 本手册写给「agent」。你的任务是引导小白运行本目录例程：
> 浏览器（Chrome/Edge）通过 **Web Bluetooth** 连接 ESP32-S3，网页上
> 查看板子 Flash 里的文件（列表/查看/下载/删除/上传），并控制 WS2812 灯珠颜色。
> 前置条件：设备已按仓库根目录 `SETUP_GUIDE.md` 配好 MicroPython 环境，
> 例程 01 已确认 WS2812 灯珠接 GPIO48。

## 1. 文件结构

| 文件 | 作用 |
|------|------|
| `boot.py` | 看门狗：main.py 崩溃自动重启，保证广播不掉线 |
| `config.py` | 设备名 / UUID / 灯珠引脚 / 协议块大小 / **蓝牙密码** `BLE_PASSWORD`（小白可自行改） |
| `main.py` | ESP32-S3 端 BLE GATT 服务器：文件服务 + LED 服务 |
| `web/index.html` | 网页端（Web Bluetooth 客户端，单文件，静态托管即可） |

## 2. 架构说明（为什么这么设计）

- **网页不跑在板子上**：Web Bluetooth 要求页面在 HTTPS 下运行，所以网页是
  一个独立静态文件，挂到任意 HTTPS 静态托管（GitHub Pages / Netlify /
  Cloudflare Pages / 自有服务器）即可，板子只负责广播 BLE 服务。
- **BLE 数据通道**：板子暴露两个 GATT 服务——LED 服务（写 3 字节 RGB）和
  文件服务（CMD 特征写入命令，DATA 特征 notify 返回响应）。
- **行协议**：所有命令是 `\n` 结尾的 ASCII 行；每条命令的响应以 `DONE`
  行结束（出错则以 `ERR ...` 行结束，无 DONE）。文件内容用 base64 分块传。
- **为什么用 base64**：BLE 通知按 MTU 分片，直接传二进制需要自己处理分片
  边界；base64 把任意文件变成安全文本行，网页端拼接后 `atob` 还原。

## 3. 先确定串口（编号会变，用 by-id）

```bash
ls -l /dev/serial/by-id/
```
后面命令里的 `<PORT>` 用 by-id 完整路径替换。

## 4. 上传并运行（板子端）

```bash
python3 -m mpremote connect <PORT> cp boot.py :
python3 -m mpremote connect <PORT> cp config.py :
python3 -m mpremote connect <PORT> cp main.py :
python3 -m mpremote connect <PORT> reset
```

`main.py` 是开机自启文件名，复位后自动运行。串口应打印：

```
GATT 服务注册完成: led=16 cmd=19 data=21
正在广播: ESP32S3-FS
（启动横幅会打印设备名/版本/密码，如 密码: 1234）
```

板载 WS2812 灯珠应显示**暗绿色**（广播中待连接）。

## 5. 部署网页（需要 HTTPS）

`web/index.html` 是零依赖单文件，**整个页面复制粘贴即可**，任选一种方式：

- **GitHub Pages**：新建仓库 → Settings → Pages → 把 index.html 放根目录
- **Netlify / Vercel / Cloudflare Pages**：拖拽上传 index.html 即可
- **本地临时测**：Chrome 里 `localhost` 也算安全上下文，可直接
  `python3 -m http.server 8000` 后访问 http://localhost:8000/web/ 测试
  （Web Bluetooth 在 localhost 可用，无需 HTTPS）

> ⚠️ 浏览器要求：**Chrome / Edge**（桌面版或 Android）支持 Web Bluetooth；
> **iOS Safari 不支持**，iPhone 上无法使用本页面。

## 6. 引导用户测试

1. 板子上电（main.py 自动跑，灯珠暗绿 = 广播中）。
2. 手机（Android）或电脑 Chrome/Edge 打开部署好的页面。
3. 点「连接设备」→ 选择 `ESP32S3-FS` → **输入密码**（默认 `1234`，见 `config.py` 的 `BLE_PASSWORD`）。
4. 验证四点：
   - 连接后灯珠变**蓝色**（已连接）；
   - 文件面板自动列出板子上的文件（boot.py / config.py / main.py 带大小）；
   - 点「查看」能看文本内容，「下载」能拿到原始文件，「上传」能把本地文件
     传到板子，「删除」能删文件；
   - LED 面板选色/预设色/熄灭，灯珠即时变色并保持（断开后恢复暗绿）。

## 7. 排错速查

| 现象 | 排查 |
|------|------|
| 页面提示「不支持 Web Bluetooth」 | 换 Chrome/Edge；确认页面是 HTTPS 或 localhost |
| 连接后提示输密码 / 密码错误 | 密码是 `config.py` 的 `BLE_PASSWORD`（默认 `1234`），串口启动横幅也会打印；连错 3 次设备会自动断开，重新连接再试 |
| 搜不到设备 | 板子是否上电且 main.py 在跑（灯珠暗绿）；手机蓝牙是否开；距离太远 |
| 连接后马上断开 | 板子断电重启后重新广播；页面「断开」后重新点「连接设备」 |
| 命令超时 | 板子可能在忙（看串口日志）；一次只操作一个动作；大文件读取耐心等 |
| 上传大文件失败 | 默认上限 512KB（`MAX_WRITE_SIZE`），超限报 `ERR size too large` |
| 改设备名/UUID 后连不上 | `config.py` 和 `web/index.html` 顶部的常量要同步改 |
| REPL 连不上（mpremote exec 报错） | `main.py` 主循环占着主线程，属正常；先 Ctrl-C 打断或用复位 |
| 设备又消失了（之前能扫到） | 脚本被串口工具（Thonny/mpremote）打断或崩溃；等 3s 看门狗会自动重启；检查板子供电 |
| 想恢复例程 02 | 重新上传 `examples/02-ap-file-server/` 的 `main.py` |

## 8. 已踩过的坑（实现时别重犯）

1. **`gatts_register_services` 必须一次注册全部服务**：分两次调用时，本固件
   每次调用都从句柄 16 重新分配，两个服务的特征句柄会冲突（都返回 16），
   导致 IRQ 分派错乱。一次调用返回 `((led,), (cmd, data))` 这样的嵌套元组。
2. **本固件未导出 `bluetooth.BLE.IRQ_*` 常量**：`dir(bluetooth)` 里没有，
   用 `getattr(ble, name, fallback)` 兜底硬编码（1/2/3/4，与官方一致）。
3. **`bytes[::-1]` 不支持**：MicroPython 的 bytes 只支持 step=1 切片，
   反转用 `bytes(reversed(raw))`。
4. **base64 分块长度必须是 4 的倍数**：`ubinascii.a2b_base64` 对非 4 倍数
   长度会抛 `ValueError: incorrect padding`。网页端每块 168 字符（4 的倍数），
   板端读文件每块 `(CHUNK_SIZE-2)//4*3` 字节。
5. **每条命令的响应必须以 `DONE` 结尾**：网页的 request/response 引擎按
   `DONE`/`ERR` 判定结束，单行回复（PONG/OK/SIZE）后面必须补 `DONE`，
   否则网页会一直等到超时。
6. **网页 `request()` 里 `writeValue` 可能同步抛异常**（如未连接时 cmdChar
   为 null），必须 try/catch 并清理进行中的请求状态，否则 req 泄漏导致后续
   所有命令报「已有请求进行中」。
7. **IRQ 回调里只做轻量工作**：把收到的字节 append 进 pending 列表并置标志，
   主循环里统一处理；不要在 IRQ 里写 neopixel（RMT）或发通知。
8. **`bytearray` 不支持 `del buf[:n]` 切片删除**（CPython 可以，MicroPython 抛
   `TypeError: 'bytearray' object doesn't support item deletion`），要用重切片
   `buf = buf[n:]` 替代。这是「连接后第一次发命令就断开」的头号原因：
   网页发 PING → 板子 `_drain_cmds` 崩 → 看门狗重启 → BLE 断开。
9. **本固件 `bytearray` 没有 `.clear()`**：`bytearray.clear()` 抛 AttributeError，
   清空用 `buf = bytearray()` 重建。
10. **看门狗 boot.py 会把 mpremote 挡在外面**：mpremote 每次进 raw REPL 会软复位，
    软复位后看门狗又拉起 main.py，REPL 一直忙。想上板调试：硬复位后启动窗口内
    狂发 Ctrl-C 打断看门狗进 REPL，或先 `os.rename('boot.py','boot_wd.py')` 禁用。
