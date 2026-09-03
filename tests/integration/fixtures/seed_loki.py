"""向 Loki push 一条带标签日志，供 search_logs 真实命中。幂等：重复执行追加一条。"""
import time

import httpx

LOKI_URL = "http://127.0.0.1:3100"
LINE = "level=error msg=\"order-service 500: upstream timeout\" trace=abc123"


def seed() -> None:
    ns = str(time.time_ns())
    payload = {"streams": [
        {"stream": {"app": "order-service"}, "values": [[ns, LINE]]},
    ]}
    r = httpx.post(f"{LOKI_URL}/loki/api/v1/push", json=payload, timeout=10)
    r.raise_for_status()


if __name__ == "__main__":
    seed()
    print("seeded 1 log line")
