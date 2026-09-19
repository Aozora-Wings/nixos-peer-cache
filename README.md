# peer-cache

NixOS 节点之间的 **P2P binary cache**：多台机器（本地/WSL/服务器）在同一个 IPv6 网络里，
某台机器 build 出的包，其它机器不用再走官方 CDN，直接通过本地 v6 网络从有这台包的 peer 拉过来。

## 它是怎么工作的

```
   peer A (要包)                     rendezvous (一台常开机器)
       |                                    |
       | 1. 谁有 hash H？-------------------->|
       |<------- 在线 peer 列表 -----------|
       |                                    |
       | 2. 直连 peer B 的 [v6]:随机端口     |
       |---- GET /H.narinfo -------------->| (peer B)
       |<---- zstd NAR -------------------|
       | 3. nix 校验 narHash，导入
```

- **集合点服务器**（`serverMode = true`）：只维护在线 peer 表（地址+端口+心跳），不传文件，纯 Python 标准库，几百行。
- **cache client**（每个节点）：
  - 本机 nix 连固定端口 `http://127.0.0.1:8251/`（写进 `extraSubstituters`）；
  - 对外绑 `[::]:0` 随机端口，实际端口上报给集合点；
  - 本机有该包 → 现场 `nix-store --dump | zstd` 生成 NAR；本机没有 → 问列表里的 peer，谁有就拉回缓存；
  - nix 导入前自动校验 `narHash`，陌生人塞不了木马。

## 配置（在你的 nixos-config 里）

```nix
{
  inputs.peer-cache.url = "github:你的用户名/peer-cache";  # 或 path:/…
  # inputs.nixpkgs 走南大/清华镜像（与你现有一致）

  # 在任意节点的 configuration 里：
  imports = [ inputs.peer-cache.nixosModules.default ];

  # —— 集合点（china-server，一台常开机器即可）——
  services.peer-cache.enable = true;
  services.peer-cache.serverMode = true;
  services.peer-cache.serverPort = 8250;

  # —— 其它所有节点（本机 / WSL / 别的服务器）——
  services.peer-cache.enable = true;
  services.peer-cache.serverUrl = "http://china-server.qkzy.net:8250";
  # 多数情况不用设 advertiseAddress，自动探测全局 v6；
  # 若自动选错了地址再显式给：
  # services.peer-cache.advertiseAddress = "2408:xxxx::1";
}
```

节点间走 **IPv6 直连**（你那几台 v6 同网）；服务器只有 v4 也没关系——
它只当电话簿，数据不经过它。

## 几个注意点

- **入站 v6 防火墙**：peer 之间直连，需要路由器允许入站 v6 到 client 的随机端口
  （或对 client 端口段放行）。集合点本身只在服务器上开一个固定端口。
- **签名**：本 cache 不签名，模块会设 `require-sigs = false`。`cache.nixos.org` 等有签名的源
  仍会验签；本 cache 的内容由 `narHash` 保证未被篡改。
- **substituters 顺序**：本机 daemon 是追加（`extraSubstituters`），先试你已有的
  tuna/ustc/cache.nixos.org，它们没有的（通常是你自己机器 build 的派生）才落到 P2P。
- **缓存**：生成的 narinfo/nar 存在 `/var/cache/peer-cache/`，不会每次重复 dump。

## 开发/手动跑（不用 nixos-rebuild）

```bash
# 集合点
python3 pkgs/peer-cache/server.py --port 8250

# client（本机 nix 连 127.0.0.1:8251，对外随机端口）
python3 pkgs/peer-cache/client.py \
  --server-url http://127.0.0.1:8250 \
  --local-port 8251 --cache-dir /tmp/peer-cache
```

验证（绕过本机 HTTP 代理）：
```bash
no_proxy=127.0.0.1 nix copy --from http://127.0.0.1:8251/ \
  --option require-sigs false /nix/store/<某路径>
```
