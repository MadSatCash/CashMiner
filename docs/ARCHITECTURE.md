# Architecture / Arquitectura — 2.17.1

| Directory | Responsibility / Responsabilidad |
| --- | --- |
| `src/cashminer/app` | Loopback HTTP API, UI lifecycle, service coordination / API local e interfaz |
| `src/cashminer/wallet` | Keys, HD derivation, signing, Electrum, wallet storage / Billeteras |
| `src/cashminer/network` | Peer observations, exploration, selection and ranking / Peers |
| `src/cashminer/mining` | Per-network sessions and child-process bridge / Sesiones y puente |
| `mining_engine` | Shared CPU/CUDA/OpenCL work execution, P2P/RPC/Stratum / Motor |
| `native` | Distributed Windows x64 hashing libraries and C/CUDA sources / DLL y fuentes |
| `ui`, `assets` | Local HTML/JS/CSS and artwork / Interfaz y recursos |
| `packaging/windows` | Private Python runtime build and native launcher / Empaquetado |
| `packaging/android` | APK, WebView, Keystore and per-network foreground services / Integración Android |
| `src/cashminer/platform/android_runtime.py` | Android adapter for the shared app and miner / Adaptador Android |
| `scripts`, `tests` | Manual tools and automated checks / Herramientas y pruebas |

The wallet signs locally. Modern wallet secrets are not passed to mining
children; the bridge passes public reward addresses. Each network has its
own session state and SQLite data. Peer observations are not consensus proof.
Ranking is derived data used for initial candidates, not an additional source
of truth or a mechanism for refreshing live miner connections.

La billetera firma localmente. El puente entrega direcciones públicas de
recompensa al minero, no secretos de las billeteras modernas. Cada red tiene
estado y SQLite separados. Las observaciones de peers no prueban consenso.
El ranking es un dato derivado para candidatos iniciales.

The UI server binds to 127.0.0.1 on a dynamically assigned port and uses a
per-session token for authenticated API operations. The Windows launcher opens
the private `pythonw.exe`; the miner, ranking worker and hardware probe use
the sibling private `python.exe`. CPython `_pth` isolates imports from the
machine's Python configuration. Child pipes are UTF-8.

La API escucha sólo en loopback y utiliza un token por sesión. El paquete
Windows incluye su propio Python para la interfaz y sus procesos separados.
Los datos persistentes se guardan fuera del directorio del programa.

Native P2P performs checkpoint/header/PoW/difficulty checks; it is not a
replacement for a fully validating node. RPC and Stratum supply work through
their own configured endpoints while using the same hashing backends.
