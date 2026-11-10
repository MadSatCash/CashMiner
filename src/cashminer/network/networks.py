"""Identidades de red explícitas: un magic P2P NO prueba identidad de cadena."""
from dataclasses import dataclass


@dataclass(frozen=True)
class Network:
    name: str
    magic_hex: str
    default_port: int
    seeds: tuple[str, ...]
    bootstrap: tuple[str, ...] = ()
    identifier: str = ""
    identity_locator: str = ""  # checkpoint público; vacío = sin verificación disponible
    identity_first_hash: str = ""  # primera cabecera inmediatamente posterior al checkpoint

    @property
    def magic(self) -> bytes:
        return bytes.fromhex(self.magic_hex)


NETWORKS: dict[str, Network] = {
    "mainnet": Network("mainnet", "e3e1f3e8", 8333,
                       ("seed.bch.loping.net", "dnsseed.electroncash.de", "seed.bchd.cash"),
                       identifier="bch-mainnet"),
    "testnet3": Network("testnet3", "f4e5f3f4", 18333,
                        ("seed.tbch.loping.net", "testnet-seed.bchd.cash"),
                        identifier="bch-testnet3"),
    "testnet4": Network("testnet4", "e2b7daaf", 28333,
                        ("testnet4-seed-bch.toom.im", "seed.tbch4.loping.net"),
                        identifier="bch-testnet4"),
    "chipnet": Network("chipnet", "e2b7daaf", 48333,
                       ("chipnet.bitjson.com", "seed.cbch.loping.net"),
                       identifier="bch-chipnet-fork-115252-00000000040ba964"),
    "tempnet_fablous_2026": Network(
        "tempnet_fablous_2026", "e2b7daaf", 48333, (),
        ("15.204.253.47:48335", "15.204.228.134:48333", "135.148.26.244:48333"),
        identifier="bch-tempnet-fablous-fork-327989-00000000e18af2c6",
        # Mismos puntos de control públicos que cashminer_fablous.py del motor.
        identity_locator="00000000000002bcc82b979f71d827d7788c84b981975101cb9e415ace23c46c",
        identity_first_hash="00000000e18af2c66d44a1bbfe165acc4b87a625d211a09e33d5ee61d35dcb66"),
    "regtest": Network("regtest", "dab5bffa", 18444, (),
                       identifier="bch-regtest-local-only"),
}


def get_network(name: str) -> Network:
    return NETWORKS[name]
