# CashMiner

**Experimental Bitcoin Cash wallet, miner and peer explorer.**

[Español](README.es.md) · Version **2.17.1** · [License](LICENSE)

CashMiner is a lightweight desktop project by CashRider for mining, learning
and experimenting with Bitcoin Cash. It combines wallet tools, a shared
CPU/CUDA/OpenCL hashing engine and peer exploration across BCH networks.

## Current status

Windows x64 is the first packaged target. The repository is being prepared
for its first public experimental release. The Windows ZIP is currently a
test candidate; the installer is not available yet. Android, Linux, macOS
and iOS packages are not provided by this release.

## Features

- Mining with CPU, NVIDIA CUDA and compatible OpenCL GPUs.
- Direct P2P mining with native header verification; assisted Electrum
  reference remains selectable where implemented.
- RPC mining using a configured BCH node (`getblocktemplate` / `submitblock`).
- Stratum V1 mining using a compatible configured pool.
- Independent mining sessions for Mainnet, Testnet3, Testnet4, Chipnet,
  FABLOUS Tempnet 2026 and local Regtest, subject to each network's requirements.
- Wallets, HD address derivation, local transaction signing, Electrum
  synchronization, recovery tools and backups.
- Per-network SQLite peer observations, Peer Explorer and a background
  precalculated ranking for initial mining candidates.
- Per-network P2P sources: DNS, SQLite or both.

## Run the Windows ZIP

When a release asset is available, download **CashMiner-Windows.zip** from
[Releases](https://github.com/MadSatCash/CashMiner/releases). Extract the
**entire ZIP** and open `CashMiner/CashMiner.exe`.

Keep `_internal`, the license files and the other packaged files beside the
executable. Python is included; no separate Python installation is needed.

Target: Windows 10/11 x64 on Intel/AMD. The candidate has been tested on
Windows 11; a clean Windows installation check is still pending. Compatible
GPU drivers remain necessary for CUDA/OpenCL. The existing UI uses an
installed browser (Edge/Chrome/Brave preferred). The launcher is not
publisher-signed. If Windows reports a missing `VCRUNTIME140.dll`, use the
official Microsoft Visual C++ Redistributable x64.

Do not run tests or development copies against your live wallet data. Running
two copies normally uses the same data directory; they are not isolated wallets.

## Run from source on Windows

Use Python 3.10+ and a terminal in the repository root:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe CashMiner.pyw
```

This source checkout includes the three Windows x64 hashing DLLs, their
sources and checksums under `native/`. The Python package alone does not
include the complete desktop application: run from the complete checkout.

To build the standalone Windows ZIP, see
[packaging/windows/README.md](packaging/windows/README.md).

## Data and recovery

Program files and personal data are separate. On Windows the normal data
directory is `%LOCALAPPDATA%/CashMiner`; an existing `%LOCALAPPDATA%/CashMiner2`
installation may continue to be used for compatibility. Startup does not
silently migrate or copy wallets.

Wallet protection uses Windows DPAPI. Preserve recovery phrases and backups;
copying an encrypted vault to a different Windows account/computer is not a
replacement for recovery. Never share recovery phrases, private keys, vaults
or RPC/pool passwords in issues. See [migration](docs/MIGRATION.md).

For isolated development, set `CASHMINER_DATA_DIR` to a separate empty folder
before starting the application. The Windows ZIP does not contain user data.

## Experimental limits

- Native P2P verifies headers from checkpoints; it is **not full-block or
  full-node consensus validation**. The native P2P builder currently produces
  coinbase-only blocks, without mempool transactions/fees.
- Native P2P does not require your own full node. Wallet synchronization
  still uses Electrum servers; RPC requires your own or an authorized node.
- A found proof of work, a transmitted block and an observed chain inclusion
  are different results. None alone guarantees a spendable reward.
- Backend/protocol validation coverage varies by network and hardware.
- Candidates are selected initially; dynamic candidate refresh while mining
  is not implemented. Rankings can lag behind observations.
- FABLOUS Tempnet mining has a programmed cutoff at **2026-11-15 12:00 UTC**.
  Future Chipnet consensus changes are not automatically supported.
- This is experimental software, intended for learning and testing. CPU/GPU
  mining should not be treated as a promise of profitability.

## Development and checks

The runtime requires `cryptography`; the Windows bundle also includes
`psutil` for hardware/process support. Pillow is a test-only requirement for
visual asset checks. Standard-library SQLite is used for application data.

```powershell
.venv\Scripts\python.exe -m pip install Pillow
$env:PYTHONPATH = "$PWD\src"
.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
```

GPU and real-node tests are opt-in. Use isolated data and see
[validation notes](docs/VALIDATION.md) before enabling them.

## Documentation and license

- [Architecture / Arquitectura](docs/ARCHITECTURE.md)
- [Migration / Migración](docs/MIGRATION.md)
- [Validation / Validación](docs/VALIDATION.md)
- [Release notes / Notas de versión](docs/RELEASE_NOTES.md)
- [Third-party notices](THIRD_PARTY_NOTICES.md)
- [Acknowledgements / Agradecimientos](ACKNOWLEDGEMENTS.md)

CashRider's project code is released under the [MIT License](LICENSE).
Third-party components retain their own licenses and notices. GPU drivers,
SDKs and other vendor components are not relicensed by the project license.
