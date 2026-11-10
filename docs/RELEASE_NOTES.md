# 2.17.1 — experimental Windows candidate

## English

- Fix manual Windows data migration: close source, backup and verification
  SQLite connections before atomically publishing the migrated directory.
- Fix RPC GPU dispatch when OpenCL is available without CUDA, including when
  CPU mining is disabled. Hashing algorithms/native DLLs are unchanged.
- Repair identified test fixtures for SQLite handles, byte-exact logs and the
  complete three-DLL package; add focused migration/backend regressions.
- Add a standalone Windows ZIP build with a private runtime and native launcher.
- Correct auxiliary source launchers to use the current `cashminer` module.
- Add English/Spanish publication documentation and MIT project licensing.

Native P2P remains experimental header verification and coinbase-only block
construction. This candidate is not an installer or a cross-platform release.
See [validation](VALIDATION.md) for completed and pending checks.

## Español

- Corrige el cierre de conexiones SQLite en la migración manual de Windows.
- Corrige RPC con OpenCL disponible sin CUDA, incluso con CPU deshabilitada.
- Repara fixtures identificados y añade regresiones de migración/backends.
- Añade empaquetado ZIP Windows con Python privado y lanzador nativo.
- Corrige los lanzadores auxiliares para invocar `cashminer`.
- Añade documentación bilingüe y licencia MIT del proyecto.

No cambia los algoritmos de hashing ni las DLL. P2P nativo sigue siendo
experimental y construye bloques sólo con coinbase. La candidata todavía
no incluye instalador ni paquetes para otros sistemas.
