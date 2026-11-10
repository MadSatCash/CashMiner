# Bibliotecas nativas incluidas (v2.8.0)

Estas tres bibliotecas Windows x86-64 se distribuyen dentro de `native/`:
`bch_hashscan.dll` (CPU), `bch_hashscan_cuda.dll` (NVIDIA/CUDA) y
`bch_hashscan_opencl.dll` (OpenCL). Sus SHA-256 estan en `SHA256SUMS.txt`.
Origen: binarios compilados del proyecto original `cashminer_app` del autor.
Los fuentes C/CUDA correspondientes se guardan en `source/` para facilitar
recompilacion y trazabilidad. No se compilan ni descargan en el inicio.

El proceso minero copia a `AppData/Local/CashMiner/runtime/mining_engine/`
solo los archivos necesarios para ejecutar; esa carpeta es **salida**, nunca
origen ni fallback de bibliotecas nativas. `CashMiner2/native` es legado y no se lee como fuente. Si no se ha migrado
la carpeta de datos, el runtime nuevo se genera bajo esa raiz existente.

Requisitos externos Windows: controlador NVIDIA/CUDA u OpenCL del fabricante
para la GPU elegida. La DLL CUDA importa `VCRUNTIME140.dll` y componentes UCRT;
el sistema destino puede requerir Microsoft Visual C++ Redistributable x64.
`bch_hashscan_opencl.dll` importa `OpenCL.dll`, habitualmente suministrada por
el controlador. No se distribuyen drivers ni runtimes del proveedor.

No incorporar en el ZIP billeteras, claves, tokens, logs ni datos de AppData.
Esta version **no** incluye `python.exe`, el paquete Python `cryptography` ni
instalador: requiere Python >=3.10 y las dependencias documentadas.
