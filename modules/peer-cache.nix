# peer-cache NixOS module
#
# serverMode = true  -> rendezvous server (peer table only, no files)
# default (client)  -> P2P binary cache daemon
#
# In your nixos-config:
#   inputs.peer-cache.url = "github:Aozora-Wings/nixos-peer-cache";
#   imports = [ inputs.peer-cache.nixosModules.default ];
#
#   # china-server (rendezvous):
#   services.peer-cache.enable = true;
#   services.peer-cache.serverMode = true;
#   services.peer-cache.serverPort = 8250;
#
#   # other nodes (client):
#   services.peer-cache.enable = true;
#   services.peer-cache.serverUrl = "https://peer-cache.qkzy.net";
{ peer-cache-pkg }:
{ config, lib, pkgs, ... }:
let
  cfg = config.services.peer-cache;
  pkg = peer-cache-pkg;
in
{
  options.services.peer-cache = {
    enable = lib.mkEnableOption "NixOS P2P binary cache";

    serverMode = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = "true=rendezvous server; false=cache client.";
    };

    serverPort = lib.mkOption {
      type = lib.types.port;
      default = 8250;
      description = "rendezvous listen port in serverMode.";
    };

    serverUrl = lib.mkOption {
      type = lib.types.str;
      default = "";
      description = "rendezvous URL for client mode.";
    };

    localPort = lib.mkOption {
      type = lib.types.port;
      default = 8251;
      description = "fixed local port written into nix.conf.";
    };

    peerId = lib.mkOption {
      type = lib.types.str;
      default = config.networking.hostName;
      description = "node name reported to rendezvous.";
    };

    advertiseAddress = lib.mkOption {
      type = lib.types.nullOr lib.types.str;
      default = null;
      description = "advertised v6 address; null=auto-detect.";
    };

    cacheDir = lib.mkOption {
      type = lib.types.path;
      default = "/var/cache/peer-cache";
      description = "directory for generated narinfo/nar.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [ pkg ];

    # ---------- rendezvous server ----------
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
        ExecStart = lib.concatStringsSep " " ([
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
        Environment = "PATH=/run/current-system/sw/bin:${pkgs.nix}/bin:${pkgs.zstd}/bin:/bin";
      };
    };

    nix.settings = lib.mkIf (!cfg.serverMode) {
      extraSubstituters = [ "http://127.0.0.1:${toString cfg.localPort}/" ];
      "require-sigs" = false;
    };
  };
}
