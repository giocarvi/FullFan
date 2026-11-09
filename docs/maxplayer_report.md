# Revisión privada de Max Player frente a Fénix

Solo administrador, tanto en la vista como en `/api/admin/maxplayer-comparacion`. Consultar el reporte no modifica cuentas. Incluye una acción separada de eliminación individual en Max Player, con comprobaciones actuales y confirmación explícita. No elimina ni modifica clientes, pagos, credenciales, servicios ni tareas de Fénix.

## Fuentes

- API mediante `MAXPLAYER_API_TOKEN` del servidor y cabecera `Api-Token`; el reporte solo usa GET Users. La lectura y el borrado individual documentado no requieren `MAXPLAYER_DOMAIN_ID` ni lo envían. Las operaciones antiguas de creación/restauración siguen requiriendo el dominio. Nunca expone el token al navegador. Los errores de la integración se sustituyen por un mensaje que no contiene el cuerpo original del proveedor.
- El reporte distingue autenticación, acceso denegado, bloqueo de protección del proveedor, ruta, parámetros, dominio, límite de consultas, fallo temporal, red y tiempo de espera. Incluye únicamente categoría y código HTTP si existe; no devuelve cuerpos de respuesta, direcciones con credenciales ni secretos. Un error genérico o un 403 no se trata por sí solo como prueba de token inválido. La clasificación no sustituye una consulta autenticada real. Se recortan espacios exteriores del token y dominio al leer las variables del servidor.
- CSV UTF-8 reciente exportado de Customers, cargado por administrador (máximo 10 MB). Se analiza en memoria, no se guarda como archivo ni se importa a las tablas. La fecha de exportación es declarada por el administrador y se muestra en el reporte; no se interpreta como una verificación independiente de actualidad.
- Formato confirmado por la documentación del proveedor compartida el 9/11/2026: `GET /users?limit=100`, después `GET /users?limit=100&after_id=<X-Next-Cursor>`, hasta recibir `X-Has-More: false`. No se envían los parámetros no documentados `page`, `per_page` ni `domain_id`. Se espacian consultas para no superar por esta operación el límite mostrado de 60 solicitudes/minuto, sin reintentos automáticos ante 429; otras integraciones comparten el límite.
- Se aborta si se repiten cuentas/cursores, falta un cursor indicado como necesario, las cabeceras son inválidas o se excede el plazo de la consulta. Si faltan las cabeceras de paginación, se comparan explícitamente solo las cuentas recibidas sin afirmar cobertura completa. Lo mismo se indica para el CSV. Nunca se concluye que un cliente falte en Max Player por no aparecer en una fuente de cobertura incierta. El ámbito de GET Users es el solicitante y sus agentes descendientes, según la documentación del proveedor; no un filtro local por dominio.

## Coincidencias y reserva de casos

Se consideran exactamente los usuarios de cuenta/listas de Max Player y los usuarios Fénix/de servicio, ignorando únicamente mayúsculas y espacios exteriores. También se respeta el ID de Max Player guardado en Fénix. No se usan coincidencias aproximadas por nombre. Una coincidencia vigente en Fénix reserva la cuenta aunque otra coincidencia esté vencida, o aunque la primera esté archivada.

Los candidatos para revisión son cuentas sin coincidencia en Fénix o con coincidencia vencida más allá del margen indicado (7 días por defecto). Los archivados también necesitan fecha de vencimiento conocida y respetar el margen. No se marcan como candidatos los duplicados, coincidencias ambiguas, casos sin fecha, activaciones pendientes, pagos válidos registrados en los últimos 7 días ni cuentas conectadas si la fuente lo confirma. Una cuenta inactiva en Max Player también puede revisarse para liberar un espacio, pero no deja de estar sujeta a las demás protecciones.

«Nunca conectó» no es criterio suficiente de limpieza. Falta de estado/conexión en la fuente se muestra como «No confirmado», no como activo/desconectado. Los registros de pago anulados se excluyen de las fechas de último pago, sin eliminarse del historial. Una importación o un registro reciente que parezca pago puede requerir revisión humana y queda reservado conservadoramente.

El reporte permite filtros, buscador, paginación, CSV sin contraseñas y enlace al perfil de Max Player. Los candidatos no son una autorización de borrado.

## Eliminación individual confirmada

La documentación compartida el 9/11/2026 confirma `DELETE https://api.maxplayer.tv/v3/api/public/users/[user_id]`, sin cuerpo y con `Api-Token`, para cuentas propias. Solo se permite esta dirección HTTPS oficial. No se ejecutan borrados masivos ni automáticos.

