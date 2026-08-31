# 测试（密码认证）

两个测试都不需要真硬件，在宿主机器上即可跑。

| 文件 | 测什么 | 怎么跑 |
|------|--------|--------|
| `test_auth_board.py` | 板端 `main.py` 的认证逻辑：门禁、错密码计数、3 次自动断开、新连接重置。mock BLE/硬件模块，走 `_drain_cmds` 真实接收路径 | `python3 test/test_auth_board.py` |
| `test_auth_web.mjs` | 网页端 `web/index.html` 的真实 JS：正确密码解锁→PING/列表、错 3 次断开、取消断开、挂起请求被 reject。Node `vm` + 假 BLE 设备（行为对齐 `main.py`），无需浏览器 | `node test/test_auth_web.mjs` |

## 前提

- `test_auth_board.py`：Python 3（宿主机），`main.py` 在上一级目录。
- `test_auth_web.mjs`：Node 18+（用 `import.meta.url` 定位 `web/index.html`），无需任何 npm 依赖。

## 说明

- 假设备中的密码 `1234` 与 `config.py` 的 `BLE_PASSWORD` 默认值一致；改密码后需同步改测试里的 `PWD` / `AUTH 1234`。
- `test_auth_web.mjs` 场景 4 验证的是 `onDisconnected()` 对挂起请求的 reject 修复（防止请求进行中断开导致页面 Promise 永不 settle）。
