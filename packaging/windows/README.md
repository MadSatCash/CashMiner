# Windows x64 ZIP build / Compilación ZIP Windows x64

This build bundles official CPython 3.14.10 embedded x64, pinned wheels and
the unchanged CashMiner 2.17.1 runtime sources/native DLLs. A small native
Win32 launcher opens the private pythonw.exe using absolute sibling paths.
No Python installation, PATH entry, pip or administrator rights are needed
to run the resulting ZIP. GPU drivers and an installed browser remain external.

El paquete usa un Python privado, aislado de PYTHONPATH, PYTHONHOME y del
site-packages del usuario. El minero, ranking y detector de hardware utilizan
ese mismo Python. Los datos siguen en el directorio habitual de CashMiner;
el ZIP distribuye el programa, no los datos personales.

## Build requirements / Requisitos para compilar

- Windows x64; Python 3.10+ with pip for the build machine only.
- MSYS2 MinGW x64 GCC and windres. Default: C:/msys64/mingw64/bin.
- Matching CRT/GCC license files under mingw64/share/licenses.
- Internet on first build; exact downloads verified with SHA-256.

From Codigo_fuente, use PowerShell:

```powershell
python packaging/windows/build.py --work "$env:TEMP/cashminer-build-NUEVO" --output "C:/ruta/entrega"
```

Use a new dedicated temporary directory. Existing staged builds/output ZIPs
are deliberately not overwritten. The build never installs Python/packages
globally and does not change application data. Remove only the dedicated
temporary directory after closing its processes and saving results.

The output is CashMiner-Windows.zip, containing a CashMiner/ directory:
CashMiner.exe, _internal/python, _internal/app, notices and BUILD_MANIFEST.json.
The manifest records the compiler, runtime/wheel versions and hashes of every
delivered file. wheels.lock.json pins every wheel URL/hash; no dependency
resolution is performed when that lock already exists.

The launcher is not publisher-signed; no installer or updater is included.
Project code is MIT. The release includes LICENSE and third-party notices,
including the retained CUDA 12.8 runtime license. Original CPU/CUDA compiler
flags are not fully recorded; see THIRD_PARTY_NOTICES.md. The tested Windows
runtime is retained; publication refreshes license documents and the manifest.

## Integration checks / Comprobaciones

Run verify_package.py with the Python contained in an independently extracted
ZIP. --package points to its CashMiner folder; --work is disposable; --source
points to Codigo_fuente. It verifies hashes and starts real miner subprocesses
against the existing local Stratum simulator/share validator for CPU and every
available supported GPU. It also checks the separate ranking worker.

With --gui, it opens the actual launcher using isolated data, checks the local
HTML/assets/state/hardware endpoints and waits up to 180 seconds for a file
named gui-inspected inside --work. Create that file after observing the window;
the check then sends authenticated shutdown and verifies clean application logs.
No real wallet or public mining pool is used in these checks.

Pillow is only a development dependency for the existing visual asset tests;
it is not required by the application and is not included in the ZIP.
