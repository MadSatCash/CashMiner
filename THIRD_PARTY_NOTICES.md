# Third-party notices / Avisos de terceros

The project MIT license applies to CashRider's code. It does not replace
third-party licenses. Los componentes de terceros conservan sus licencias.

## Included resources / Recursos incorporados

### QRCode.js — MIT

Copyright (c) 2012 davidshimjs and contributors.
Underlying QRCode for JavaScript: Copyright (c) 2009 Kazuhiko Arase.

- Source: https://github.com/davidshimjs/qrcodejs
- File: `ui/vendor/qrcode.min.js`
- SHA-256: `c541ef06327885a8415bca8df6071e14189b4855336def4f36db54bde8484f36`
- Upstream Git blob: `993e88f396640f881b69f98db7a4d17401ef83ca`
- License text: [ui/vendor/LICENSE-qrcodejs.txt](ui/vendor/LICENSE-qrcodejs.txt)

### BIP39 English word list — MIT

Authors: Marek Palatinus, Pavol Rusnak, Aaron Voisine and Sean Bowe.

- Source: https://github.com/bitcoin/bips/blob/master/bip-0039/english.txt
- Specification/license: https://github.com/bitcoin/bips/blob/master/bip-0039.mediawiki
- File: `src/cashminer/wallet/bip39_english.txt`
- SHA-256: `2f5eed53a4727b4bf8880d8f3f199efc90e58503646d9ff8eff3a2ed3b24dbda`
- License text: [bip39_LICENSE.txt](src/cashminer/wallet/bip39_LICENSE.txt)

## Runtime dependencies / Dependencias

- **PyCA cryptography** (required; package declares >=41):
  https://github.com/pyca/cryptography — Apache-2.0 OR BSD-3-Clause.
  The Windows candidate pins 50.0.2. Its wheel includes OpenSSL and relevant
  notices. It performs secp256k1 signing and other cryptographic primitives.
- **psutil** (optional in source; included in Windows candidate at 7.2.2):
  https://github.com/giampaolo/psutil — BSD-3-Clause.
- **cffi** and **pycparser** (transitive dependencies of the pinned wheel set):
  https://cffi.readthedocs.io/ — MIT; https://github.com/eliben/pycparser — BSD-3-Clause.
  Exact versions, download URLs and hashes: `packaging/windows/wheels.lock.json`.
- **CPython embedded x64 3.14.10**, Windows package only:
  https://www.python.org/downloads/release/python-31410/ — PSF license and
  included component notices. No Python distribution is committed here.

Android uses Chaquopy 17.2.0, its CPython 3.11 runtime, cryptography 42.0.8,
cffi 1.17.1, pycparser 3.12 and chaquopy-libffi 3.3. Their versions, upstreams
and licenses are listed in [Android notices](packaging/android/ANDROID_NOTICES.md),
with redistribution texts under `packaging/android/licenses` and notices in the
embedded runtime/wheels. The SDK, NDK, JDK, Gradle and emulator are build tools,
not release assets. Android WebView is supplied by the operating system.

The Windows build collects installed wheel license/notice files, CPython
notices and MinGW CRT/GCC runtime notices in its `Licenses/` directory.
The native launcher is built using GCC/MinGW; applicable runtime exceptions
and CRT notices remain in force. No compiler or SDK is shipped in the ZIP.

El build Windows incorpora los avisos de CPython, wheels y runtime MinGW/GCC.
Los drivers CUDA/OpenCL no se incluyen y conservan las condiciones del proveedor.

## Optional legacy integrations / Integraciones heredadas opcionales

`psycopg` / `psycopg2` imports remain in the standalone mining engine for
legacy PostgreSQL use. The current GUI uses SQLite and removes the PostgreSQL
DSN from its miner environment. These packages are not included in the pinned
Windows candidate. If distributed, preserve their own license/exceptions:
https://www.psycopg.org/license/

## Native hashing / Hashing nativo

The three `native/*.dll` files and corresponding C/CUDA sources originate
from the author's `cashminer_app` project. Their current SHA-256 values are
listed in [native/SHA256SUMS.txt](native/SHA256SUMS.txt).

The CUDA DLL reports CUDA Runtime **12.8** (`cudaRuntimeGetVersion=12080`).
Its PE header reports linker 14.50; it incorporates the CUDA runtime and imports
Windows/Visual C++ runtime APIs. The CUDA 12.8 license text is retained in
[packaging/windows/licenses/NVIDIA-CUDA-12.8-EULA.txt](packaging/windows/licenses/NVIDIA-CUDA-12.8-EULA.txt)
and included in the Windows ZIP's `Licenses/` directory. The NVIDIA driver is
external, as is the OpenCL implementation supplied by the user's GPU driver.
See the [CUDA 12.8 EULA](https://docs.nvidia.com/cuda/archive/12.8.0/eula/index.html).

The CPU DLL imports Windows KERNEL32/MSVCRT; the OpenCL DLL additionally imports
OpenCL.dll. MinGW/GCC runtime notices and exceptions accompany the Windows ZIP.
The exact original CPU/CUDA compiler commands and flags were not recovered;
these are retained author-built binaries, not a claim of a reproducible rebuild.
The OpenCL build script records its compiler/SDK inputs. DLL hashes are unchanged
from the hardware-tested candidate and are listed under `native/`.

La DLL CUDA informa runtime 12.8; se incorpora su licencia al ZIP Windows.
Los drivers son externos. No se recuperaron todos los comandos originales de
compilación CPU/CUDA; se conserva esa limitación de reproducibilidad, sin cambiar
los binarios probados ni atribuirles una procedencia no comprobada.

## Protocol references and development tools / Referencias y herramientas

BIP32/BIP39/BIP44, CashAddr, BCH signing rules and Stratum are protocol
references; implementing a specification does not by itself mean its reference
implementation is incorporated. Literal resources are identified above.

- BCHN and bchd parameters/checkpoints are referenced in the header/mining code.
  BCHN was also used as a development/test node; it is not bundled.
- FABLOUS consensus code identifies an independent implementation of
  CHIP-2025-03: https://gitlab.com/0353F40E/fablous (owner: bitcoincashautist;
  specification MIT-0). Future specification changes require separate review.
- setuptools/pip and GCC/MinGW are build tools, not application features.
- Pillow is a development-only visual-test dependency, not in the Windows ZIP.

No Selene, Cashonize or Electron Cash library was identified as an imported
dependency in this source. Personal acknowledgements do not imply incorporated
code, coauthorship or endorsement. A complete historical provenance assessment
cannot be inferred from the current file snapshot alone.
