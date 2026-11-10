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
and began a mining trial; this is not yet a completed stability test.

Still pending before final distribution: automated startup/normal shutdown,
clean Windows installation, installer, signing/distribution decisions and final
native toolchain/redistribution notices. No Android/Linux/macOS/iOS package
has been validated by this release.

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
El autor informó después que abrió correctamente y comenzó una prueba manual
de minería. Eso no equivale a una prueba prolongada de estabilidad terminada.

Siguen pendientes el cierre de la comprobación automática de inicio/cierre,
Windows limpio, instalador y los detalles finales de distribución. Para
reproducir, usá datos aislados y los comandos anteriores. Las pruebas GPU y
BCHN son optativas y requieren hardware/binarios externos compatibles.