1. El administrador consulta la API y elige «Revisar eliminación». El servidor comprueba de nuevo su rol actual en la base, la sesión y la protección contra solicitudes cruzadas.
2. Se recorre toda la API y se vuelve a leer la página documentada que contiene el ID. Para un candidato, «Comprobar conexión y revisar» valida su identidad con `GET /customers/{id}` y sus dispositivos con `GET /customers/{id}/devices`, documentados en el OpenAPI 1.5.0 compartido el 9/11/2026. `GET /users/{id}` es una lista de clientes de un reseller, no la ficha de un cliente. Después de los dispositivos se vuelve a leer Fénix. Si falta cobertura completa, identidad, fecha, o confirmación de desconexión, se bloquea. Un CSV nunca habilita esta revisión. «Nunca conectó» no demuestra que esté desconectado ahora.
3. Si hay coincidencia en Fénix, se exigen al menos 7 días vencido, incluso en archivados; si el administrador elige más margen, también se respeta. Se reservan servicios vigentes, pagos recientes, tareas pendientes, duplicados y casos ambiguos. Los datos ocultos de identidad tampoco permiten borrar.
4. La confirmación identifica usuario e ID, advierte de la pérdida de acceso/configuración en Max Player y exige un motivo, escribir exactamente el usuario y marcar una casilla inicialmente vacía. Vence a los 180 segundos y está vinculada a administrador, cuenta, datos revisados y credencial del proveedor.
5. Al confirmar se repiten todas las lecturas y protecciones. Cualquier cambio invalida la revisión. Antes de enviar una única orden externa se guarda un recibo duradero; luego se exige un recorrido completo que confirme la ausencia del ID. Una respuesta exitosa por sí sola no basta.

Las comprobaciones son puntuales: no existe una transacción compartida entre Fénix y Max Player. Una conexión o pago puede cambiar después de la última comprobación. No se presenta esta protección como una garantía atómica entre sistemas.

### Presencia por dispositivos

El listado general `GET /users` documentado no incluye conexión actual. No se recorre cada cliente para completar ese dato: se consulta únicamente el candidato elegido, al preparar y al confirmar, dejando al menos 1,05 segundos entre lecturas de esta operación.

La respuesta de dispositivos debe tener `success: 1`, `presence_available: true`, `presence_generated_at_unix` entero y reciente (máximo 120 segundos de antigüedad y 15 de tolerancia futura), y registros identificables sin duplicados, todos con `online: false` booleano. Cualquier `online: true` bloquea; `null`, valores no booleanos, fallo de presencia, formato incompleto o fecha desactualizada no se convierten a desconexión. Un array vacío tampoco basta: la documentación advierte que puede haber registros asíncronos pendientes de persistir. No se añade una excepción de borrado para esos casos.

Solo se devuelve al navegador un resumen; identificadores de instalación, nombres de dispositivos y metadatos no se exponen. La confirmación incluye una huella de los dispositivos y su estado, pero no el instante del heartbeat, que naturalmente avanza en cada consulta. La fecha se valida de nuevo; cambios de dispositivos invalidan la confirmación. Se reconocen también los alias documentados en `lists[].iptv_info.username`, sin conservar ni devolver contraseñas o servidores de esas listas. No se realizan cambios de límites, dispositivos ni listas.

## Registro y resultados inciertos

`init_db` añade únicamente `maxplayer_cleanup_operations`, sin relación de borrado con clientes/pagos. Guarda ID, usuario, administrador, identificador de solicitud, motivo, estado y fecha. Los eventos se añaden a `audit_log`. El historial visible muestra las últimas 100 operaciones.

La reserva única por ID y solicitud evita un segundo envío por doble clic, reintento, varios procesos o reinicio. Los estados `checking`, `sending`, `verifying`, `uncertain` y `deleted` bloquean otro borrado. Un fallo de red o de registro después del posible envío exige revisión; no se reintenta automáticamente. «Verificar estado (sin borrar)» solo consulta y puede confirmar ausencia. Si la cuenta sigue presente, no vuelve a borrarla. Un rechazo explícito del proveedor antes de aceptar la orden permite una nueva preparación y confirmación humana, nunca reutilizar la solicitud anterior.

No se borran las credenciales históricas de Fénix ni se promete restaurar el perfil eliminado en Max Player. Esta funcionalidad requiere una decisión por cuenta, no interpreta la consulta de un reporte como autorización.

## Pruebas

Pruebas de normalización, secretos, CSV, paginación, cobertura desconocida, usuarios vigentes, margen, pagos recientes, tareas, conexión, duplicados y permisos. Los borrados externos se simulan siempre. Se prueban doble envío, confirmación vencida/alterada, cambio de cuenta/administrador/credencial, reconexión o pago nuevo, incertidumbre y verificación de ausencia. Las muestras SQLite y Postgres desechable conservan los clientes y pagos históricos; la copia local del respaldo real también se restaura y actualiza sin acceder a producción. Los recorridos de navegador prueban la confirmación en computadora/celular con respuestas ficticias y la ausencia del reporte para atención. La publicación no ejecuta ninguna eliminación real en Max Player.
