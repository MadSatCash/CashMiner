# Data and migration / Datos y migración

## English

The default Windows data directory is `%LOCALAPPDATA%/CashMiner`. If only a
legacy `%LOCALAPPDATA%/CashMiner2` directory exists, the application continues
using it in place. Extracting a ZIP does not copy or reset wallets.

Before moving data, stop all CashMiner windows and miners and preserve recovery
phrases/backups. The manual migration tool provides a preview before applying:

```powershell
py -3 scripts/MIGRAR_DATOS.py
py -3 scripts/MIGRAR_DATOS.py --apply
```

Use a Python environment with the project dependencies. The Windows runtime
also contains `_internal/app/scripts/MIGRAR_DATOS.py`, executable using its
private `_internal/python/python.exe`. Read the preview and do not replace
an existing destination blindly. The migration closes its SQLite handles
before publishing the destination and preserves the original source.

Windows DPAPI vaults are bound to the Windows security context. Moving files
between accounts/computers requires appropriate recovery; copying a vault is
not a substitute for its recovery phrase.

## Español

Los datos se guardan normalmente en `%LOCALAPPDATA%/CashMiner`. Si sólo existe
la carpeta anterior `%LOCALAPPDATA%/CashMiner2`, se sigue utilizando en su lugar.
Extraer un ZIP no copia ni reinicia billeteras.

Antes de migrar, cerrá todas las ventanas y mineros y conservá tus frases y
respaldos. El script anterior ofrece una vista previa; `--apply` aplica la
migración. Usá el entorno Python del proyecto o el runtime privado del ZIP.
No reemplaces un destino existente sin revisar la vista previa.

La migración conserva el origen y cierra sus conexiones SQLite antes de
publicar el destino. Los vaults DPAPI están ligados al contexto de seguridad
de Windows; para otro equipo o usuario necesitás la recuperación adecuada.
