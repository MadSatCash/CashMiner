# Validation — v2.18.4

- Shared suite passed 636 tests, with 9 skipped.
- Windows ZIP and extracted package matched all 321 file hashes in the build
  manifest. The launcher metadata and packaged local API report 2.18.4.
- With synthetic wallets, a synced wallet could prepare 40,000 sats while
  another wallet was stale. The regression tests also cover the largest
  valid fungible CashToken amount and keep token outputs out of BCH sends.
- The signed APK installed over v2.18.3 in an Android 13 x86-64 emulator.
  A synthetic Regtest wallet remained available and its recovery phrase still
  derived the same address. Keystore, synthetic transaction signing and
  native hashing self-tests passed.

---

# Validation — v2.18.3

- Shared suite passed 635 tests, with 9 skipped.
- The Windows launcher and the Android 13 x86-64 emulator imported a synthetic
  Testnet3 wallet against two local TLS Electrum fixtures. The first scan
  checked 58 addresses and reported discovery and verification progress. After
  a forced disconnect, the cached balance was marked outdated and reverified
  through the second server without requesting unchanged history or outputs.
- The shared UI strings for discovery, verification, saving, and reconnecting
  were checked in Spanish and English.
- The emulator accepted the APK over v2.18.2. The package kept the same signing
  certificate and passed the Android Keystore, wallet recovery, signing and
  native hashing self-tests. Testing used an emulator and synthetic funds.
- All 321 Windows manifest file hashes and both distribution checksums matched.

---

# Validation — v2.18.2

- Full shared suite: 642 tests, no failures/errors, 9 skipped. Optional hardware
  and BCHN groups were not enabled for this UI update.
- After the final empty-wallet instruction change: 9 i18n and 26 UI tests passed.
- Ten WIF/wallet HTTP tests passed using the Windows package's Python and sources.
- Isolated browser checks: general menu opens the same options; show/hide works
  for hexadecimal and WIF by mouse and keyboard. Toggling preserves the key value
  and enabled address preview; changing format resets visibility and closing
  clears the field. Spanish/English labels checked. At 390px, both 44px buttons
  remain in bounds, with no horizontal overflow. No console warnings/errors.
- Android original certificate, payload and version verified; DEX/native/resources
  unchanged. This APK still needs owner testing on a phone.

Automated checks used public test keys and temporary data, without payments.
Windows startup/shutdown and all 321 manifest files were verified. The owner
confirmed successful WIF import during Windows testing. The 2.18.1 checks below
describe the earlier local candidate; it was not published separately.

---

# Validation — v2.18.1 (local candidate)

- Full shared suite: 642 tests, no failures/errors, 9 skipped. Optional hardware
  and BCHN groups were not enabled for this wallet/UI update.
- Public scalar-1 compressed/uncompressed WIF vectors, all six supported chains,
  hexadecimal equivalence, recovery, duplicate detection and compression flags.
  Rejects checksum/character/length/network/prefix/compression/scalar errors,
  conflicting recovery formats, missing confirmation and wrong address.
- Authenticated loopback HTTP preview/import, compression override prevention
  and wrong-network rejection; no secret in normal state/preview responses.
- Ten wallet/WIF tests also passed using the shipped Windows Python/application.
- Browser integration with a temporary data directory and disabled wallet sync:
  complete WIF preview/confirmation/import, incorrect-checksum error, Spanish and
  English strings, information buttons and Escape, 1100px desktop and 390px
  mobile layout. No horizontal overflow at 390px and no console warnings/errors.
- Windows EXE startup, API 2.18.1, static assets, hardware inventory and normal
  shutdown passed with isolated data. Delivered manifest hashes stayed unchanged.
- Android manifest, original certificate and payload verified; 32 DEX/native/
  resource entries unchanged. This APK has not been tested on a phone/emulator.

No real wallet keys, payments or broadcasts were used for these checks. The
user's installation/data are unchanged. Owner package testing precedes push and
publication. Prior mining/consensus evidence below is historical, not rerun.

---

# Validation — v2.18

The 2.18 shared source suite completed 635 tests without failures/errors,
with 7 skips and both BCHN optional groups enabled. Fourteen focused Chipnet
checks were subsequently rerun without failures. The changes include:

- Replay of 9,467 post-checkpoint headers across activation; 9,967 matching
  comparisons against compiled BCHN ASERT arithmetic, retaining 600 vectors.
- Branch context, cache revalidation, strict minimum-difficulty thresholds,
  halvings, coinbase construction and wallet maturity/selection boundaries.
- An isolated BCHN chain accepting a CashMiner-built block and rejecting a
  coinbase spend at 100/999 confirmations, accepting it at 1,000.
- Live Chipnet native/assisted connections and independent server comparisons.
- Windows ZIP: 322 files verified before/after; CPU, OpenCL and CUDA shares
  checked by independent local Stratum; ranking process and EXE startup/API 2.18/
  resources/normal shutdown checked with isolated data.
- Android signature, version and payload verified; 32 DEX/native/resource entries
  unchanged. This new APK was not tested on a phone/emulator.

The owner ran Windows Chipnet mining with CUDA/OpenCL after packaging. Logs
showed hashing and template changes, not a confirmed self-mined public block.
A public Chipnet block mined and accepted from 2.18 remains untested. Header
verification is not full transaction/script/UTXO validation. Improvements to
send latency and GPU batch scheduling remain deferred.

[Details](releases/NOTAS_V2.18.md) · [Artifact provenance](ARTIFACTS.md).

---

## Historical validation — v2.17.1

# Validation / Validación

## Windows candidate, 2026-11-10

