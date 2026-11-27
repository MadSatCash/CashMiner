# CashMiner v2.18.4 — Sincronización y envío

- La verificación de saldos admite cantidades válidas de CashTokens. Un valor
  alto en ese campo ya no interrumpe el escaneo de la billetera.
- Enviar depende del estado de la billetera seleccionada y de la conexión a
  Electrum. Si otra billetera está sincronizando o reintentando, la que ya
  está al día puede preparar un envío y mostrar la confirmación habitual.
- Paquetes para Windows y Android desde el mismo código fuente.
  Android conserva el identificador de aplicación y el certificado para
  instalar la actualización encima de la versión anterior.

## Wallet sync and send

- Balance sync accepts valid CashToken quantities without applying size limits
  to the token amount field.
- A synced wallet can prepare a send while another wallet is syncing or
  retrying, as long as Electrum is connected. Sending still requires confirmation.
- The Windows and Android packages use the same source. Android retains its
  application ID and signing certificate for in-place updates.
