#!/usr/bin/env python3
"""peer-cache 集合点（rendezvous）服务器。

职责非常薄：只维护一张在线 peer 表 (peer_id -> {address, port, last_seen})，
不转发任何文件数据。peer 启动后定期 POST /register 心跳；掉线超过 TTL 自动剔除。
拉取方通过 GET /peers 拿到所有在线地址，再直连对方取 NAR。

设计说明：
- 纯标准库，无第三方依赖，在国内服务器上直接 `python3 server.py --port 8250` 即可跑。
- 服务器本身不要求 IPv6：client 连上来时若没显式带 address，就用它的来源 IP。
  （client 侧会自己上报稳定的全局/ULA v6 地址供其他 peer 直连。）
"""
import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DEFAULT_TTL = 90          # 心跳超过这个秒数未更新即视为离线
CLEANUP_INTERVAL = 30     # 清理线程间隔


class PeerTable:
    def __init__(self, ttl=DEFAULT_TTL):
        self._peers = {}
        self._lock = threading.Lock()
        self._ttl = ttl

    def upsert(self, peer_id, address, port):
        now = time.time()
        with self._lock:
            self._peers[peer_id] = {
                "peer_id": peer_id,
                "address": address,
                "port": int(port),
                "last_seen": now,
            }

    def remove(self, peer_id):
        with self._lock:
            self._peers.pop(peer_id, None)

    def list(self):
        now = time.time()
        with self._lock:
            stale = [pid for pid, p in self._peers.items()
                     if now - p["last_seen"] > self._ttl]
            for pid in stale:
                del self._peers[pid]
            return list(self._peers.values())

    def cleanup_loop(self):
        while True:
            time.sleep(CLEANUP_INTERVAL)
            self.list()


table = PeerTable()


class Handler(BaseHTTPRequestHandler):
    server_version = "peer-cache-rendezvous/0.1"

    def _send_json(self, code, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode())
        except json.JSONDecodeError:
            return {}

    def log_message(self, fmt, *args):
        pass

    def do_GET(self):
        path = urlparse(self.path).path
        if path in ("/peers", "/peers/"):
            self._send_json(200, {"peers": table.list()})
        elif path in ("/healthz", "/healthz/"):
            self._send_json(200, {"ok": True, "peers": len(table.list())})
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        body = self._read_json()

        if path in ("/register", "/register/"):
            peer_id = body.get("peer_id")
            if not peer_id:
                self._send_json(400, {"error": "peer_id required"})
                return
            address = body.get("address")
            if not address:
                address = self.client_address[0]
            port = body.get("port")
            if not port:
                self._send_json(400, {"error": "port required"})
                return
            table.upsert(peer_id, address, port)
            self._send_json(200, {"ok": True, "address": address, "port": port})

        elif path in ("/unregister", "/unregister/"):
            peer_id = body.get("peer_id")
            if peer_id:
                table.remove(peer_id)
            self._send_json(200, {"ok": True})
        else:
            self._send_json(404, {"error": "not found"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8250)
    ap.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    args = ap.parse_args()

    global table
    table = PeerTable(args.ttl)
    threading.Thread(target=table.cleanup_loop, daemon=True).start()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print(f"[rendezvous] listening on {args.host}:{args.port}, ttl={args.ttl}s", flush=True)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