The general suite ran with the bundled CPython 3.14.10 and dependencies:
**606 tests, 0 failures, 0 errors, 5 skipped**, about 120 seconds. Tests combine
fixtures, local protocol servers and opt-in hardware/node checks. This does
not establish identical coverage on all networks, hardware or operating systems.

The extracted ZIP was checked with Python removed from PATH and invalid
PYTHONPATH/PYTHONHOME values. Independent local Stratum validation accepted
shares produced by real CPU, Intel OpenCL and NVIDIA CUDA miner subprocesses.
The separate ranking process and ZIP file hashes were also checked.

The automated GUI check timed out while discovering the child listener port;
the visual automation tool could not confidently identify the app-browser URL.
Those are unresolved verification limitations, not evidence of a confirmed GUI
product defect. The author subsequently reported successful manual startup
and ran a short simultaneous Testnet3/FABLOUS trial on 2026-11-10. The local
miner logs record nine Testnet3 proof-of-work solutions and one FABLOUS
solution (height 364992), whose header was then announced by three peers.
The counters matched these logs. This is evidence from a short real mining
trial, not full-block validation or a completed long-duration stability test.

Coverage not established: automated startup/normal shutdown and clean Windows
installation. This experimental release has no installer or publisher signature.
Publication refreshed the Windows MIT/vendor notices and manifest only;
executable, DLLs and application sources match the tested candidate. These results describe the retained
Windows ZIP, not the Android package below. Linux/macOS/iOS remain deferred.

## Android APK 2170105, 2026-11-10

- Version 2.17.1, package `org.cashminer.android`, versionCode 2170105. Source:
  `b5b487332006bb2d7f764de6e07795608ff05cfc`. Previous signing certificate retained.
- Eighteen focused tests passed: eight Android controller, two shared defaults/
  migration, five desktop device defaults and three internal CPU duty checks.
- Android 15 x86-64 emulator: Testnet3 and Testnet4 sessions ran simultaneously
  against independent local Stratum share verifiers, producing 29 and 41 valid
  shares. They continued after Home with separate notifications. Stopping
  Testnet3 left Testnet4 mining. These are controlled protocol tests, not public
  Testnet3/Testnet4 blocks.
- Save As through Android's document picker produced 8,962 bytes identical to
  the full original log. The picker may append `.txt` to its `.log` filename.
- Release build, vital lint, APK signature/ABIs and installation as an update
  passed. Final DEX/native/manifest and inner payload contents matched the tested
  APK; native libraries were unchanged.
- The owner subsequently reported finding and checking a Testnet3 block on
  their physical Android phone. Earlier phone testing also showed the reward
  in a PC wallet for the same key. This is owner-reported physical-device
  evidence, distinct from the controlled tests; a full log of the latest block
  was not independently reviewed in this packaging step.

This does not establish all-device/all-network coverage or indefinite background
uptime. Android uses CPU only and Keystore; its cryptography 42.0.8 dependency
differs from Windows and still needs review before a stable wallet release.
The complete Windows suite was not repeated for this documentation/upload step.

## Reproduce tests

Use an isolated checkout/data directory and install the runtime requirements
plus Pillow for visual asset tests. From the repository root:

```powershell
$env:PYTHONPATH = "$PWD\src"
python -X utf8 -m unittest discover -s tests
```

For native OpenCL checks, set `CASHMINER_TEST_OPENCL=1` on a Windows machine
with compatible GPUs. For real BCHN Regtest checks, also set
`CASHMINER_TEST_BCHN_DIR` to a directory containing `bitcoind.exe` and
`bitcoin-cli.exe`. Tests create local temporary nodes; do not point them at
your normal node data or expose their RPC ports publicly. BCHN is not bundled.
See the test module docstrings for prerequisites and scope.

## Español

La suite Windows ejecutó **606 pruebas, sin fallos ni errores y con 5 omitidas**
con el Python del paquete. Se comprobaron shares reales de CPU/OpenCL/CUDA
contra un servidor Stratum local y el proceso separado de ranking.

El comprobador automático de GUI agotó el plazo buscando el puerto del hijo;
la automatización visual se detuvo al no identificar con certeza la URL.
El autor informó después que abrió correctamente y realizó una prueba corta
simultánea de Testnet3 y FABLOUS el 10/11/2026. Los logs locales registraron
nueve soluciones PoW de Testnet3 y una de FABLOUS (altura 364992), cuya cabecera
fue anunciada después por tres peers. Los contadores coincidieron con los logs.
Es evidencia de minería real breve, no validación completa de bloques ni una
prueba prolongada de estabilidad terminada.

No se completó la comprobación automática de inicio/cierre ni Windows limpio.
Esta publicación experimental no incluye instalador ni firma del editor. Se
actualizaron licencias/avisos y manifiesto, conservando los archivos del programa. Para
reproducir, usá datos aislados y los comandos anteriores. Las pruebas GPU y
BCHN son optativas y requieren hardware/binarios externos compatibles.

La APK Android 2170105 pasó 18 pruebas específicas y ensayos en emulador de dos
redes simultáneas, segundo plano, detención independiente y exportación completa
del log. Los verificadores Stratum locales aceptaron 29 y 41 shares; no son
bloques de redes públicas. El propietario informó después que encontró y comprobó
un bloque de Testnet3 en su teléfono. No se revisó independientemente su log
completo en esta tarea. No implica cobertura de todos los equipos/redes ni
continuidad indefinida. Sigue pendiente revisar la dependencia criptográfica
móvil para una publicación estable. Linux, macOS e iOS quedan para después.
