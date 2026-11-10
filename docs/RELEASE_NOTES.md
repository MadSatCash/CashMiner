# 2.17.1 — experimental Windows and Android

## English

Private preparation draft. One source repository with separate packages for
Windows x64 and Android. Linux, macOS and iOS are deferred.

| File | Use |
| --- | --- |
| `CashMiner-Windows.zip` | Extract the entire ZIP; open `CashMiner/CashMiner.exe`. |
| `CashMiner-Android-v2.17.1.apk` | Install/update on Android 7.0+; ARM32/ARM64/x86-64; CPU mining. |
| `SHA256SUMS.txt` | SHA-256 checksums of both packages. |

### Android

- Shared wallet, P2P/RPC/Stratum, peer storage, ranking and responsive UI, with
  Android WebView, Keystore and CPU hashing built from the existing C source.
- CPU 0–100%, independent network sessions and continued mining when minimized
  or locked, with a Stop notification per network. Android/vendor process policies
  still apply. CUDA/OpenCL are not ported to Android.
- Full original logs saved using Android's document picker.
- Update over the existing app without uninstalling or clearing data. Package ID
  and signing certificate are unchanged; keep recovery material.
- Eighteen focused tests passed. Two emulator sessions produced 29/41 shares
  independently validated by local Stratum servers and continued in background.
  Stopping one left the other mining. The exported log matched the complete file.
- The owner reports finding and checking a Testnet3 block on their Android phone.
  This is owner-reported physical-device evidence, not all-network validation.
- APK source: `b5b487332006bb2d7f764de6e07795608ff05cfc`; versionCode 2170105.

### Retained Windows candidate

- Fixes manual migration by closing SQLite handles before publishing migrated
  data, and RPC dispatch with OpenCL available without CUDA.
- Includes private Python and native launcher; GPU drivers and a browser remain
  external. No installer or publisher signature is included.
- Retains the previously tested ZIP byte-for-byte. Its runtime matches desktop
  source `dce3b1543afc2de86ae3642172dda87ee35fb02f`; it does not include the later
  shared C-MT CPU duty fix developed during the Android port.
- Earlier Windows suite: 606 tests, 0 failures/errors, 5 skipped, plus independent
  local CPU/OpenCL/CUDA share verification. Not rerun for this documentation upload.

### Scope and preparation status

Native P2P verifies headers rather than full blocks and builds coinbase-only
blocks. Tempnet mining cuts off at 2026-11-15 12:00 UTC. Future Chipnet consensus
changes are not automatically supported. Review of Android's older cryptography
runtime for a stable wallet release remains pending.
Before public binary distribution, the retained Windows ZIP still needs its
bundled project-license/notices refresh and the native redistribution provenance
already tracked in THIRD_PARTY_NOTICES.md. The repository remains private and
this release remains a draft. See docs/VALIDATION.md and docs/ARTIFACTS.md.

## Español

Borrador privado de preparación. Un repositorio de código y paquetes separados
para Windows x64 y Android. Linux, macOS e iOS quedan para después.

| Archivo | Uso |
| --- | --- |
| `CashMiner-Windows.zip` | Extraer completo y abrir `CashMiner/CashMiner.exe`. |
| `CashMiner-Android-v2.17.1.apk` | Instalar/actualizar en Android 7.0+; ARM32/ARM64/x86-64; minería CPU. |
| `SHA256SUMS.txt` | Checksums SHA-256 de ambos paquetes. |

### Android

- Comparte billetera, P2P/RPC/Stratum, peers, ranking e interfaz adaptable;
  incorpora WebView, Keystore y hashing CPU compilado desde el C existente.
- CPU 0–100%, sesiones simultáneas por red y continuidad al minimizar/bloquear,
  con notificación Detener por red. Siguen aplicándose las políticas del sistema
  y fabricante. CUDA/OpenCL no están portados a Android.
- Exportación del registro completo mediante el selector de documentos Android.
- Actualizar encima, sin desinstalar ni borrar datos. Mantiene identificador y
  firma. Conservar las frases/claves de recuperación.
- Pasaron 18 pruebas específicas. Dos sesiones en emulador produjeron 29/41
  shares verificados por servidores Stratum locales, continuaron en segundo
  plano y se detuvieron independientemente. El log exportado coincidió completo.
- El propietario informó que encontró y comprobó un bloque de Testnet3 en su
  teléfono. Es evidencia física informada por él, no validación de todas las redes.
- Fuente APK: `b5b487332006bb2d7f764de6e07795608ff05cfc`; versionCode 2170105.

### Candidata Windows conservada

- Corrige handles SQLite en migración manual y RPC con OpenCL sin CUDA.
- Incluye Python privado y lanzador; drivers GPU y navegador externos.
  No incluye instalador ni firma digital del editor.
- Conserva el ZIP probado sin cambiar sus bytes. Su runtime corresponde a
  `dce3b1543afc2de86ae3642172dda87ee35fb02f`; no incluye la corrección posterior
  del control CPU C-MT desarrollada durante el port Android.
- Suite Windows anterior: 606 pruebas, sin fallos/errores, 5 omitidas y shares
  CPU/OpenCL/CUDA verificados localmente. No se repitió para esta subida documental.

### Alcance y estado de preparación

P2P nativo verifica cabeceras, no bloques completos, y construye bloques sólo
con coinbase. Tempnet corta minería el 15/11/2026 a las 12:00 UTC. No se promete
compatibilidad automática con cambios futuros de Chipnet. Sigue pendiente revisar
el runtime criptográfico móvil anterior para una publicación estable de billetera.
Antes de distribuir públicamente el ZIP Windows conservado falta actualizar sus
licencias/avisos incorporados y cerrar la procedencia de redistribución nativa ya
documentada en THIRD_PARTY_NOTICES.md. El repositorio permanece privado y esta
release en borrador. Ver docs/VALIDATION.md y docs/ARTIFACTS.md.
