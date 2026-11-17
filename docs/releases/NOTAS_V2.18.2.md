# CashMiner v2.18.2 — Importación WIF, ojito y menú general

- Importación de claves individuales en hexadecimal o WIF, separada de las
  frases BIP39 y semillas BIP32 HD. Placeholder neutral «Billetera importada».
- WIF valida caracteres Base58, longitud, checksum, prefijo de red, compresión
  y rango secp256k1. Su compresión no puede cambiarse por la API. La dirección
  se muestra y confirma antes de importar; la vista previa no consulta saldos.
- Mainnet tiene un prefijo WIF distinto. Las redes de prueba comparten prefijo:
  el usuario debe seleccionar la cadena correcta.
- La clave se guarda en el almacén cifrado existente como clave individual;
  su respaldo sigue siendo hexadecimal equivalente. No hay cambio de esquema.
- Ayudas ⓘ para BIP39, BIP32, hexadecimal y WIF, con clic, teclado y toque.

- Botón de ojo para mostrar/ocultar la clave individual, tanto hexadecimal como
  WIF. Por defecto está oculta. La acción conserva el valor y la vista previa de
  dirección; cambiar de formato o cerrar el diálogo vuelve a ocultarla.
- El control general «Manage/Administrar» se sustituye por un botón ☰. Abre las
  mismas opciones generales. Se conserva el engranaje de cada billetera.
- Etiquetas accesibles, teclado y traducciones español/inglés para ambos botones.
- La indicación cuando no hay billeteras remite al menú ☰.

Incluye los cambios del candidato local 2.18.1, no publicado por separado. Se
comparten en Windows y Android. Datos y estructura de billeteras sin cambios.

Windows se prepara con la receta fijada. Android actualiza payload Python/UI y
manifiesto de 2.18.1, conserva el certificado y los componentes Java/nativos;
versionName 2.18.2, versionCode 2180200. APK pendiente de prueba en teléfono.
El propietario confirmó la importación WIF al probar Windows. Pasaron 642
pruebas sin fallos ni errores, con 9 omitidas; también pasaron 35 pruebas UI/idioma
y 10 de billetera con el Python distribuido. Arranque/cierre y hashes de Windows
verificados con datos aislados; interfaz revisada en escritorio y a 390px.
