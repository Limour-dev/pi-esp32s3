#!/usr/bin/env python3
"""broker 连通性/板子在线探测：只读连接，看 esp32s3/# 保留消息与在线客户端数。

用法（不需要真硬件，宿主机跑；TLS 用系统信任库校验服务器证书）：
    python3 test/test_mqtt_broker_probe.py --host cdn-g.limour.top --port 8883 \
        --user limour --pass '密码'

判断：
    - rc=Success + broker 版本           → 凭据有效、链路通
    - esp32s3/# 有保留消息               → 板子连上过并发布过（status=online/offline、led/state=颜色）
    - $SYS/broker/clients/connected=N    → 在线客户端数；板子在线时应 ≥ 实际设备数+1（含本 probe）
    - 只有 $SYS 没有 esp32s3             → 板子不在这个 broker 上（面板 CONNECTED 是过期状态）
退出码：0=收到 esp32s3 消息；2=连接成功但无 esp32s3 消息；1=连接失败。
"""
import argparse, ssl, sys, time
import paho.mqtt.client as mqtt

WATCH_SECONDS = 8


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", required=True)
    ap.add_argument("--port", type=int, default=8883)
    ap.add_argument("--user", default="")
    ap.add_argument("--pass", dest="password", default="")
    ap.add_argument("--wait", type=float, default=WATCH_SECONDS, help="订阅观察秒数")
    args = ap.parse_args()

    got = []
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="broker-probe")

    def on_connect(cl, ud, flags, rc, props=None):
        print("[on_connect] rc =", rc)
        cl.subscribe("esp32s3/#", qos=0)
        cl.subscribe("$SYS/broker/version", qos=0)
        cl.subscribe("$SYS/broker/clients/connected", qos=0)

    def on_message(cl, ud, msg):
        got.append((msg.topic, msg.payload.decode(errors="replace")))
        print("[msg] %s = %r" % (msg.topic, msg.payload))

    c.on_connect = on_connect
    c.on_message = on_message
    c.tls_set(cert_reqs=ssl.CERT_REQUIRED)
    if args.user:
        c.username_pw_set(args.user, args.password)

    print("连接 %s:%s ..." % (args.host, args.port))
    try:
        c.connect(args.host, args.port, keepalive=15)
        c.loop_start()
        time.sleep(args.wait)
    except Exception as e:
        print("连接失败:", repr(e))
        sys.exit(1)
    finally:
        c.loop_stop()
        c.disconnect()

    print("\n--- 收到 %d 条 ---" % len(got))
    for t, p in got:
        print("  %s = %s" % (t, p))
    has_esp = any(t.startswith("esp32s3/") for t, _ in got)
    sys.exit(0 if has_esp else 2)


if __name__ == "__main__":
    main()
