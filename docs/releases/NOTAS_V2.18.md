# CashMiner v2.18 — Chipnet Faster Blocks

La base común incorpora las reglas Mina/Faster Blocks de Chipnet. Windows y
Android usan el mismo módulo `cashminer.network.chipnet_consensus`. Se conserva
el editor de monto de 2.17.2. Las otras redes mantienen sus reglas anteriores.

## Consenso y conexiones

- Activación por MTP del padre: 1794744000. En la rama pública comprobada, el
  último bloque lento es 332450 y el primero de un minuto es 332451.
- Contexto de activación por rama, reconstruido desde once cabeceras. ASERT
  basado en ticks, aritmética entera compatible con BCHN y dificultad mínima
  sólo cuando `ntime > tiempo_del_padre + 2 × intervalo_del_siguiente_bloque`.
- Subsidio y halvings por ticks. El subsidio actual es 250.000.000 satoshis
  (2,5 tBCH); BIP34 sigue usando la altura real. La coinbase Chipnet usa versión
  2 para evitar la forma de transacción versión 1 prohibida por Mina.
- Madurez de coinbase: 60.000 ticks. Una coinbase posterior al cambio requiere
  1.000 confirmaciones; las anteriores y las que atraviesan la transición se
  calculan con sus respectivos intervalos. Se aplica a saldos y selección de
  UTXOs antes de preparar un envío.
- P2P nativo comprueba enlace, PoW, dificultad, MTP y trabajo acumulado desde
  el checkpoint histórico. Revalida el caché bajo las nuevas reglas. Se fijan
  además los hashes de activación y de dos bloques posteriores comprobados en
  tres servidores independientes. Explorer y RPC comprueban la nueva identidad.
- El modo Electrum asistido verifica la secuencia completa de cabeceras con
  ese mismo verificador y corrobora la punta con peers P2P. La billetera compara
  los servidores Electrum a una altura común; no elige una rama por ser más alta.
- El modo asistido limita la selección de transacciones al piso ABLA de Chipnet,
  normalizado por intervalo (200.000 bytes después del cambio). Es conservador:
  este minero de cabeceras no deriva el límite adaptativo desde bloques completos.
- Los registros agregan intervalo objetivo y probabilidad por intervalo. CPU,
  CUDA y OpenCL conservan sus kernels; cambia la construcción/verificación del
  trabajo. RPC sigue usando las plantillas del nodo configurado.

Las comprobaciones de cabeceras no equivalen a validar todas las transacciones,
scripts y UTXOs de un nodo completo. La billetera conserva su modelo Electrum.

## Referencias y verificación

Referencia BCHN: preview 29.2.1, commit
`3e6827e95c7a17497e09ac15556debd116dea1d0`, distribuido en el
[directorio oficial upgrade2027_temp](https://download.bitcoincashnode.org/misc/builds/upgrade2027_temp/).
Se contrastaron `pow.cpp`, `validation.cpp` y `consensus/tx_verify.cpp` con el
[CHIP Faster Blocks](https://gitlab.com/0353F40E/fablous/-/blob/master/readme.md).

- Replay de 9.467 cabeceras posteriores al checkpoint, con contexto de once
  cabeceras previo; incluye la transición. Los fixtures se conservan en tests.
- 9.967 comparaciones ASERT coincidentes con la función C++ compilada de BCHN,
  incluyendo historia real y casos de borde. Se retienen 600 vectores de regresión.
- Pruebas de límites de dificultad mínima, halvings, ramas, caché, coinbase,
  selección de servidores y madurez en saldos y preparación de envíos.
- Suite completa: 635 pruebas sin fallos ni errores, 7 omitidas, ejecutada con
  ambos grupos opcionales BCHN habilitados.
- BCHN aislado: bloque construido por CashMiner aceptado por `submitblock`;
  gasto de coinbase rechazado con 100/999 confirmaciones y aceptado con 1.000.
  No se emitieron transacciones ni bloques a la red pública durante esa prueba.
- Conexiones reales P2P y TLS: cuatro peers corroboraron la punta nativa y
  tres servidores Electrum coincidieron a una altura común; el modo asistido
  verificó las cabeceras y obtuvo el contexto de un minuto.

Las pruebas opcionales con nodo se activan mediante `CASHMINER_TEST_BCHN_DIR`
y `CASHMINER_TEST_BCHN_MINA_DIR` apuntando al directorio de ejecutables BCHN.

## Procedencia de los paquetes

Windows se genera desde CashMiner_v2.18 mediante la receta fijada en
`packaging/windows`. Incluye Python y dependencias privadas. Los verificadores
de paquete comprobaron 322 archivos antes y después, trabajo CPU/OpenCL/CUDA
contra Stratum local y el proceso de ranking. Se verificaron además el arranque
del EXE, API 2.18, recursos del editor y cierre normal con datos aislados.

Android actualiza el payload Python/UI de la APK 2.17.2 y su manifiesto a
versionName 2.18 / versionCode 2180000. Conserva los DEX, recursos y bibliotecas
nativas; se alinea y firma con las herramientas oficiales 35.0.0 y el certificado
original. No es una recompilación Java/C ni acredita pruebas en un teléfono.
La receta completa Gradle también queda preparada para 2.18.

Los paquetes están en las carpetas hermanas Windows_v2.18 y Android_v2.18.
Previous conserva los paquetes anteriores y archivos fuente cristalizados.
Signing permanece fuera de Git. Los paquetes y checksums de esta versión se
distribuyen en la release experimental v2.18 de GitHub. Las demoras del camino
de envío y el tamaño de los lotes de hashing quedan para una entrega posterior.
La prueba de hallar y confirmar un bloque propio en Chipnet pública sigue
pendiente; la prueba de aceptación citada arriba corresponde al nodo aislado.
