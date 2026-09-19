# 把 client.py / server.py 打进 /nix/store，并生成两个可执行 wrapper。
# 纯 Python 标准库，无第三方依赖；运行时只依赖系统已有的 python3 / nix-store / zstd。
{ pkgs }:
let
  src = ./peer-cache;

  libdir = pkgs.runCommand "peer-cache-lib" { } ''
    mkdir -p $out
    cp ${src}/client.py $out/client.py
    cp ${src}/server.py $out/server.py
  '';

  mkBin = name: script:
    pkgs.writeShellScriptBin name ''
      # 由 systemd 服务注入 PATH（含 nix-store / zstd），这里只兜底带上 python。
      exec ${pkgs.python3}/bin/python3 ${libdir}/${script} "$@"
    '';
in
pkgs.symlinkJoin {
  name = "peer-cache";
  paths = [
    (mkBin "peer-cache-server" "server.py")
    (mkBin "peer-cache-client" "client.py")
  ];
}
