{
  description = "peer-cache：NixOS 节点间的 P2P binary cache（rendezvous + 透明 pull-through）";

  # 与 nixos-config 一致：nixpkgs 走南大镜像，避免境内 GitHub 直连不稳。
  inputs.nixpkgs.url =
    "git+https://mirrors.nju.edu.cn/git/nixpkgs.git?ref=nixos-unstable&shallow=1";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
    in {
      packages.${system}.peer-cache = pkgs.callPackage ./pkgs { };

      nixosModules.default = import ./modules/peer-cache.nix;
    };
}
