# CashMiner v2.18.3 — Wallet sync progress

Initial wallet sync pipelines history and unspent-output requests, with up to
15 requests in flight per Electrum connection. The wallet shows discovery and
verification progress, and labels cached balances while reconnecting.

La sincronización inicial agrupa las consultas y muestra cuántas direcciones
se revisaron. Después de una reconexión, indica cuándo el saldo guardado está
pendiente de verificar.

[Cambios detallados](releases/NOTAS_V2.18.3.md) · [Validation](VALIDATION.md) ·
[Packages and SHA-256](ARTIFACTS.md)

---

# CashMiner v2.18.2 — WIF import, key visibility and general menu

**[Windows ZIP](https://github.com/MadSatCash/CashMiner/releases/download/v2.18.2/CashMiner-Windows.zip)** · **[Android APK](https://github.com/MadSatCash/CashMiner/releases/download/v2.18.2/CashMiner-Android-v2.18.2.apk)** · [SHA-256](https://github.com/MadSatCash/CashMiner/releases/download/v2.18.2/SHA256SUMS.txt)

Experimental Windows and Android release. Single private keys accept Hexadecimal
or WIF, separately from HD BIP39/BIP32 imports. WIF validates its checksum,
network, compression and private-key range and shows the address for confirmation.
Format information buttons explain each option; imported names are network-neutral.

Show/hide the imported single private key (Hexadecimal/WIF) without changing its
value or address preview. Keys start hidden. The general Manage button is now
☰, opening the same options; individual wallet settings keep their gear.
Spanish/English labels, keyboard and mobile controls are included.

Ojito para mostrar/ocultar la clave individual y menú general ☰. La clave queda
oculta por defecto y se conserva la dirección comprobada al alternar visibilidad.

Includes WIF import and format help prepared in the unpublished 2.18.1 candidate.
The owner confirmed successful WIF import during Windows testing. Validation:
642 tests without failures/errors, 9 skipped; 35 focused UI/language checks and
10 wallet tests with the shipped Windows Python also passed. The EXE started
and closed normally with isolated data.

Android retains its update certificate and DEX/native/resources. Its Python/UI
payload and manifest are updated (versionCode 2180200); signature, alignment and
payload were verified. This APK still needs testing on a phone/emulator. Install
over the existing app without uninstalling or clearing data.

Incluye importación WIF, ayudas de formato, placeholder neutral, ojito y menú ☰.
El propietario confirmó la importación WIF al probar Windows. Pasaron 642 pruebas
sin fallos ni errores, con 9 omitidas. La APK conserva la firma de actualización;
falta probarla en teléfono/emulador. Instalá encima, sin desinstalar ni borrar datos.

[Cambios detallados](releases/NOTAS_V2.18.2.md) · [Validation](VALIDATION.md) ·
[Artifacts](ARTIFACTS.md)

---

## Unpublished local candidate 2.18.1 — included in 2.18.2

Experimental Windows and Android update. Single private keys accept Hexadecimal
or WIF; HD BIP39 and BIP32 imports remain separate. WIF validates its checksum,
network and compression and shows the address before confirmation. Format help
buttons work by click, keyboard and touch in Spanish and English. The imported
wallet name is now network-neutral.

Actualización experimental para Windows y Android: importación de claves
individuales en hexadecimal o WIF, ayudas ⓘ para cada formato y placeholder
neutral. Se comprueban checksum, red y compresión y se confirma la dirección
antes de guardar. Las billeteras existentes conservan su estructura.

This candidate was not published separately; its changes are included in 2.18.2.
No se publicó por separado; sus cambios están incluidos en 2.18.2.

[Detailed changes / Cambios detallados](releases/NOTAS_V2.18.2.md) ·
[Validation / Validación](VALIDATION.md) · [Artifacts / Artefactos](ARTIFACTS.md)

---

## Previous release / Versión anterior: 2.18

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
