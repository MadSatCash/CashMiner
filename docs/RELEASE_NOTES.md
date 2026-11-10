# CashMiner v2.17.1 — Windows & Android

**[⬇️ Windows ZIP](https://github.com/MadSatCash/CashMiner/releases/download/v2.17.1/CashMiner-Windows.zip)** · **[⬇️ Android APK](https://github.com/MadSatCash/CashMiner/releases/download/v2.17.1/CashMiner-Android-v2.17.1.apk)** · [SHA-256](https://github.com/MadSatCash/CashMiner/releases/download/v2.17.1/SHA256SUMS.txt)

## English

First experimental Windows and Android release of CashMiner, a lightweight
Bitcoin Cash wallet, miner and peer explorer for learning and experimentation.

| System | Download | Start |
| --- | --- | --- |
| Windows 10/11 x64 | [CashMiner-Windows.zip](https://github.com/MadSatCash/CashMiner/releases/download/v2.17.1/CashMiner-Windows.zip) | Extract the entire ZIP; open `CashMiner/CashMiner.exe`. |
| Android 7.0+ | [CashMiner-Android-v2.17.1.apk](https://github.com/MadSatCash/CashMiner/releases/download/v2.17.1/CashMiner-Android-v2.17.1.apk) | Open the APK on your phone and install/update. |

Windows supports CPU, CUDA and compatible OpenCL GPUs. Android includes ARM32,
ARM64 and x86-64 CPU mining, adjustable 0–100%, independent network sessions and
background mining with Stop notifications. Update Android over the existing
installation without uninstalling or clearing data to preserve wallets.
Python is included in both packages. Direct P2P does not need your own full node;
RPC needs a configured node and Stratum needs a compatible configured pool.

Validation includes earlier Windows tests (606, no failures/errors, 5 skipped),
local CPU/CUDA/OpenCL share verification, 18 focused Android tests and two
parallel emulator sessions producing independently verified Stratum shares.
The owner reports finding and checking a Testnet3 block on their Android phone.
Coverage varies by network/device; these are not universal compatibility claims.

The Android APK is the tested build 2170105 from `b5b487332006bb2d7f764de6e07795608ff05cfc`.
The Windows runtime is retained from `dce3b1543afc2de86ae3642172dda87ee35fb02f`;
only MIT/vendor license documents and its manifest were refreshed for publication.
Its executable/DLLs/application sources are unchanged. It predates the later
shared C-MT CPU duty fix in the source tree. Checksums cover the packages offered here.

Experimental limits: native P2P verifies headers, not complete blocks, and builds
coinbase-only blocks. FABLOUS Tempnet mining cuts off at 2026-11-15 12:00 UTC.
Future Chipnet consensus changes are not automatically supported. Windows uses
DPAPI; Android uses Keystore. Keep recovery phrases/keys and backups. Windows
launcher is not publisher-signed; Android is signed with the project's update key.
Android uses an older cryptography runtime whose review for a stable wallet
release remains pending. Android/vendor policies may affect background uptime.
Linux, macOS and iOS packages are not included.

[English guide](https://github.com/MadSatCash/CashMiner#readme) · [Source/build provenance](https://github.com/MadSatCash/CashMiner/blob/main/docs/ARTIFACTS.md) · [Validation](https://github.com/MadSatCash/CashMiner/blob/main/docs/VALIDATION.md)

## Español

Primera publicación experimental de CashMiner para Windows y Android: una
billetera, minero y explorador de peers liviano para aprender y experimentar
con Bitcoin Cash.

| Sistema | Descarga | Inicio |
| --- | --- | --- |
| Windows 10/11 x64 | [CashMiner-Windows.zip](https://github.com/MadSatCash/CashMiner/releases/download/v2.17.1/CashMiner-Windows.zip) | Extraer completo y abrir `CashMiner/CashMiner.exe`. |
| Android 7.0+ | [CashMiner-Android-v2.17.1.apk](https://github.com/MadSatCash/CashMiner/releases/download/v2.17.1/CashMiner-Android-v2.17.1.apk) | Abrir la APK en el teléfono e instalar/actualizar. |

Windows admite CPU, CUDA y GPU compatibles con OpenCL. Android incluye minería
CPU ARM32/ARM64/x86-64, ajustable 0–100%, sesiones independientes por red y minería
en segundo plano con notificaciones Detener. Actualizá Android encima, sin
borrar datos ni desinstalar, para conservar las billeteras. Ambos incluyen Python.
P2P directo no necesita tu propio nodo completo; RPC necesita un nodo configurado
y Stratum un pool compatible configurado.

Validación: suite Windows anterior (606 pruebas, sin fallos/errores, 5 omitidas),
shares CPU/CUDA/OpenCL verificados localmente, 18 pruebas Android y dos sesiones
paralelas en emulador con shares verificados independientemente. El propietario
informó que encontró y comprobó un bloque de Testnet3 en su teléfono. La cobertura
varía por red/equipo; no se promete compatibilidad universal.

La APK probada es la 2170105, fuente `b5b487332006bb2d7f764de6e07795608ff05cfc`.
El runtime Windows se conserva desde `dce3b1543afc2de86ae3642172dda87ee35fb02f`;
sólo se actualizaron licencias/avisos y manifiesto para publicar. No cambian EXE,
DLL ni fuentes de la aplicación. Es anterior a la corrección posterior del control
CPU C-MT del código común. Los checksums corresponden a los paquetes ofrecidos aquí.

Límites experimentales: P2P nativo verifica cabeceras, no bloques completos, y
construye bloques sólo con coinbase. FABLOUS Tempnet corta minería el 15/11/2026,
12:00 UTC. No hay compatibilidad automática con cambios futuros de Chipnet.
Windows usa DPAPI; Android, Keystore. Conservá frases/claves y respaldos. El
lanzador Windows no tiene firma del editor; Android conserva la firma del proyecto
para actualizar. Sigue pendiente revisar el runtime criptográfico móvil anterior
para una publicación estable. Las políticas de Android/fabricante pueden afectar
la continuidad. No incluye paquetes Linux, macOS ni iOS.

[Guía en español](https://github.com/MadSatCash/CashMiner/blob/main/README.es.md) · [Procedencia y compilación](https://github.com/MadSatCash/CashMiner/blob/main/docs/ARTIFACTS.md) · [Validación](https://github.com/MadSatCash/CashMiner/blob/main/docs/VALIDATION.md)
