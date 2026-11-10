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
