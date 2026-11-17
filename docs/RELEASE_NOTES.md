# CashMiner v2.18 — Chipnet Faster Blocks · Windows & Android

**[Windows ZIP](https://github.com/MadSatCash/CashMiner/releases/download/v2.18/CashMiner-Windows.zip)** · **[Android APK](https://github.com/MadSatCash/CashMiner/releases/download/v2.18/CashMiner-Android-v2.18.apk)** · [SHA-256](https://github.com/MadSatCash/CashMiner/releases/download/v2.18/SHA256SUMS.txt)

## English

Experimental update for Chipnet's one-minute blocks. Shared code now handles
branch-local activation, tick-based ASERT and halvings, the current 2.5 tBCH
base subsidy and 60,000-tick coinbase maturity (1,000 new one-minute blocks).
Native P2P and Electrum-assisted mining validate upgraded-chain references;
wallet balances and coin selection use the new maturity rules. BIP34 retains
raw block heights and Chipnet coinbases use transaction version 2.

Also includes the 2.17.2 amount editor: locale-aware decimal/group separators,
eight BCH decimals, persistent conversion space and compact validation tooltip.
Windows includes the shared C-MT CPU duty fix previously absent from its package.

Validation: 635 tests completed without failures/errors, 7 skipped; real Chipnet
header replay and live connections; block acceptance and coinbase maturity checks
against isolated BCHN; packaged CPU/OpenCL/CUDA shares independently verified
on local Stratum; EXE startup and normal shutdown with isolated data.
A self-mined block accepted on public Chipnet remains untested.

Windows is rebuilt from the shared sources with its private Python runtime;
hashing DLLs are retained. Extract the entire ZIP and open CashMiner/CashMiner.exe.
Android is an incremental Python/UI payload and manifest update (versionCode
2180000): DEX, resources and native libraries retain their earlier bytes and
update certificate. This APK has not been tested on a phone/emulator. Install
over the existing app without uninstalling or clearing data to preserve wallets.

Native P2P verifies headers, not all transactions/scripts/UTXOs as a full node
would. Assisted mining uses a conservative 200,000-byte Chipnet selection cap.
Future consensus changes still require an update. Existing experimental platform
and dependency limitations remain; see the linked provenance and validation.
Send-path latency and GPU batch optimizations are deferred, not part of 2.18.

## Español

Actualización experimental para Chipnet con bloques de un minuto: activación
por rama, ASERT y halvings por ticks, subsidio base actual de 2,5 tBCH y madurez
de coinbase de 60.000 ticks (1.000 bloques nuevos de un minuto). Se actualizan
P2P nativo, Electrum asistido, referencias de conexión, saldos y selección de
UTXOs. BIP34 conserva la altura real; la coinbase Chipnet usa versión 2.

Incluye el editor de monto de 2.17.2: formato numérico activo, agrupación de
miles, ocho decimales BCH, espacio fijo para conversión y tooltip discreto.
Windows incorpora la corrección de control CPU C-MT del código común.

Verificación: 635 pruebas sin fallos/errores, 7 omitidas; cabeceras y conexiones
reales de Chipnet; aceptación de bloque y madurez comprobadas con BCHN aislado;
shares CPU/OpenCL/CUDA verificados en Stratum local; arranque y cierre del EXE
con datos aislados. Sigue pendiente encontrar y confirmar un bloque propio en
Chipnet pública. No se promete validación completa de nodo.

Windows: extraé el ZIP completo y abrí CashMiner/CashMiner.exe. Android:
actualizá encima de la instalación existente, sin desinstalar ni borrar datos.
La APK actualiza Python/UI y manifiesto, conserva DEX/recursos/bibliotecas nativas
y firma anterior; esta APK todavía no se probó en teléfono/emulador.
Las mejoras de latencia de envío y lotes GPU quedan para después.

[Source / Código](https://github.com/MadSatCash/CashMiner/tree/v2.18) · [Provenance / Procedencia](https://github.com/MadSatCash/CashMiner/blob/v2.18/docs/ARTIFACTS.md) · [Detailed changes / Cambios detallados](https://github.com/MadSatCash/CashMiner/blob/v2.18/docs/releases/NOTAS_V2.18.md) · [Validation / Validación](https://github.com/MadSatCash/CashMiner/blob/v2.18/docs/VALIDATION.md)
