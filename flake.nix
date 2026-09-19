{
  description = "peer-cache: NixOS P2P binary cache (rendezvous + pull-through client)";

  inputs.nixpkgs.url =
    "git+https://mirrors.nju.edu.cn/git/nixpkgs.git?ref=nixos-unstable&shallow=1";

  outputs = { self, nixpkgs }:
    let
      system = "x86_64-linux";
      pkgs = import nixpkgs { inherit system; };
      peer-cache-pkg = pkgs.callPackage ./pkgs { };
    in {
      packages.${system}.peer-cache = peer-cache-pkg;

      nixosModules.default = import ./modules/peer-cache.nix { inherit peer-cache-pkg; };
    };
}
