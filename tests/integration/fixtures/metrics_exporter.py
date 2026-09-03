"""Prometheus fixture exporter：暴露与 Workload 契约同名的指标。
每次 /metrics 被 scrape 计数递增，使 rate() 有值；ghost-service 不暴露任何系列。
2s scrape 间隔下 rate 约 5 req/s、error_rate 0.2、cpu 0.5 核。
"""
from http.server import BaseHTTPRequestHandler, HTTPServer

_STATE = {"n": 0}


def build_metrics_text() -> str:
    n = _STATE["n"]
    total = n * 10
    ok = n * 8        # status=200
    err = n * 2       # status=500（命中 status=~"5..|4.."）
    cpu = n * 1.0     # container_cpu_usage_seconds_total 秒数递增
    mem = 512 * 1024 * 1024
    return "\n".join(
        [
            f'http_requests_total{{service="order-service",status="200"}} {ok}',
            f'http_requests_total{{service="order-service",status="500"}} {err}',
            f'container_cpu_usage_seconds_total{{service="order-service"}} {cpu}',
            f"container_memory_usage_bytes{{service=\"order-service\"}} {mem}",
        ]
    )


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        if self.path != "/metrics":
            self.send_response(404)
            self.end_headers()
            return
        _STATE["n"] += 1
        body = build_metrics_text().encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; version=0.0.4")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):  # 静默
        pass


def main() -> None:
    HTTPServer(("127.0.0.1", 8000), Handler).serve_forever()


if __name__ == "__main__":
    main()
