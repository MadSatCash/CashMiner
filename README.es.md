# CashMiner

**Billetera, minero y explorador de peers experimental para Bitcoin Cash.**

[English](README.md) · Versión **2.17.1** · [Licencia](LICENSE)

CashMiner es un proyecto de escritorio liviano de CashRider para minar,
aprender y experimentar con Bitcoin Cash. Reúne herramientas de billetera,
un motor compartido CPU/CUDA/OpenCL y exploración de peers de distintas redes.

## Estado actual

Windows x64 es el primer destino empaquetado. Estamos preparando la primera
publicación pública experimental. El ZIP Windows es una candidata de prueba;
el instalador todavía no está disponible. Esta versión no ofrece paquetes
para Android, Linux, macOS ni iOS.

## Funciones

- Minería con CPU, NVIDIA CUDA y GPU compatibles con OpenCL.
- Minería P2P directa con verificación nativa de cabeceras; Electrum asistido
  sigue disponible donde está implementado.
- RPC con un nodo BCH configurado: `getblocktemplate` / `submitblock`.
- Stratum V1 con un pool compatible configurado por el usuario.
- Sesiones independientes para Mainnet, Testnet3, Testnet4, Chipnet,
  FABLOUS Tempnet 2026 y Regtest local, con los requisitos de cada red.
- Billeteras, derivación HD, firma local, sincronización Electrum,
  herramientas de recuperación y respaldos.
- Observaciones de peers en SQLite por red, Peer Explorer y ranking
  precalculado en segundo plano para preparar candidatos iniciales.
- Fuentes P2P por red: DNS, SQLite o ambas.

## Ejecutar el ZIP de Windows

Cuando esté disponible, descargá **CashMiner-Windows.zip** desde
[Releases](https://github.com/MadSatCash/CashMiner/releases). Extraé el ZIP
**completo** y abrí `CashMiner/CashMiner.exe`.

Conservá `_internal`, las licencias y los demás archivos junto al ejecutable.
Python está incluido; no necesitás instalarlo por separado.

Destino: Windows 10/11 x64 Intel/AMD. La candidata se probó en Windows 11;
la prueba en una instalación limpia sigue pendiente. CUDA/OpenCL requieren
controladores compatibles. La interfaz utiliza un navegador instalado
(preferentemente Edge, Chrome o Brave). El lanzador no tiene firma digital
del editor. Si falta `VCRUNTIME140.dll`, utilizá el Microsoft Visual C++
Redistributable x64 oficial.

No ejecutes pruebas contra los datos de tus billeteras reales. Dos copias
normalmente comparten el directorio de datos; no crean billeteras aisladas.

## Ejecutar desde el código en Windows

Con Python 3.10+ y una terminal en la raíz del repositorio:

```powershell
py -3 -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\pythonw.exe CashMiner.pyw
```

El repositorio incluye las tres DLL de hashing Windows x64, sus fuentes y
checksums en `native/`. El paquete Python por sí solo no incluye toda la
aplicación: ejecutá desde el repositorio completo.

La compilación del ZIP autónomo está documentada en
[packaging/windows/README.md](packaging/windows/README.md).

## Datos y recuperación

El programa y los datos personales se guardan por separado. En Windows se
utiliza normalmente `%LOCALAPPDATA%/CashMiner`; una instalación anterior en
`%LOCALAPPDATA%/CashMiner2` puede seguir utilizándose por compatibilidad.
El inicio no migra ni copia billeteras silenciosamente.

La protección de billeteras utiliza DPAPI de Windows. Conservá tus frases de
recuperación y respaldos: copiar el vault cifrado a otra computadora o cuenta
de Windows no reemplaza la recuperación. Nunca publiques frases, claves,
vaults ni contraseñas RPC/pool en issues. Ver [migración](docs/MIGRATION.md).

Para pruebas aisladas, configurá `CASHMINER_DATA_DIR` con una carpeta vacía
independiente antes de iniciar. El ZIP no contiene datos personales.

## Límites experimentales

- P2P nativo verifica cabeceras desde checkpoints; **no valida bloques completos
  ni sustituye un nodo completo**. Construye bloques sólo con coinbase, sin
  transacciones del mempool ni sus comisiones.
- P2P nativo no requiere tu propio nodo completo. La billetera sigue utilizando
  Electrum; RPC requiere un nodo propio o autorizado.
- Encontrar PoW, transmitir un bloque y observarlo en la cadena son resultados
  distintos. Ninguno por sí solo garantiza una recompensa gastable.
- La cobertura de validación varía según red, protocolo y hardware.
- Los candidatos se seleccionan al iniciar; no se actualizan dinámicamente
  durante la minería. El ranking puede estar desfasado respecto de observaciones.
- La minería FABLOUS Tempnet tiene corte programado el **15/11/2026 12:00 UTC**.
  No se promete compatibilidad automática con futuros cambios de Chipnet.
- Es software experimental para aprender y probar. La minería CPU/GPU no
  constituye una promesa de rentabilidad.

## Desarrollo y pruebas

El runtime requiere `cryptography`; el paquete Windows también incorpora
`psutil`. Pillow se utiliza sólo para pruebas de recursos gráficos.

```powershell
.venv\Scripts\python.exe -m pip install Pillow
$env:PYTHONPATH = "$PWD\src"
.venv\Scripts\python.exe -X utf8 -m unittest discover -s tests
```

Las pruebas GPU y con nodos reales son optativas. Usá datos aislados y leé
las [notas de validación](docs/VALIDATION.md) antes de activarlas.

## Documentación y licencia

- [Arquitectura](docs/ARCHITECTURE.md)
- [Migración](docs/MIGRATION.md)
- [Validación](docs/VALIDATION.md)
- [Notas de versión](docs/RELEASE_NOTES.md)
- [Avisos de terceros](THIRD_PARTY_NOTICES.md)
- [Agradecimientos](ACKNOWLEDGEMENTS.md)

El código del proyecto de CashRider tiene [licencia MIT](LICENSE). Los
componentes de terceros conservan sus propias licencias y avisos. La licencia
del proyecto no cambia las condiciones de los drivers, SDK ni otros componentes
de sus proveedores.
