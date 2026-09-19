# peer-cache NixOS 模块
#
# 两种模式：
#   serverMode = true  -> 跑集合点（rendezvous），只维护在线 peer 表，不存文件。
#   默认（client）     -> 跑 P2P binary cache daemon，并把本机加进 P2P 网络。
#
# 在你的 nixos-config 里：
#   inputs.peer-cache.url = "github:你的用户名/peer-cache";   # 或本地 path:
#   imports = [ inputs.peer-cache.nixosModules.default ];
#
#   # 服务器节点（china-server）：
#   services.peer-cache.enable = true;
#   services.peer-cache.serverMode = true;
#   services.peer-cache.serverPort = 8250;
#
#   # 其它节点（本机 / WSL / 别的服务器）：
#   services.peer-cache.enable = true;
#   services.peer-cache.serverUrl = "http://china-server.qkzy.net:8250";
{ pkgs }:
{ config, lib, ... }:
let
  cfg = config.services.peer-cache;
  pkg = pkgs.callPackage ../../pkgs { };
in
{
  options.services.peer-cache = {
    enable = lib.mkEnableOption "NixOS P2P binary cache";

    serverMode = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "true=作为集合点服务器（rendezvous）；false=作为 cache client。";
    };

    serverPort = lib.mkOption {
      type = lib.types.port;
      default = 8250;
      description = "serverMode 下 rendezvous 监听端口。";
    };

    serverUrl = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "client 模式下的 rendezvous 地址，如 http://china-server.qkzy.net:8250。";
    };

    localPort = lib.mkOption {
      type = lib.types.port;
      default = 8251;
      description = "client 模式下本机 nix 连接的固定端口（写进 nix.conf）。";
    };

    peerId = lib.mkOption {
      type = lib.types.str;
      default = config.networking.hostName;
      description = "上报给 rendezvous 的节点名。";
    };

    advertiseAddress = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "上报的 v6 地址；null=自动探测全局/ULA v6。";
    };

    cacheDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/cache/peer-cache";
      description = "缓存生成的 narinfo / nar 的目录。";
    };
  };

  config = lib.mkIf cfg.enable {
    # 所有节点共用：nix / zstd 在 PATH 里（client 调 nix-store|zstd）
    environment.systemPackages = [ pkg ];

    # ---------- 集合点服务器 ----------
    systemd.services.peer-cache-rendezvous = lib.mkIf cfg.serverMode {
      description = "peer-cache rendezvous server";
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        ExecStart = "${pkg}/bin/peer-cache-server --host 0.0.0.0 --port ${toString cfg.serverPort}";
        Restart = "on-failure";
        RestartSec = 2;
      };
    };

    # ---------- P2P cache client ----------
    systemd.services.peer-cache = lib.mkIf (!cfg.serverMode) {
      description = "peer-cache P2P binary cache";
      wantedBy = [ "multi-user.target" ];
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      serviceConfig = {
        ExecStart = concatStringsSep " " ([
          "${pkg}/bin/peer-cache-client"
          "--server-url ${cfg.serverUrl}"
          "--local-port ${toString cfg.localPort}"
          "--peer-id ${cfg.peerId}"
          "--cache-dir ${cfg.cacheDir}"
        ] ++ lib.optionals (cfg.advertiseAddress != null) [
          "--advertise-address ${cfg.advertiseAddress}"
        ]);
        Restart = "on-failure";
        RestartSec = 2;
        CacheDirectory = "peer-cache";
        # nix-store 在 /run/current-system/sw/bin；zstd 走包
        Environment = "PATH=/run/current-system/sw/bin:${pkgs.nix}/bin:${pkgs.zstd}/bin:/bin";
      };
    };

    # 把本机 daemon 加进 substituters（追加：先试你已有的 tuna/ustc/cache.nixos.org，
    # 它们 miss 的（通常是你自己机器上 build 的派生）才落到 P2P。
    nix.settings = lib.mkIf (!cfg.serverMode) {
      extraSubstituters = [ "http://127.0.0.1:${toString cfg.localPort}/" ];
      # 本 cache 不做签名；narHash 仍校验内容，陌生人塞不了木马。
      # cache.nixos.org 等有签名的源依旧会验签。
      require-sigs = false;
    };
  };
}
