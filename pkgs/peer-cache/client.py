#!/usr/bin/env python3
"""peer-cache client：本机 NixOS 节点上跑的 P2P binary cache。"""
import argparse, glob, hashlib, json, os, shutil, socket, subprocess, tempfile, threading, time, urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

STORE = "/nix/store"
CACHE_DIR_DEFAULT = "/var/cache/peer-cache"

class V6ThreadingHTTPServer(ThreadingHTTPServer):
    address_family = socket.AF_INET6

def netloc(addr, port):
    return f"[{addr}]:{port}" if ":" in addr else f"{addr}:{port}"

def detect_global_v6():
    try:
        out = subprocess.check_output(["ip","-o","-6","addr","show","scope","global"], text=True)
    except Exception:
        return None
    for line in out.splitlines():
        parts = line.split()
        if "inet6" not in parts: continue
        i = parts.index("inet6")
        addr = parts[i+1].split("/")[0]
        if addr.startswith("fe80") or addr == "::1": continue
        return addr
    return None

class PeerCache:
    def __init__(self, args):
        self.args = args
        self.cache_dir = args.cache_dir
        os.makedirs(self.cache_dir, exist_ok=True)
        self.peers = []
        self.peer_port = None
        self.lock = threading.Lock()

    def local_path(self, h):
        hits = glob.glob(os.path.join(STORE, h + "-*"))
        return hits[0] if hits else None

    def ensure_local_nar(self, h, path):
        info_file = os.path.join(self.cache_dir, h + ".narinfo")
        nar_file = os.path.join(self.cache_dir, h + ".nar.zst")
        if os.path.exists(info_file) and os.path.exists(nar_file):
            with open(info_file) as f: return f.read(), nar_file
        refs_out = subprocess.check_output(["nix-store","-q","--references",path], text=True).split()
        ref_hashes = [os.path.basename(r) for r in refs_out]
        tmp = tempfile.NamedTemporaryFile(delete=False, dir=self.cache_dir, suffix=".dump")
        try:
            subprocess.run(["nix-store","--dump",path], stdout=tmp, check=True)
            tmp.close()
            hh = hashlib.sha256()
            with open(tmp.name,"rb") as f:
                for chunk in iter(lambda: f.read(1<<20), b""): hh.update(chunk)
            nar_hash, nar_size = hh.hexdigest(), os.path.getsize(tmp.name)
            subprocess.run(["zstd","-q","-15","-f","-o",nar_file,tmp.name], check=True)
        finally:
            try: os.unlink(tmp.name)
            except OSError: pass
        info = (f"StorePath: {path}\nURL: nar/{h}.nar\nCompression: zstd\n"
                f"NarHash: sha256:{nar_hash}\nNarSize: {nar_size}\n"
                f"References: {' '.join(ref_hashes)}\n")
        with open(info_file,"w") as f: f.write(info)
        return info, nar_file

    def fetch_from_peers(self, h):
        with self.lock: peers = list(self.peers)
        for addr, port in peers:
            base = f"http://{netloc(addr, port)}"
            try:
                req = urllib.request.urlopen(f"{base}/{h}.narinfo", timeout=2)
                if req.status != 200: continue
                info = req.read().decode()
                nar_rel = None
                for line in info.splitlines():
                    if line.startswith("URL:"): nar_rel = line.split(":",1)[1].strip()
                nar_url = f"{base}/{nar_rel or ('nar/'+h+'.nar')}"
                with urllib.request.urlopen(nar_url, timeout=60) as r, \
                     open(os.path.join(self.cache_dir,h+".nar.zst"),"wb") as out:
                    shutil.copyfileobj(r, out)
                with open(os.path.join(self.cache_dir,h+".narinfo"),"w") as out:
                    out.write(info)
                return info
            except Exception:
                continue
        return None

    def heartbeat_loop(self):
        server = self.args.server_url.rstrip("/")
        while True:
            body = json.dumps({"peer_id":self.args.peer_id,"address":self.args.advertise_address,"port":self.peer_port}).encode()
            try:
                req = urllib.request.Request(f"{server}/register", data=body, headers={"Content-Type":"application/json"})
                urllib.request.urlopen(req, timeout=5).read()
            except Exception as e:
                print(f"[client] register failed: {e}", flush=True)
            time.sleep(15)

    def refresh_peers_loop(self):
        server = self.args.server_url.rstrip("/")
        while True:
            try:
                data = json.loads(urllib.request.urlopen(f"{server}/peers", timeout=5).read().decode())
                mine = (self.args.advertise_address, self.peer_port)
                fresh = [(p["address"], int(p["port"])) for p in data.get("peers",[]) if (p["address"],int(p["port"])) != mine]
                with self.lock: self.peers = fresh
                print(f"[client] known peers: {len(fresh)}", flush=True)
            except Exception as e:
                print(f"[client] refresh peers failed: {e}", flush=True)
            time.sleep(15)

    def make_handler(self):
        outer = self
        class Handler(BaseHTTPRequestHandler):
            server_version = "peer-cache-client/0.1"
            def log_message(self,*a): pass
            def _404(self): self.send_response(404); self.end_headers()
            def _file(self, path, ctype):
                if not os.path.exists(path): self._404(); return
                size = os.path.getsize(path)
                self.send_response(200)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(size))
                self.end_headers()
                if getattr(self,"_head",False): return
                with open(path,"rb") as f: shutil.copyfileobj(f, self.wfile)
            def do_HEAD(self):
                self._head = True; self.do_GET(); self._head = False
            def do_GET(self):
                self._head = False
                path = self.path.split("?",1)[0]
                if path in ("/nix-cache-info","/nix-cache-info/"):
                    info = ('{"StoreDir":"/nix/store","WantMassQuery":0,"Priority":100}\n').encode()
                    self.send_response(200)
                    self.send_header("Content-Type","application/json")
                    self.send_header("Content-Length",str(len(info)))
                    self.end_headers()
                    if not self._head: self.wfile.write(info)
                    return
                if path.endswith(".nar"):
                    h = os.path.basename(path)[:-len(".nar")]
                    self._file(os.path.join(outer.cache_dir,h+".nar.zst"),"application/x-nix-nar")
                    return
                if path.endswith(".narinfo"):
                    h = os.path.basename(path)[:-len(".narinfo")]
                    local = outer.local_path(h)
                    try:
                        info = outer.ensure_local_nar(h, local)[0] if local else outer.fetch_from_peers(h)
                    except Exception as e:
                        print(f"[client] error for {h}: {e}", flush=True); info = None
                    if not info: self._404(); return
                    body = info.encode()
                    self.send_response(200)
                    self.send_header("Content-Type","text/x-nix-cache-info")
                    self.send_header("Content-Length",str(len(body)))
                    self.end_headers()
                    if not self._head: self.wfile.write(body)
                    return
                self._404()
        return Handler

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--server-url", required=True)
    ap.add_argument("--local-port", type=int, default=8251)
    ap.add_argument("--peer-port", type=int, default=0)
    ap.add_argument("--peer-id", default=socket.gethostname())
    ap.add_argument("--advertise-address", default=None)
    ap.add_argument("--cache-dir", default=CACHE_DIR_DEFAULT)
    ap.add_argument("--bind", default="::")
    args = ap.parse_args()
    if not args.advertise_address:
        args.advertise_address = detect_global_v6()
    print(f"[client] advertise v6 = {args.advertise_address}", flush=True)
    pc = PeerCache(args)
    hc = pc.make_handler()
    psrv = V6ThreadingHTTPServer((args.bind, args.peer_port), hc)
    pc.peer_port = psrv.server_address[1]
    print(f"[client] peer-facing on {args.bind}:{pc.peer_port}", flush=True)
    threading.Thread(target=psrv.serve_forever, daemon=True).start()
    lsrv = ThreadingHTTPServer(("127.0.0.1", args.local_port), hc)
    print(f"[client] local nix cache on http://127.0.0.1:{args.local_port}/", flush=True)
    threading.Thread(target=pc.heartbeat_loop, daemon=True).start()
    threading.Thread(target=pc.refresh_peers_loop, daemon=True).start()
    lsrv.serve_forever()

if __name__ == "__main__":
    main()