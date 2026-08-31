# boot.py —— 看门狗：main.py 崩溃/退出后自动重启，保证 BLE 广播不掉线
# 想进 REPL 调试：按住 Ctrl-C（或串口发 \x03）即可跳出循环
import sys
import time

_RESTART_DELAY = 3  # 崩溃后等待秒数

while True:
    try:
        import main as _app
        _app.main()          # 阻塞运行；正常情况永不返回
        break                # main 主动退出（罕见）则不再重启
    except KeyboardInterrupt:
        print("\n[watchdog] Ctrl-C 打断，进入 REPL。")
        break
    except Exception as e:
        sys.print_exception(e)
        print("[watchdog] main.py 异常，%.1fs 后重启..." % _RESTART_DELAY)
        time.sleep(_RESTART_DELAY)
