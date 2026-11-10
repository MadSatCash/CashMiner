/* CashMiner v2.11 · UI language and numeric presentation only.
   Source language: Spanish. Logs, addresses, secret material and protocol
   payloads are deliberately outside the translation pipeline. */
(() => {
  'use strict';
  const LANGUAGE_KEY='cashminer.ui.language.v210';
  const FORMAT_KEY='cashminer.ui.numberFormat.v210';
  const EN={
    'Minería':'Mining','Billeteras':'Wallets','Red':'Network','Administrar':'Manage',
    'Moneda fiat':'Fiat currency',
    'Vista principal':'Main view','Billetera':'Wallet','Minero':'Miner','Cotización de 1 BCH':'Rate of 1 BCH',
    'Acción de billetera':'Wallet action',
    'Seleccionar billetera':'Select wallet','Elegí una billetera':'Choose a wallet','Sin billeteras':'No wallets',
    'Inmaduras:':'Immature:',
    'Saldo total disponible':'Total available balance','Preparando billeteras…':'Preparing wallets…',
    'Todavía no hay una billetera':'No wallet yet','Billetera seleccionada':'Selected wallet',
    'Saldo total:':'Total balance:','Recompensas inmaduras:':'Immature rewards:',
    'Sin saldo sincronizado':'Balance not synchronized','Sin billetera seleccionada':'No wallet selected',
    'Verificando saldos...':'Checking balances...','Verificando saldos…':'Checking balances…',
    'No hay billeteras para esta red. Usá Administrar para crear o importar.':'No wallets on this network. Use Manage to create or import one.',
    'Elegí una billetera o creá una nueva para comenzar.':'Select a wallet or create a new one to begin.',
    'Conectando':'Connecting','Sincronizando':'Syncing','Conectada y sincronizada':'Connected and synced',
    'Sin conexión o datos desactualizados':'Disconnected or outdated data',
    'Recibir':'Receive','Enviar':'Send','Configurar billetera':'Wallet settings',
    'Cerrar configuración de billetera':'Close wallet settings','Volver a la billetera':'Back to wallet',
    'Configuración de la billetera seleccionada':'Selected wallet settings',
    'Código QR de la dirección de recepción':'Receive address QR code',
    'Tocá para copiar la dirección':'Tap to copy address','Copiar dirección de recepción':'Copy receive address',
    'Cargando dirección…':'Loading address…','¡Copiada!':'Copied!',
    'No se pudo copiar la dirección':'Could not copy address',
    'Enviar a Dirección CashAddr (con prefijo):':'Send to CashAddr (including prefix):',
    'Monto tBCH':'Amount tBCH','Monto BCH':'Amount BCH','Comisión':'Fee',
    'Comisión:':'Fee:','Comisión en satoshis por byte':'Fee in satoshis per byte',
    'Enviar todos los UTXO rentables, descontando la comisión':'Send all profitable UTXOs, minus the fee',
    'Formato y ruta de derivación':'Format and derivation path',
    'Ninguna billetera':'No wallet','Configuración':'Settings','Cerrar':'Close',
    'Cancelar':'Cancel','Continuar':'Continue','Aceptar':'Accept',
    'Permitir operación experimental.':'Allow experimental operation.',
    'Contraseña de la billetera':'Wallet password',
    'Minería detenida':'Mining stopped','Iniciando minería':'Starting mining',
    'Deteniendo minería':'Stopping mining','Minando':'Mining','Detenido':'Stopped',
    'Actividad e historial de minería':'Mining activity and history',
    'Destino de recompensas':'Reward destination',
    'Destino':'Destination','Externa':'External','Agregar destino':'Add destination',
    'Guardar destinos':'Save destinations','Dirección copiada':'Address copied',
    'Copiar dirección completa':'Copy full address','Quitar destino':'Remove destination',
    'En Stratum los pagos los controla el pool.':'In Stratum, the pool controls payouts.',
    'Elegí una billetera o una dirección externa':'Select a wallet or an external address',
    'Utilizar una dirección fija o externa':'Use a fixed or external address',
    'Dirección pública para recibir recompensas':'Public address to receive mining rewards',
    'Sin dirección de recompensa':'No reward address',
    'Creá o importá una billetera en esta red para poder minar.':'Create or import a wallet on this network to start mining.',
    'En modo Stratum el pool decide los pagos según el usuario/worker; la configuración de abajo sólo se aplica a minería individual RPC/P2P-tip.':
      'In Stratum mode, the pool determines payouts from your user/worker; the setting below only applies to solo RPC/P2P-tip mining.',
    'Red y modalidad de minería':'Network and mining mode',
    'Modalidad':'Mode','Solo P2P-tip / Electrum':'Solo P2P-tip / Electrum',
    'Solo RPC':'Solo RPC','Pool Stratum':'Stratum pool',
    'Aplicar modalidad y conexión (sesión actual)':'Apply mode and connection (current session)',
    'La conexión RPC/Stratum debe configurarse para esta sesión. No guardamos contraseñas en disco.':
      'RPC/Stratum connections must be configured for this session. Passwords are not saved to disk.',
    'Red activa:':'Active network:',
    'P2P directo':'Direct P2P','Electrum asistido':'Electrum-assisted',
    'P2P nativo':'Native P2P','Referencia de punta P2P':'P2P chain-tip reference',
    'Actividad e historial de minería':'Mining activity and history',
    'Estado':'Status','Estado:':'Status:',
    'Potencia informada':'Reported hashrate','Altura observada':'Observed height',
    'Soluciones PoW halladas':'PoW solutions found','En cadena observada':'Observed on chain',
    'Fuera de cadena':'Off chain','Pendientes de verificar':'Pending verification',
    'Sesiones y bloques propios':'Sessions and own blocks',
    'Sin sesiones de minería':'No mining sessions',
    'La pertenencia se basa en las cabeceras de peers y la mejor rama conocida; no supone validación independiente del bloque completo ni recompensa definitiva. «Pendiente» significa falta de evidencia suficiente, no rechazo. Se actualizan con la sincronización normal del motor; al detenerse conservan el último estado conocido.':
      'Chain membership relies on peer headers and the best known branch; it is not independent full-block validation or a final reward. “Pending” means insufficient evidence, not rejection. Results update with normal miner synchronization and retain their last known state when stopped.',
    'Hardware':'Hardware','Volver a detectar hardware':'Detect hardware again',
    'Guardar configuración':'Save settings','Detectando CPU y GPU locales…':'Detecting local CPU and GPUs…',
    'Bibliotecas incluidas:':'Included libraries:',
    'Cada dispositivo compatible tiene su porcentaje independiente. Inicial: CPU 0 %, GPU 25 %. Cero desactiva ese dispositivo. Los cambios se aplican en el próximo arranque de minería.':
      'Each compatible device has its own percentage. Defaults: CPU 0%, GPU 25%. Zero disables that device. Changes apply the next time mining starts.',
    'Disponible':'Available','No disponible':'Unavailable',
    'Nativa':'Native','No compatible':'Not compatible',
    'Conexiones para minar':'Mining connections',
    'Mínimo de peers compatibles para minar':'Minimum compatible peers for mining',
    'Guardar mínimo para minería':'Save mining minimum',
    'Este ajuste pertenece al motor, no al explorador. Cambia el mínimo para iniciar la minería; el motor sigue verificando por sí mismo la cadena y las cabeceras.':
      'This setting belongs to the miner, not the explorer. It changes the minimum number of peers required to start mining; the engine still validates chain and headers itself.',
    'Se aplica en el próximo arranque del minero. La modalidad con 0 peers sigue pendiente.':
      'Applies the next time the miner starts. Zero-peer mode is not implemented yet.',
    'Servidores Electrum de minería':'Mining Electrum servers',
    'Diagnóstico del minero · Logs originales':'Miner diagnostics · Original logs',
    'Registro original del motor, guardado en archivos por ejecución. Incluye las respuestas P2P, anuncios de bloques y verificación de cabeceras; no se borra al detener ni cerrar CashMiner.':
      'Original engine log, stored in a separate file per run. Includes P2P responses, block announcements and header verification; it is not deleted when mining stops or CashMiner closes.',
    'LOG DEL MINERO':'MINER LOG','Copiar todo':'Copy all','Exportar log':'Export log',
    'Retención FIFO (MiB)':'FIFO retention (MiB)','Aplicar límite':'Apply limit',
    'Eliminar sesión':'Delete session','Buscar texto, altura, hash o error...':'Search text, height, hash or error...',
    'Archivo original:':'Original file:','Vista:':'View:',
    'Desde el inicio':'From the beginning',
    'No hay sesiones guardadas':'No saved sessions',
    'Cargando sesiones…':'Loading sessions…','Cargando sesión...':'Loading session...',
    'Esperando que el motor cree el log de esta sesión…':'Waiting for the miner to create this session log…',
    'Sesión protegida':'Protected session',
    'Peer Explorer':'Peer Explorer',
    'Datos P2P · almacenamiento compartido':'P2P data · Shared storage',
    'Conectividad':'Connectivity','Configuración de exploración':'Discovery settings',
    'Iniciar exploración':'Start discovery','Detener exploración':'Stop discovery',
    'Deteniendo exploración…':'Stopping discovery…','Actualizar historial':'Refresh history',
    'Direcciones anunciadas (getaddr)':'Advertised addresses (getaddr)',
    'Handshakes correctos':'Successful handshakes',
    'Conexiones simultáneas':'Concurrent connections','Intervalo entre rondas (segundos)':'Interval between rounds (seconds)',
    'Guardar configuración de exploración':'Save discovery settings',
    'Agregar peer':'Add peer','Agregar':'Add','Eliminar':'Delete',
    'Agregar endpoint (IP:puerto o DNS:puerto)':'Add endpoint (IP:port or DNS:port)',
    'Peers conocidos':'Known peers','Fuente':'Source','Fuentes':'Sources','Eventos':'Events',
    'Tamaño':'Size','Últimas 30 observaciones':'Last 30 observations',
    'Procedencia':'Provenance','Actividad detallada del Peer Explorer':'Peer Explorer detailed activity',
    'No hay peers':'No peers','Esperando actividad…':'Waiting for activity…',
    'Configuración guardada. Los cambios de hardware se aplican al reiniciar la minería.':
      'Settings saved. Hardware changes apply after restarting mining.',
    'Configuración guardada':'Settings saved',
    'Guardar preferencia':'Save preference','Guardar límite de SQLite':'Save SQLite limit',
    'Crear billetera':'Create wallet','Importar billetera':'Import wallet',
    'Nombre':'Name','Tipo de billetera':'Wallet type','Mi billetera':'My wallet',
    'Billetera importada':'Imported wallet','Billetera HD importada':'Imported HD wallet',
    'Legacy · Clave privada individual':'Legacy · Single private key',
    'Legacy · clave comprimida':'Legacy · compressed key',
    'Legacy · sin comprimir':'Legacy · uncompressed',
    'HD · semilla hexadecimal':'HD · hexadecimal seed','HD · billetera anterior':'HD · older wallet',
    'BIP39 · Frase semilla (HD)':'BIP39 · Seed phrase (HD)',
    'BIP32 · Semilla hexadecimal (HD)':'BIP32 · Hexadecimal seed (HD)',
    'Cantidad de palabras BIP39':'BIP39 word count',
    '12 palabras (predeterminado)':'12 words (default)','15 palabras':'15 words',
    '18 palabras':'18 words','21 palabras':'21 words','24 palabras':'24 words',
    'Longitud de semilla BIP32':'BIP32 seed length',
    '32 bytes · 64 caracteres hexadecimales':'32 bytes · 64 hexadecimal characters',
    '64 bytes · 128 caracteres hexadecimales':'64 bytes · 128 hexadecimal characters',
    'Ruta de derivación BIP44 (cuenta)':'BIP44 derivation path (account)',
    'Ruta de derivación BIP44':'BIP44 derivation path',
    'Ruta de derivación predeterminada':'Default derivation path',
    'Ruta BIP44 predeterminada':'Default BIP44 path',
    'Guardar ruta predeterminada':'Save default path',
    'Importar frase BIP39':'Import BIP39 phrase','Importar semilla HD':'Import HD seed',
    'Importar clave Legacy':'Import Legacy key',
    'Frase semilla de 12, 15, 18, 21 o 24 palabras · BIP39':'12, 15, 18, 21 or 24-word seed phrase · BIP39',
    'Frase de recuperación BIP39':'BIP39 recovery phrase',
    'Palabras BIP39 en inglés':'BIP39 words in English',
    'Semilla BIP32 (64 o 128 caracteres hexadecimales)':'BIP32 seed (64 or 128 hexadecimal characters)',
    '64 o 128 caracteres hexadecimales':'64 or 128 hexadecimal characters',
    '64 caracteres hexadecimales':'64 hexadecimal characters',
    'Clave privada hexadecimal (32 bytes)':'Hexadecimal private key (32 bytes)',
    'Legacy · clave privada individual hexadecimal (private_key_hex)':'Legacy · Single hexadecimal private key (private_key_hex)',
    'Primera dirección pública esperada (opcional, muy recomendable)':'Expected first public address (optional, strongly recommended)',
    'Dirección pública esperada (opcional, recomendada)':'Expected public address (optional, recommended)',
    'Comprobar direcciones':'Check addresses',
    'Primero verificá la dirección calculada antes de importar.':'Verify the calculated address before importing.',
    'Elegí el tipo. Las claves privadas se generan localmente con el generador criptográfico del sistema y se guardan protegidas mediante Windows DPAPI. Conservá el respaldo fuera de esta computadora.':
      'Choose a type. Private keys are generated locally using the system cryptographic generator and protected with Windows DPAPI. Keep a backup outside this computer.',
    'Elegí el formato original. Una clave individual no se convierte en HD; conserva su dirección. Los secretos nunca deben enviarse a un sitio web externo ni compartirse por chat.':
      'Choose the original format. A single key is not converted into HD; it keeps its address. Never send secrets to an external website or share them in chat.',
    'Confirmá que la ruta y la primera dirección coinciden con la billetera original. Sin passphrase BIP39 adicional: no importes si la original usa una.':
      'Confirm the path and first address match the original wallet. No additional BIP39 passphrase: do not import if the original uses one.',
    'Esta preferencia sólo afecta futuras creaciones e importaciones; nunca cambia las rutas de billeteras existentes.':
      'This preference only affects future wallet creation and imports; it never changes existing wallets’ paths.',
    'Modo de conexión con la red':'Network connection mode',
    'Electrum · modo normal automático':'Electrum · Automatic normal mode',
    'Servidor actual:':'Current server:','Sin conexión':'Disconnected',
    'Última actividad técnica:':'Last technical activity:',
    'Agregar servidor personalizado':'Add custom server',
    'Agregar servidor':'Add server','Puerto TLS':'TLS port',
    'Sincronizar todas':'Sync all',
    'Huella SHA-256 del certificado (opcional; solo para confianza explícita)':
      'Certificate SHA-256 fingerprint (optional; only for explicit trust)',
    'Completar servidor alternativo':'Fill alternate server',
    'Los servidores predeterminados se seleccionan automáticamente. TLS y verificación de red obligatorios.':
      'Default servers are selected automatically. TLS and network verification are required.',
    'Una conexión activa por red para consultar tus direcciones; elige servidores según disponibilidad, rapidez y fallos recientes, y cambia automáticamente si uno falla. No compara saldos entre operadores. Guarda sus métricas de conexión por red, sin claves ni direcciones.':
      'One active connection per network to query addresses; servers are chosen by availability, speed and recent failures, with automatic failover. It does not compare balances across operators. Connection metrics are saved per network, without keys or addresses.',
    'CashMiner 2.7.13.3 es experimental y no fue auditado. Windows DPAPI no sustituye un respaldo externo. No custodiar BCH reales hasta validar firma, sincronización y envío.':
      'CashMiner is experimental and has not been audited. Windows DPAPI does not replace an external backup. Do not hold real BCH until signing, synchronization and sending have been validated.',
    'Ver respaldo privado':'View private backup','Actualizar billetera':'Refresh wallet',
    'Historial':'History','Direcciones':'Addresses','Cargando direcciones…':'Loading addresses…',
    'Nombre de esta billetera':'Name of this wallet','Renombrar billetera':'Rename wallet',
    'Sólo cambia su nombre local. Las claves, direcciones y ruta BIP44 se conservan.':
      'Only its local name changes. Keys, addresses and BIP44 path are preserved.',
    'Eliminar billetera':'Delete wallet',
    'Elimina la billetera de CashMiner, su vault cifrado y su historial local. No mueve fondos en la red. Guardá antes tu frase o clave privada y su ruta si necesitás recuperarla.':
      'Deletes this wallet from CashMiner, its encrypted vault and local history. It does not move funds on the network. Back up your phrase or private key and path before deletion if you may need to recover it.',
    'Movimientos':'Transactions','Sin historial completo para esta billetera.':'No complete history for this wallet.',
    'Altura 0 o negativa = sin confirmar. Este historial conserva TXID y altura, no el valor neto de cada movimiento.':
      'Height zero or negative means unconfirmed. This history stores TXID and height, not the net value of each transaction.',
    'Recepción':'Receive','Cambio':'Change','Sin actividad':'No activity','Usada':'Used',
    'Emitida':'Issued','Anterior':'Previous','Siguiente':'Next',
    'Copiar':'Copy','Dirección copiada':'Address copied',
    'Cargar líneas anteriores':'Load earlier lines',
    'Respaldo privado':'Private backup',
    'Clave privada Legacy de una dirección':'Legacy single-address private key',
    'Semilla HD BIP32':'BIP32 HD seed','Frase BIP39':'BIP39 phrase',
    'Copiar al portapapeles':'Copy to clipboard',
    'Secreto copiado. El portapapeles contiene información privada.':'Secret copied. Your clipboard contains private information.',
    'Revelar secreto privado':'Reveal private secret',
    'El secreto aparecerá en pantalla. Evitá capturas, grabaciones y compartirlo.':
      'The secret will appear on screen. Avoid screenshots, recordings and sharing it.',
    'Mostrar':'Show','Crear':'Create','Importar':'Import',
    'Eliminar definitivamente':'Delete permanently',
    'Billetera renombrada':'Wallet renamed',
    'Billetera eliminada localmente':'Wallet deleted locally',
    'Sincronización solicitada':'Synchronization requested',
    'Ese ya es el nombre de la billetera':'That is already the wallet name',
    'Nombre de entre 1 y 60 caracteres':'Name must be 1 to 60 characters',
    'Escribí un nombre':'Enter a name',
    'Ingresá las palabras de recuperación':'Enter the recovery words',
    'La semilla BIP32 debe tener 64 o 128 caracteres hexadecimales':
      'BIP32 seed must contain 64 or 128 hexadecimal characters',
    'La clave cambió: comprobá otra vez':'The key changed: verify again',
    'Seleccioná la variante de dirección':'Select the address variant',
    'No se pudo leer la lista local:':'Could not read the local list:',
    'Verificá la dirección':'Verify the address',
    'Frase BIP39 importada':'BIP39 phrase imported',
    'Semilla BIP32 importada':'BIP32 seed imported',
    'Clave Legacy importada':'Legacy key imported',
    'Guardar':'Save',
    'Confirmar envío':'Confirm send','Confirmar envío ·':'Confirm send ·',
    'Última revisión. Esta operación difundirá una transacción irreversible si es aceptada por la red. No requiere contraseña.':
      'Final review. This operation will broadcast an irreversible transaction if accepted by the network. No password is required.',
    'Destinatario':'Recipient','Enviar todo (MAX)':'Send all (MAX)',
    'Importe:':'Amount:','Cambio:':'Change:','entradas':'inputs',
    'TXID previsto:':'Expected TXID:','Transmitir ahora':'Broadcast now',
    'Transmitiendo':'Broadcasting','Enviando transacción':'Sending transaction',
    'Esperando la respuesta del servidor Electrum.':'Waiting for the Electrum server response.',
    'Transacción enviada':'Transaction sent','El servidor rechazó el envío':'Server rejected the transaction',
    'Resultado del envío incierto':'Uncertain send result',
    'La transacción fue aceptada para difusión. Puede seguir sin confirmar.':
      'The transaction was accepted for broadcast. It may remain unconfirmed.',
    'El envío podría haberse difundido. No se reintentó automáticamente.':
      'The transaction may have been broadcast. It was not automatically retried.',
    'Volver a billetera':'Back to wallet','Consultar transacción':'View transaction',
    'Copiar TXID':'Copy TXID','TXID copiado':'TXID copied',
    'No se pudo copiar el TXID':'Could not copy TXID',
    'Elegí una billetera para enviar':'Select a wallet to send from',
    'Primero sincronizá y conectá la billetera':'Sync and connect the wallet first',
    'La red o la billetera cambió. Revisá de nuevo el envío':'Network or wallet changed. Review the send again',
    'Nombre de sesión':'Session name',
    'No se pudo completar la operación':'Could not complete the operation',
    'Error de proceso:':'Process error:',
    'Preferencias de visualización':'Display preferences',
    'Idioma':'Language','Formato numérico':'Number format',
    'Automático según idioma':'Automatic by language',
    'Punto de miles y coma decimal':'Thousands dot and decimal comma',
    'Coma de miles y punto decimal':'Thousands comma and decimal dot',
    'Los formatos de pantalla no alteran los satoshis ni las direcciones de la red.':
      'Display formatting does not change satoshis or network addresses.',
    'Se guardó el formato numérico':'Number format saved',
    'El formato numérico cambió. Revisá el importe antes de enviar.':
      'Number format changed. Check the amount before sending.',
    'Usá la coma como separador decimal.':'Use a comma as decimal separator.',
    'Usá el punto como separador decimal.':'Use a dot as decimal separator.',
    'Importe inválido: revisá los separadores decimales y de miles.':
      'Invalid amount: check decimal and thousands separators.',
    'No se pudo abrir el explorador en el navegador predeterminado:':
      'Could not open explorer in the default browser:',
    'No hay datos':'No data','Cargando historial...':'Loading history...',
    'Inicio:':'Started:','Última ronda:':'Last round:',
    'Próxima:':'Next:','Hasta':'Until',
    'Límite actualizado.':'Limit updated.',
  };
  Object.assign(EN, {
    'Agregar servidor TLS (host:puerto)':'Add TLS server (host:port)',
    'Alternativo Testnet3:':'Testnet3 alternative:',
    'Automático (usar el más prioritario disponible)':'Automatic (use the highest-priority available)',
    'BIP32 · semilla hexadecimal HD de 32 o 64 bytes':'BIP32 · 32 or 64-byte hexadecimal HD seed',
    'Buscando sesiones...':'Searching sessions…','Cadena':'Chain',
    'Candidatos de la ronda':'Round candidates','Cargando detalles…':'Loading details…',
    'Cargando peers…':'Loading peers…',
    'Contraseña RPC':'RPC password','Contraseña Stratum':'Stratum password',
    'Detalles':'Details',
    "Ejemplo: m/44'/145'/0'. Las direcciones se derivan agregando /0/0, /0/1, etc. La ruta queda vinculada a esta billetera.":
      "Example: m/44'/145'/0'. Addresses are derived by appending /0/0, /0/1, etc. The path remains linked to this wallet.",
    'El pool controla los pagos mediante tu usuario/worker, no mediante la dirección de coinbase seleccionada abajo.':
      'The pool controls payouts through your user/worker, not the coinbase address selected below.',
    'Elegí la versión que corresponde a tu dirección original.':'Choose the variant matching your original address.',
    'Eventos minero':'Miner events','Fallos':'Failures',
    'La identidad de bifurcación sólo se comprueba donde hay checkpoint disponible. No equivale a validación completa del consenso.':
      'Fork identity is only checked where a checkpoint is available. This is not full consensus validation.',
    'Los ajustes guardados se aplican en las próximas operaciones, no reinician la ronda en curso.':
      'Saved settings apply to subsequent operations; they do not restart the current round.',
    'Los resultados de conexión no implican validez de consenso. La compatibilidad de cadena es una observación separada del minero.':
      'Connection results do not prove consensus validity. Chain compatibility is a separate miner observation.',
    'Límite de base por red (MiB)':'Per-network database limit (MiB)',
    'Ninguna dirección calculada coincide con la esperada. No importes esta clave.':
      'No calculated address matches the expected address. Do not import this key.',
    'No se consultaron saldos.':'No balances were queried.','No se detectaron GPU.':'No GPUs detected.',
    'Peers conocidos en SQLite':'Known peers in SQLite','Peers nuevos en la ronda':'New peers this round',
    'Peers por ronda (0 = sin límite)':'Peers per round (0 = unlimited)',
    'Personalizados:':'Custom:', 'Ronda de esta ejecución':'Round in this run',
    'SQLite por red, compartida por Peer Explorer y minero. Este límite no es el FIFO de los logs originales ni configura las conexiones P2P.':
      'SQLite is shared per network by Peer Explorer and the miner. This limit is not the original-log FIFO and does not configure P2P connections.',
    'Se calculan ambas direcciones posibles, sin consulta de saldo ni selección automática.':
      'Both possible addresses are calculated without balance queries or automatic selection.',
    'Servidor Stratum':'Stratum server','Servidor preferido':'Preferred server',
    'Siguiente ↓':'Next ↓','↑ Anterior':'↑ Previous',
    'Sin acontecimientos recientes':'No recent events',
    'Sin motor compatible':'No compatible engine',
    'Sin peers conocidos todavía':'No known peers yet',
    'Sin procedencia registrada':'No recorded provenance',
    'Sin ronda iniciada':'No round started',
    'Sondeos fallidos':'Failed probes','Sondeos finalizados':'Completed probes',
    'Timeout de conexión (segundos)':'Connection timeout (seconds)',
    'Todavía no hay direcciones registradas.':'No recorded addresses yet.',
    'URL de tu nodo RPC':'Your RPC node URL',
    'Un secreto de 64 caracteres puede representar una clave privada Legacy o una semilla BIP32:':
      'A 64-character secret may be a Legacy private key or a BIP32 seed:',
    'no son intercambiables.':'they are not interchangeable.',
    'Usuario / worker del pool':'Pool user / worker','Usuario RPC':'RPC username',
    'Volver al presente ↓':'Jump to latest ↓',
    'Últimas 2.500 líneas del explorador en memoria. El registro original del minero se consulta por separado en «Diagnóstico del minero».':
      'Last 2,500 explorer lines kept in memory. The original miner log is available separately under Miner diagnostics.',
    'No se pudo detectar el hardware:':'Could not detect hardware:',
    '(BIP39/BIP32 · dirección fija)':'(BIP39/BIP32 · fixed address)',
    '(dirección fija)':'(fixed address)', '(HD anterior)':'(older HD)',
    'Peer':'Peer','Hash:':'Hash:','Padre:':'Parent:',
    'Enviando':'Sending','Red activa:':'Active network:',
  });

  // Audited additions in v2.11. These are interface strings, never miner logs.
  Object.assign(EN, {
    "Minería por red": "Mining by network",
    "Red de billeteras": "Wallet network",
    "Administrar billeteras": "Manage wallets",
    "No se pudo cargar la dirección": "Could not load the address",
    "QR local no disponible": "Local QR unavailable",
    "QR no disponible": "QR unavailable",
    "P2PKH · una dirección": "P2PKH · one address",
    "Minero": "Miner",
    "Origen:": "Origin:",
    "Iniciar exploración": "Start explorer",
    "Detener exploración": "Stop explorer",
    "Deteniendo exploración…": "Stopping explorer…",
    "Explorador iniciado": "Explorer started",
    "Servidor actual:": "Current server:",
    "Sin registrar": "Not recorded",
    "inactivo": "inactive",
    "conectado": "connected",
    "desconectado": "disconnected",
    "conectando": "connecting",
    "Sin conexión": "Not connected",
    "Última actividad técnica:": "Last technical activity:",
    "Nombre de esta billetera": "Name of this wallet",
    "Inmaduro:": "Immature:",
    "Tokens:": "Tokens:",
    "Entradas": "Inputs",
    "entradas": "inputs",
    "Copiar dirección": "Copy address",
    "Direcciones de la billetera": "Wallet addresses",
    "Cargando direcciones…": "Loading addresses…",
    "Rama": "Branch",
    "Total:": "Total:",
    "Sin observar": "Not observed",
    "Nunca": "Never",
    "No se pudo cargar la lista de direcciones.": "Could not load the address list.",
    "No se pudo leer la lista local:": "Could not read local list:",
    "Cambio:": "Change:",
    "Recibido:": "Received:",
    "Importe:": "Amount:",
    "Enviar todo (MAX)": "Send all (MAX)",
    "Transmitir ahora": "Broadcast now",
    "Enviando transacción": "Broadcasting transaction",
    "Esperando la respuesta del servidor Electrum.": "Waiting for the Electrum server response.",
    "Última revisión. Esta operación difundirá una transacción irreversible si es aceptada por la red. No requiere contraseña.": "Final review. If accepted by the network, this operation broadcasts an irreversible transaction. No password is required.",
    "Transacción enviada": "Transaction broadcast",
    "El servidor rechazó el envío": "Server rejected the transaction",
    "Resultado del envío incierto": "Uncertain transaction outcome",
    "La transacción fue aceptada para difusión. Puede seguir sin confirmar.": "The transaction was accepted for broadcast. It may still be unconfirmed.",
    "El envío podría haberse difundido. No se reintentó automáticamente.": "The transaction may have been broadcast. It was not retried automatically.",
    "Consultar transacción": "View transaction",
    "Copiar TXID": "Copy TXID",
    "TXID copiado": "TXID copied",
    "No se pudo copiar el TXID": "Could not copy TXID",
    "Volver a billetera": "Back to wallet",
    "CashMiner no pudo conocer el resultado del envío:": "CashMiner could not determine the transaction outcome:",
    "Actualización de billetera pendiente": "Wallet update pending",
    "No confundas esta clave con una semilla HD.": "Do not confuse this key with an HD seed.",
    "No la compartas, fotografíes ni guardes solamente en la PC.": "Do not share or photograph it, or store it only on this PC.",
    "estas palabras": "these words",
    "este secreto": "this secret",
    "Ruta:": "Path:",
    "Última actividad técnica": "Last technical activity",
    "Estado:": "Status:",
    "(certificado autofirmado). No se conecta automáticamente. Para utilizarlo, comprobá su huella SHA-256 mediante una fuente confiable y agregalo con esa huella; CashMiner rechazará certificados distintos.": "(self-signed certificate). It is not connected automatically. To use it, verify its SHA-256 fingerprint through a trusted source and add it with that fingerprint; CashMiner will reject different certificates.",
    "Ruta inválida. Usá m/44'/145'/0' (formato BIP44 con cuenta de 0 a 1000)": "Invalid path. Use m/44'/145'/0' (BIP44 format, account 0 to 1000)",
    "Se generará un secreto nuevo. Su respaldo aparecerá una sola vez después de la creación; guardalo fuera de esta PC.": "A new secret will be generated. Its backup will appear only once after creation; store it outside this PC.",
    "Volvé a comprobar las direcciones antes de importar.": "Check the addresses again before importing.",
    "La dirección esperada cambió. Volvé a comprobar.": "Expected address changed. Check again.",
    "La clave cambió: comprobá otra vez": "The key changed: check again",
    "Red activa:": "Active network:",
    "El motor comparte el mismo código CPU/GPU, pero los trabajos se obtienen según la red. Testnet P2P-tip es experimental y utiliza Electrum como referencia, NO valida la cadena completa. Mainnet requiere un nodo RPC o un pool Stratum.": "The engine uses the same CPU/GPU code, but jobs are obtained for the selected network. Testnet P2P-tip is experimental and uses Electrum as a reference; it does NOT validate the full chain. Mainnet requires an RPC node or a Stratum pool.",
    "Se aplica al próximo arranque en modalidad P2P-tip. Entero de 1 a 80; 2 es el valor inicial, 1 es experimental y 0 no está permitido. Si la red no ofrece suficientes peers compatibles, no se inicia la minería.": "Applies on the next start in P2P-tip mode. Enter an integer from 1 to 80; 2 is the default, 1 is experimental and 0 is not allowed. If the network has too few compatible peers, mining will not start.",
    "Exclusivos del minero P2P-tip; no modifican los servidores de tus billeteras. Conexiones TLS con certificado verificado y coincidencia de red obligatoria. Si falla uno, prueba el siguiente. Sólo se aplica en el próximo arranque.": "These servers are only for the P2P-tip miner and do not modify your wallet servers. TLS certificates must be verified and the network must match. If one fails, the next is tried. Changes apply at the next start.",
    "Explora endpoints por DNS y getaddr, guarda antecedentes en SQLite y funciona de forma independiente del minero. El minero incorpora otras observaciones a la misma base, sin usar puntuaciones como autoridad de consenso.": "Discovers endpoints via DNS and getaddr, stores observations in SQLite and runs independently of the miner. The miner adds its own observations to the same database; scores are never treated as consensus authority.",
    "Se actualiza automáticamente mientras esta sección está abierta, incluso cuando sólo está minando. Conectividad y cadena son observaciones diferentes. Los nuevos candidatos pueden utilizarse desde el próximo arranque del minero.": "Updates automatically while this section is open, including while only the miner is running. Connectivity and chain status are separate observations. New candidates may be used after the miner restarts.",
    "Cargando peers…": "Loading peers…",
    "Sin candidatos en esta ronda": "No candidates this round",
    "Esperando actividad…": "Waiting for activity…",
    "Activo · esperando": "Active · waiting",
    "Preparando": "Preparing",
    "Explorando": "Exploring",
    "Esperando": "Waiting",
    "Activo": "Active",
    "Iniciando": "Starting",
    "Deteniendo": "Stopping",
    "Ronda": "Round",
    "Sondeos finalizados": "Completed probes",
    "de": "of",
    "Buscar anterior": "Find previous",
    "Buscar siguiente": "Find next",
    "Límite de almacenamiento de logs en MiB": "Log storage limit (MiB)",
    "Eliminar sesión seleccionada": "Delete selected session",
    "Registro original del minero": "Original miner log",
    "Progreso de la exploración": "Explorer progress",
    "Porcentaje de": "Percentage for",
    "Sin backend compatible": "No compatible backend",
    "Sin motor compatible": "No compatible engine",
    "ninguna": "none",
    "Personalizado": "Custom",
    "Personalizados:": "Custom:",
    "Eventos del minero:": "Miner events:",
    "Último handshake satisfactorio:": "Last successful handshake:",
    "Última observación de compatibilidad:": "Last compatible observation:",
    "Última observación de incompatibilidad:": "Last incompatible observation:",
    "Última cabecera:": "Latest header:",
    "Procedencia": "Provenance",
    "Últimas 30 observaciones": "Last 30 observations",
    "Explorador / registro P2P": "Explorer / P2P record",
    "Conectividad": "Connectivity",
    "Compatible observada": "Observed compatible",
    "Incompatible observada": "Observed incompatible",
    "Sin verificar": "Not verified",
    "Ocultar": "Hide",
    "Ver": "View",
    "Más de una red no puede minar simultáneamente": "Multiple networks cannot mine simultaneously",
    "Sin bloques encontrados.": "No blocks found.",
    "Pertenencia no determinada": "Chain membership undetermined",
    "Fuera de cadena observada": "Observed off chain",
    "No difundido (obsoleto)": "Not broadcast (stale)",
    "Rama competidora": "Competing branch",
    "Reorganización": "Reorganization",
    "Sin más acontecimientos registrados.": "No further recorded events.",
    "Todavía no hay sesiones registradas en esta versión.": "No sessions recorded in this version yet.",
    "Cargando sesión...": "Loading session…",
    "Esperando que el motor cree el log de esta sesión…": "Waiting for the miner to create the log for this session…",
    "No hay sesiones guardadas": "No saved sessions",
    "Log original:": "Original log:",
    "Sesión eliminada:": "Session deleted:",
    "Confirmar eliminación": "Confirm deletion",
    "Eliminar sesión": "Delete session",
    "No hay más líneas anteriores.": "No earlier lines available.",
    "Desde el inicio": "From the beginning",
    "Hay líneas anteriores disponibles": "Earlier lines available",
    "Archivo original:": "Original file:",
    "Vista:": "View:",
    "Sin archivo original": "No original file",
    "Escribí un texto para buscar en el archivo completo": "Enter text to search the whole file",
    "No se pudo leer el registro original": "Could not read the original log",
    "Todavía no hay un archivo de minería seleccionado": "No mining log file selected yet",
    "La sesión protegida excede el límite.": "The protected session exceeds the limit.",
    "No se pudo copiar el registro": "Could not copy the log",
    "El explorador todavía no tiene líneas para copiar": "Explorer has no lines to copy yet",
    "Registro del Peer Explorer copiado": "Peer Explorer log copied",
    "Sin más coincidencias para": "No more matches for",
    "Inicio:": "Started:",
    "Última ronda:": "Last round:",
    "Próxima:": "Next:",
    "Última incidencia:": "Latest issue:",
    "Fuentes:": "Sources:",
    "Eventos:": "Events:",
    "Tamaño:": "Size:",
    "en SQLite": "in SQLite",
    "Ingresá un número entero de peers entre 1 y 80": "Enter an integer peer count from 1 to 80",
    "Mínimo de peers: el valor debe estar entre 1 y 80": "Minimum peers: value must be between 1 and 80",
    "Mínimo para minería guardado; se aplica al próximo arranque": "Mining peer minimum saved; applies on the next start",
    "Configuración guardada. Los cambios de hardware se aplican al reiniciar la minería.": "Settings saved. Hardware changes apply when mining is restarted.",
    "Cada dispositivo compatible necesita un porcentaje entre 0 y 100.": "Each compatible device needs a percentage between 0 and 100.",
    "Porcentaje inválido para un dispositivo.": "Invalid percentage for a device.",
    "No se pudo detectar el hardware. Usá «Volver a detectar hardware» antes de guardar.": "Hardware could not be detected. Use “Detect hardware again” before saving.",
    "Servidor TLS agregado para la próxima sesión": "TLS server added for the next session",
    "Servidor eliminado de la lista de minería": "Server removed from the mining list",
    "Preferencia de servidor guardada para la próxima sesión": "Server preference saved for the next session",
    "Configuración de exploración guardada": "Explorer settings saved",
    "Límite de SQLite guardado": "SQLite limit saved",
    "Límite entre 1 y 10240 MiB": "Limit must be between 1 and 10240 MiB",
    "Límite actualizado.": "Limit updated.",
    "No se pudo copiar la dirección": "Could not copy address",
    "Error de proceso:": "Process error:",
    "Contiene": "Contains",
    "Semilla": "Seed"
});
  // Only explicitly recognized UI patterns are interpolated; arbitrary wallet names,
  // secrets, addresses, TXIDs and log lines are deliberately never translated.
  const DYNAMIC_MESSAGES=[
    [/^Red activa: ([^.]+)\. P2P utiliza la referencia propia de cada red y NO valida bloques completos\. Mainnet P2P \(Electrum asistido\) es experimental: confirma BCH mediante checkpoints y peers, sin validar bloques completos\. Regtest P2P sigue pendiente\.$/,
      m=>'Active network: '+m[1]+'. P2P uses the selected network tip reference and does not fully validate blocks. Mainnet Electrum-assisted P2P is experimental: it checks BCH checkpoints and peers, but does not perform full block validation. Regtest P2P is not implemented yet.'],
    [/^Red activa: ([^.]+)\. El motor comparte el mismo código CPU\/GPU, pero los trabajos se obtienen según la red\. Testnet P2P-tip es experimental y utiliza Electrum como referencia, NO valida la cadena completa\. Mainnet requiere un nodo RPC o un pool Stratum\.$/,
      m=>'Active network: '+m[1]+'. The engine uses the same CPU/GPU code, but jobs are obtained for the selected network. Testnet P2P-tip is experimental and uses Electrum as a reference; it does NOT validate the full chain. Mainnet requires an RPC node or a Stratum pool.'],
    [/^Última actividad técnica: (.+)\. Estado: (.+)$/,
      m=>'Last technical activity: '+t(m[1])+'. Status: '+t(m[2])],
    [/^CPU · (\d+) hilos · Nativa$/,
      m=>'CPU · '+m[1]+' threads · Native'],
    [/^GPU · Sin backend compatible$/,
      m=>'GPU · No compatible backend'],
    [/^([\d.,]+ (?:BCH|tBCH)) · Inmaduro: ([\d.,]+ (?:BCH|tBCH))( · Tokens: (.+))?$/,
      m=>m[1]+' · Immature: '+m[2]+(m[4]?' · Tokens: '+m[4]:'')],
    [/^Recepción: (\d+) · Cambio: (\d+) · Total: (\d+)$/,
      m=>'Receive: '+m[1]+' · Change: '+m[2]+' · Total: '+m[3]],
    [/^(Recepción|Cambio) · Rama (\d+)$/,
      m=>t(m[1])+' · Branch '+m[2]],
    [/^Copiar dirección #(\d+)$/,
      m=>'Copy address #'+m[1]],
    [/^Cambio: ([\d.,]+ \w+) · (\d+) entradas$/,
      m=>'Change: '+m[1]+' · '+m[2]+' inputs'],
    [/^\. Quien tenga (estas palabras|este secreto) puede gastar los fondos de esta billetera\.\s+(No confundas esta clave con una semilla HD\. )?No la compartas, fotografíes ni guardes solamente en la PC\. ?(Ruta: (.+)\.)?$/,
      m=>'. Anyone with '+(m[1]==='estas palabras'?'these words':'this secret')+' can spend the funds in this wallet. '+(m[2]?'Do not confuse this key with an HD seed. ':'')+'Do not share it, photograph it, or store it only on this PC. '+(m[4]?'Path: '+m[4]+'.':'')],
    [/^Último handshake satisfactorio: (.*)$/,
      m=>'Last successful handshake: '+t(m[1])],
    [/^Última observación de compatibilidad: (.*)$/,
      m=>'Last compatible observation: '+t(m[1])],
    [/^Última observación de incompatibilidad: (.*)$/,
      m=>'Last incompatible observation: '+t(m[1])],
    [/^Última cabecera: (.*)$/,
      m=>'Latest header: '+m[1]],
    [/^Eventos del minero: (\d+)$/,
      m=>'Miner events: '+m[1]],
    [/^En cadena observada: (\d+)$/,
      m=>'Observed on chain: '+m[1]],
    [/^(.+?) · (\d+) en cadena \/ (\d+) hallados · (\d+) por verificar · (.+)$/,
      m=>m[1]+' · '+m[2]+' on chain / '+m[3]+' found · '+m[4]+' to verify · '+t(m[5])],
    [/^#(\d+) · (Usada|Emitida|Sin actividad)$/,
      m=>'#'+m[1]+' · '+t(m[2])],
    [/^ · Inmaduro: ([\d.,]+ \w+)$/,
      m=>' · Immature: '+m[1]],
    [/^Quedan sin gastar (\d+) UTXO no rentables \((\d+) sats\)\.$/,
      m=>'Leaving '+m[1]+' uneconomical UTXOs unspent ('+m[2]+' sats).'],
    [/^Sin más coincidencias para «(.+)»$/,
      m=>'No more matches for “'+m[1]+'”'],
    [/^Archivo original: (.+) · Vista: ([\d.]+) KiB de ([\d.]+) KiB(.*)$/,
      m=>'Original file: '+m[1]+' · View: '+m[2]+' KiB of '+m[3]+' KiB'+t(m[4])],
    [/^(\d+) de (\d+) sondeos finalizados \((\d+) %\)$/,
      m=>m[1]+' of '+m[2]+' probes completed ('+m[3]+'%)'],
    [/^Peers: (\d+) · Fuentes: (\d+) · Eventos: (\d+) · Tamaño: (.*)$/,
      m=>'Peers: '+m[1]+' · Sources: '+m[2]+' · Events: '+m[3]+' · Size: '+m[4]],
    [/^Inicio: (.+) · Última ronda: (.+) · Próxima: (.+)$/,
      m=>'Started: '+m[1]+' · Last round: '+m[2]+' · Next: '+m[3]],
    [/^Última incidencia: (.+)$/,
      m=>'Latest issue: '+m[1]],
    [/^(\d+) en SQLite$/,
      m=>m[1]+' in SQLite'],
    [/^Porcentaje de (.+)$/,
      m=>'Percentage for '+m[1]],
    [/^(Detener|Iniciar) minería en (.+)$/,
      m=>(m[1]==='Detener'?'Stop':'Start')+' mining on '+m[2]],
    [/^Configurar minería · (.+)$/,
      m=>'Configure mining · '+m[1]],
    [/^Estado: (.+?)( · Ronda (\d+))?$/,
      m=>'Status: '+t(m[1])+(m[3]?' · Round '+m[3]:'')],
    [/^Registro del Peer Explorer copiado \((\d+) líneas\)$/,
      m=>'Peer Explorer log copied ('+m[1]+' lines)'],
    [/^Log completo copiado \((\d+) caracteres\)$/,
      m=>'Full log copied ('+m[1]+' characters)'],
    [/^Límite actualizado\. (\d+) sesiones antiguas eliminadas\.(.*)$/,
      m=>'Limit updated. '+m[1]+' older sessions deleted.'+t(m[2])],
    [/^Sesión eliminada: (.+)$/,
      m=>'Session deleted: '+m[1]],
    [/^Agregados: (.+)$/,
      m=>'Added: '+m[1]],
    [/^Log exportado: (.+)$/,
      m=>'Log exported: '+m[1]],
    [/^Error de proceso: (.+)$/,
      m=>'Process error: '+t(m[1])],
    [/^CashMiner no pudo conocer el resultado del envío: (.+)$/,
      m=>'CashMiner could not determine the transaction outcome: '+t(m[1])],
    [/^No se pudo abrir el explorador en el navegador predeterminado: (.+)$/,
      m=>'Could not open the explorer in the default browser: '+t(m[1])],
    [/^No se pudo leer la lista local: (.+)$/,
      m=>'Could not read local list: '+t(m[1])],
    [/^No se pudo detectar el hardware: (.+)$/,
      m=>'Could not detect hardware: '+t(m[1])],
    [/^Ruta por defecto de (.+) actualizada\. No se modificaron las billeteras existentes\.$/,
      m=>'Default path for '+m[1]+' updated. Existing wallets were not changed.'],
    [/^Frase BIP39 importada en (.+)$/,
      m=>'BIP39 phrase imported on '+m[1]],
    [/^Semilla BIP32 importada en (.+)$/,
      m=>'BIP32 seed imported on '+m[1]],
    [/^Clave Legacy importada en (.+)$/,
      m=>'Legacy key imported on '+m[1]],
  ];

  // User-visible errors reported by the local wallet and miner APIs.
  Object.assign(EN, {
    "Sesión de log no válida": "Invalid log session",
    "Posición de lectura no válida": "Invalid read position",
    "Cursores de lectura inválidos": "Invalid read cursors",
    "Red desconocida": "Unknown network",
    "Red de billetera desconocida": "Unknown wallet network",
    "Cambió la red de billeteras. Volvé a abrir el diálogo": "Wallet network changed. Reopen the dialog",
    "Cambió la red de billeteras. Reabrí el diálogo": "Wallet network changed. Reopen the dialog",
    "Cambió la red de billeteras. Cerrá el diálogo y volvé a abrirlo": "Wallet network changed. Close and reopen the dialog",
    "Cambió la red de billeteras; actualizá la vista": "Wallet network changed. Refresh the view",
    "Idioma desconocido": "Unknown language",
    "Formato numérico desconocido": "Unknown number format",
    "La configuración por dispositivo requiere un valor verdadero": "Per-device configuration requires true",
    "Destino desconocido": "Unknown destination",
    "Red de minería desconocida": "Unknown mining network",
    "Detené este minero antes de cambiar su conexión": "Stop this miner before changing its connection",
    "Cambió la red del minero; reabrí la configuración": "Mining network changed. Reopen settings",
    "Modo incompatible con la red": "Mode is incompatible with this network",
    "Minería ya activa": "Mining is already running",
    "Peer no encontrado en la base de esta red": "Peer not found in this network database",
    "Log inválido": "Invalid log",
    "No se pudo abrir el navegador predeterminado": "Could not open default browser",
    "Detené el minero de esta red antes de eliminar su billetera de recompensas": "Stop this network miner before deleting its reward wallet",
    "Mínimo de peers: escribí un número entero de 1 a 80": "Minimum peers: enter an integer from 1 to 80",
    "Máximo 12 servidores Electrum personalizados": "Maximum of 12 custom Electrum servers",
    "Selección Electrum para minería P2P sólo en Testnet3/Testnet4/Chipnet": "P2P mining Electrum selection is only available on Testnet3/Testnet4/Chipnet",
    "El servidor preferido debe pertenecer a la lista de esta red": "Preferred server must be on this network server list",
    "Credenciales RPC demasiado largas": "RPC credentials are too long",
    "Payload fuera de tamaño admitido": "Payload exceeds supported size",
    "Usuario/contraseña Stratum inválidos": "Invalid Stratum username/password",
    "No hay billeteras en esta red: creá/importá una o configurá una dirección externa": "No wallets on this network: create/import one or configure an external address",
    "Modo de destino no válido": "Invalid destination mode",
    "WebSocket P2P aún no compatible; ingresá TCP o un dominio DNS": "P2P WebSocket is not supported yet; use TCP or a DNS hostname",
    "Página de direcciones inválida": "Invalid address page",
    "La billetera de minería no existe en la red seleccionada": "Mining wallet does not exist on the selected network",
    "Red o TXID inválido para el explorador": "Invalid network or TXID for explorer",
    "Identificador de billetera inválido": "Invalid wallet identifier",
    "Formato de respaldo inválido": "Invalid backup format",
    "Almacén de claves incorrecto o de otra red": "Incorrect key store or wrong network",
    "Formato de semilla no reconocido": "Unrecognized seed format",
    "La semilla recuperada tiene tamaño inesperado": "Recovered seed has an unexpected size",
    "Una clave privada individual no es una semilla HD": "A single private key is not an HD seed",
    "La semilla no coincide con la billetera": "Seed does not match the wallet",
    "La billetera no contiene una clave Legacy": "Wallet does not contain a Legacy key",
    "La clave privada no coincide con la dirección de la billetera": "Private key does not match the wallet address",
    "Clave privada inválida": "Invalid private key",
    "La clave Legacy debe contener 64 caracteres hexadecimales": "Legacy key must contain 64 hexadecimal characters",
    "Clave privada fuera del rango secp256k1": "Private key is out of secp256k1 range",
    "Escribí un nombre de hasta 60 caracteres": "Enter a name of up to 60 characters",
    "La cuenta HD debe estar entre 0 y 1000": "HD account must be between 0 and 1000",
    "Indicá una sola forma de recuperación": "Provide exactly one recovery method",
    "Tipo de billetera desconocido": "Unknown wallet type",
    "Sólo se generan semillas HD de 32 o 64 bytes": "Only 32 or 64-byte HD seeds can be generated",
    "BIP39 requiere 12, 15, 18, 21 o 24 palabras": "BIP39 requires 12, 15, 18, 21 or 24 words",
    "Selección de clave comprimida inválida": "Invalid compressed-key selection",
    "Antes de importar una clave Legacy, confirmá la dirección pública calculada": "Before importing a Legacy key, confirm the calculated public address",
    "La dirección calculada no coincide con la dirección esperada": "Calculated address does not match the expected address",
    "Billetera inexistente": "Wallet does not exist",
    "Escribí un nombre de entre 1 y 60 caracteres": "Enter a name between 1 and 60 characters",
    "El nombre contiene caracteres de control": "Name contains control characters",
    "Tamaño de página inválido": "Invalid page size",
    "Referencia de cadena inválida": "Invalid chain reference",
    "UTXO duplicado en el snapshot": "Duplicate UTXO in snapshot",
    "Direcciones duplicadas en sincronización": "Duplicate addresses during sync",
    "Actualización de una dirección no descubierta": "Attempted update of an undiscovered address",
    "El salto de altura no es consecutivo": "Block height jump is not consecutive",
    "Una wallet Legacy utiliza su dirección fija para el cambio": "A Legacy wallet uses its fixed address for change",
    "La transacción preparada tiene entradas duplicadas": "Prepared transaction has duplicate inputs",
    "Faltan direcciones de origen para el gasto local": "Source addresses missing for local spend",
    "La transacción contiene entradas repetidas": "Transaction has repeated inputs",
    "Nombre de servidor no válido": "Invalid server name",
    "Puerto inválido": "Invalid port",
    "Cuenta HD y ruta de derivación contradictorias": "HD account conflicts with derivation path",
    "Una clave Legacy no admite ruta HD": "Legacy keys cannot have an HD path",
    "Una clave Legacy no tiene cuentas HD": "Legacy keys have no HD accounts",
    "Esta billetera ya existe en esta red": "This wallet already exists on this network",
    "Límite de direcciones de recepción": "Receive address limit reached",
    "Dirección HD registrada no coincide con la derivación": "Stored HD address does not match derivation",
    "Billetera eliminada": "Wallet deleted",
    "Límite de direcciones de cambio": "Change address limit reached",
    "Dirección de cambio HD incompatible con el índice guardado": "HD change address does not match saved index",
    "La billetera necesita sincronizarse antes de transmitir": "Wallet must sync before broadcasting",
    "Huella TLS SHA-256 inválida: deben ser 64 caracteres hexadecimales": "Invalid TLS SHA-256 fingerprint: must be 64 hexadecimal characters",
    "Puerto de Mainnet incorrecto para Testnet3": "Mainnet port is invalid for Testnet3",
    "Ese servidor autofirmado requiere una huella TLS SHA-256 verificada y aprobada": "That self-signed server requires a verified and approved TLS SHA-256 fingerprint",
    "Clave privada Legacy inválida": "Invalid Legacy private key",
    "La billetera cambió. Actualizá la pantalla antes de eliminarla": "Wallet changed. Refresh before deleting it",
    "No se encontró el respaldo cifrado; no se eliminó la billetera": "Encrypted backup not found; wallet was not deleted",
    "UTXO duplicado para una dirección": "Duplicate UTXO for an address",
    "Los UTXO de esta vista previa cambiaron; prepará el envío nuevamente": "The preview UTXOs changed; prepare the send again",
    "Entrada firmada no pertenece a la billetera": "Signed input does not belong to the wallet",
    "Semilla hexadecimal inválida": "Invalid hexadecimal seed",
    "No se pudo restaurar el vault cifrado tras el fallo; conservá el archivo de recuperación local": "Could not restore encrypted vault after failure; keep the local recovery file",
    "Ingresá un importe decimal positivo, sin separadores de miles": "Enter a positive decimal amount without thousands separators",
    "El importe debe tener hasta ocho decimales y ser al menos 546 sats": "Amount must have no more than eight decimals and be at least 546 sats",
    "Ingresá una comisión positiva en sat/byte (punto o coma decimal)": "Enter a positive fee in sat/byte (dot or comma as decimal separator)",
    "La comisión debe ser mayor que cero y hasta 1.000 sat/byte": "Fee must be greater than zero and at most 1,000 sat/byte",
    "La billetera no tiene proveedor Electrum válido": "Wallet has no valid Electrum provider",
    "Primero sincronizá completamente esta billetera": "Sync this wallet completely first",
    "La comprobación de saldos es antigua; actualizá la billetera": "Balance check is stale; refresh the wallet",
    "Importe BCH inválido": "Invalid BCH amount",
    "Comisión inválida": "Invalid fee",
    "Estado de sincronización inválido": "Invalid sync state",
    "Dirección destinataria inválida": "Invalid recipient address",
    "Modo MAX inválido": "Invalid MAX mode",
    "No hay UTXOs gastables según Electrum": "No spendable UTXOs according to Electrum",
    "La vista previa venció o no corresponde a esta billetera": "Preview expired or does not belong to this wallet",
    "Ruta:": "Path:"
});

  Object.assign(EN, {
    'Actividad del Peer Explorer':'Peer Explorer activity',
    'Aumentar letra':'Increase font size',
    'Bloques propios observados en cadena (esta sesión; no son confirmaciones irreversibles)':
      'Own blocks observed on chain (this session; not irreversible confirmations)',
    'Buscar texto o hash en el log completo':'Search text or hash in the full log',
    'Controles independientes de los mineros':'Controls independent of miners',
    'Elegir sesión de minería':'Select mining session',
  });
  const DYNAMIC_PREFIXES=[
    ['Minería · ','Mining · '],['Minando · ','Mining · '],
    ['Servidores Electrum de minería · ','Mining Electrum servers · '],
    ['Bibliotecas incluidas: ','Included libraries: '],['No se pudo detectar el hardware: ','Could not detect hardware: '],['Mis billeteras · ','My wallets · '],
    ['Movimientos · ','Transactions · '],['Respaldo privado · ','Private backup · '],
    ['Confirmar envío · ','Confirm send · '],['Eliminar billetera · ','Delete wallet · '],
    ['Crear billetera · ','Create wallet · '],['Importar clave Legacy · ','Import Legacy key · '],
    ['Transmitiendo · ','Broadcasting · '],
    ['Monto ','Amount '],['Destino público: ','Public destination: '],
    ['Billetera: ','Wallet: '],['Servidor actual: ','Current server: '],
    ['Error de proceso: ','Process error: '],
    ['Quedan sin gastar ','Unspent: '],['Página ','Page '],['Bloque ','Block '],
    ['No se pudo leer la lista local: ','Could not read the local list: '],
    ['Sincronización solicitada','Synchronization requested'],
    ['No se pudo copiar la dirección','Could not copy address'],
  ];
  Object.assign(EN,{
    'Unidad del importe':'Amount unit',
    'Cotización no disponible. Usá BCH.':'Rate unavailable. Use BCH.',
    'Cotización no disponible o importe fiat inválido.':'Rate unavailable or invalid fiat amount.',
    'Importe fiat inválido.':'Invalid fiat amount.',
    'Importe ingresado:':'Entered amount:',
    'Mínimo 546 sats':'Minimum 546 sats',
    'Importe BCH inválido.':'Invalid BCH amount.'
  });
  const DYNAMIC_SUFFIXES=[[' (BIP39/BIP32 · dirección fija)',' (BIP39/BIP32 · fixed address)'],
    [' (dirección fija)',' (fixed address)'],[' (HD anterior)',' (older HD)']];
  function read(key,fallback){try {return localStorage.getItem(key)||fallback} catch{return fallback}}
  function store(key,val){try{localStorage.setItem(key,val)}catch{}}
  let language=['es','en'].includes(read(LANGUAGE_KEY,'es'))?read(LANGUAGE_KEY,'es'):'es';
  let numberFormat=['auto','es','en'].includes(read(FORMAT_KEY,'auto'))?read(FORMAT_KEY,'auto'):'auto';
  function getLocale(){return numberFormat==='auto'?(language==='es'?'es-AR':'en-US'):(numberFormat==='es'?'es-AR':'en-US')}
  function t(input){
    const source=String(input??'');if(language!=='en'||!source.trim())return source;
    const lead=source.match(/^\s*/)[0], trail=source.match(/\s*$/)[0];
    const value=source.slice(lead.length,source.length-trail.length);
    if(Object.prototype.hasOwnProperty.call(EN,value))return lead+EN[value]+trail;
    for(const [pattern,render] of DYNAMIC_MESSAGES){const found=pattern.exec(value);if(found)return lead+render(found)+trail;}
    for(const [a,b] of DYNAMIC_PREFIXES)if(value.startsWith(a))return lead+b+value.slice(a.length)+trail;
    for(const [a,b] of DYNAMIC_SUFFIXES)if(value.endsWith(a))return lead+value.slice(0,-a.length)+b+trail;
    // Don't translate arbitrary user-supplied names, URLs, logs or key material.
    return source;
  }
  function formatNumber(value,options={}){
    const n=Number(value);return Number.isFinite(n)?new Intl.NumberFormat(getLocale(),options).format(n):String(value);
  }
  function formatSats(value,options={}){
    const min=Math.max(0,Math.min(8,options.min??2));
    const max=Math.max(min,Math.min(8,options.max??8));
    let sat;
    try { sat=typeof value==='bigint'?value:BigInt(String(value)); }
    catch {return String(value)}
    const neg=sat<0n; if(neg)sat=-sat;
    const intPart=sat/100000000n;
    const intString=intPart.toString().replace(/\B(?=(\d{3})+(?!\d))/g,getLocale()==='es-AR'?'.':',');
    let frac=(sat%100000000n).toString().padStart(8,'0').slice(0,max);
    while(frac.length>min&&frac.endsWith('0'))frac=frac.slice(0,-1);
    return (neg?'-':'')+intString+(frac?(getLocale()==='es-AR'?',':'.')+frac:'');
  }
  function formatBch(sats,unit,opts){return formatSats(sats,opts)+' '+unit}
  function normalizeInput(value){
    const str=String(value??'').trim();if(!str)return '';
    const es=getLocale()==='es-AR';
    const decimal=es?',':'.',group=es?'.':',';
    // No scientific notation, signs, whitespace or uncontrolled floating-point conversion.
    const validPlain=new RegExp('^\\d+(?:\\'+decimal+'\\d+)?$');
    const validGrouped=new RegExp('^\\d{1,3}(?:\\'+group+'\\d{3})+(?:\\'+decimal+'\\d+)?$');
    if(!validPlain.test(str)&&!validGrouped.test(str)){
      throw new Error(t('Importe inválido: revisá los separadores decimales y de miles.'));
    }
    return str.split(group).join('').replace(decimal,'.');
  }
  const ignoredSelectors='script,style,pre,code,.logbox,#minerLog,#peerLog,#walletReceiveAddress,#recoverySeed,#sendAddress,#sendFeeRate,#walletTitle,#walletList strong,.inline-code,.path,[data-cm-no-translate]';
  function ignored(node){const parent=node.nodeType===1?node:node.parentElement;return !parent||!!parent.closest(ignoredSelectors)}
  const originalNodes=new WeakMap(), translatedNodes=new WeakMap();
  const originalAttrs=new WeakMap(),translatedAttrs=new WeakMap();
  const ATTRS=['placeholder','title','aria-label'];
  const ATTR_ONLY=new Set(['minerLog','walletReceiveAddress','peerLog']);
  let observer, queued=false;
  function translateNode(node){
    if(ignored(node))return;
    const now=node.nodeValue;
    if(!originalNodes.has(node)||now!==translatedNodes.get(node))originalNodes.set(node,now);
    const original=originalNodes.get(node);const result=t(original);
    translatedNodes.set(node,result);
    if(now!==result)node.nodeValue=result;
  }
  function translateAttrs(el){
    if(ignored(el)&&!ATTR_ONLY.has(el.id))return;
    let origins=originalAttrs.get(el),last=translatedAttrs.get(el);
    if(!origins){origins={};last={};originalAttrs.set(el,origins);translatedAttrs.set(el,last)}
    for(const attr of ATTRS){
      if(!el.hasAttribute(attr))continue;
      const now=el.getAttribute(attr);
      if(!(attr in origins)||now!==last[attr])origins[attr]=now;
      const value=t(origins[attr]);last[attr]=value;
      if(now!==value)el.setAttribute(attr,value);
    }
  }
  function update(root=document.body){
    if(!root)return;
    const doc=root.ownerDocument||document;
    const walker=doc.createTreeWalker(root,NodeFilter.SHOW_ELEMENT|NodeFilter.SHOW_TEXT,{acceptNode(node){
      if(node.nodeType===1&&ignored(node))return NodeFilter.FILTER_REJECT;
      return NodeFilter.FILTER_ACCEPT;
    }});
    if(root.nodeType===1){translateAttrs(root);for(const el of root.querySelectorAll('#minerLog,#walletReceiveAddress,#peerLog'))translateAttrs(el);}
    let node;
    while((node=walker.nextNode())){
      if(node.nodeType===3)translateNode(node);
      else if(node.nodeType===1)translateAttrs(node);
    }
  }
  function schedule(){if(queued)return;queued=true;queueMicrotask(()=>{queued=false;update()})}
  function setLanguage(next,persist=false){
    if(!['es','en'].includes(next))return;
    language=next;store(LANGUAGE_KEY,next);document.documentElement.lang=next;
    const select=document.getElementById('languageSelect');if(select&&select.value!==next)select.value=next;
    schedule();document.dispatchEvent(new CustomEvent('cashminer:locale-changed',{detail:{language:next,numberFormat,persist,kind:'language'}}));
  }
  function setNumberFormat(next,persist=false){
    if(!['auto','es','en'].includes(next))return;
    numberFormat=next;store(FORMAT_KEY,next);document.dispatchEvent(new CustomEvent('cashminer:locale-changed',{detail:{language,numberFormat,persist,kind:'numberFormat'}}));
  }
  function init(){
    document.documentElement.lang=language;
    const select=document.getElementById('languageSelect');
    if(select){select.value=language;select.addEventListener('change',()=>setLanguage(select.value,true))}
    observer=new MutationObserver(schedule);
    observer.observe(document.body,{subtree:true,childList:true,characterData:true,attributes:true,attributeFilter:ATTRS});
    update();
  }
  window.CMI18n={t,init,setLanguage,setNumberFormat,getLanguage:()=>language,getNumberFormat:()=>numberFormat,
    getLocale,formatNumber,formatSats,formatBch,normalizeInput,apply:update,
    hydrate(lang,fmt){setLanguage(lang==='en'?'en':'es');setNumberFormat(['auto','es','en'].includes(fmt)?fmt:'auto')}};
})();
