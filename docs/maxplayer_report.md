# Revisión privada de Max Player frente a Fénix

Solo administrador, tanto en la vista como en `/api/admin/maxplayer-comparacion`. Es un reporte de revisión sin acciones para eliminar, desactivar, renovar o desconectar cuentas de Max Player. No modifica clientes, pagos, servicios ni tareas de Fénix.

## Fuentes

- API existente mediante `MAXPLAYER_API_TOKEN` y `MAXPLAYER_DOMAIN_ID` del servidor; solo usa GET Users. Nunca expone el token al navegador. Los errores de la integración se sustituyen por un mensaje que no contiene el cuerpo original del proveedor.
- El reporte distingue autenticación, acceso denegado, bloqueo de protección del proveedor, ruta, parámetros, dominio, límite de consultas, fallo temporal, red y tiempo de espera. Incluye únicamente categoría y código HTTP si existe; no devuelve cuerpos de respuesta, direcciones con credenciales ni secretos. Un error genérico o un 403 no se trata por sí solo como prueba de token inválido. La clasificación no sustituye una consulta autenticada real. Se recortan espacios exteriores del token y dominio al leer las variables del servidor.
- CSV UTF-8 reciente exportado de Customers, cargado por administrador (máximo 10 MB). Se analiza en memoria, no se guarda como archivo ni se importa a las tablas. La fecha de exportación es declarada por el administrador y se muestra en el reporte; no se interpreta como una verificación independiente de actualidad.
- Se recorren páginas si la API informa un total y se aborta si repite cuentas, faltan páginas o cambia el total. Si no informa un total, se comparan explícitamente solo las cuentas recibidas sin afirmar cobertura completa. Lo mismo se indica para el CSV. Nunca se concluye que un cliente falte en Max Player por no aparecer en una fuente de cobertura incierta.

## Coincidencias y reserva de casos

Se consideran exactamente los usuarios de cuenta/listas de Max Player y los usuarios Fénix/de servicio, ignorando únicamente mayúsculas y espacios exteriores. No se usan coincidencias aproximadas por nombre. Una coincidencia activa en Fénix reserva la cuenta aunque otra coincidencia esté vencida.

Los candidatos para revisión son cuentas sin coincidencia en Fénix o con coincidencia archivada/vencida más allá del margen indicado (7 días por defecto). No se marcan como candidatos los duplicados, coincidencias ambiguas, casos sin fecha, activaciones pendientes, pagos válidos registrados en los últimos 7 días, cuentas conectadas si la fuente lo confirma, ni cuentas que la fuente ya informa inactivas en Max Player.

«Nunca conectó» no es criterio suficiente de limpieza. Falta de estado/conexión en la fuente se muestra como «No confirmado», no como activo/desconectado. Los registros de pago anulados se excluyen de las fechas de último pago, sin eliminarse del historial. Una importación o un registro reciente que parezca pago puede requerir revisión humana y queda reservado conservadoramente.

El reporte permite filtros, buscador, paginación, CSV sin contraseñas y enlace al perfil de Max Player. Los candidatos no son una autorización de borrado: cualquier futura limpieza requiere una revisión actualizada y una decisión del administrador, considerando pagos, coincidencias y conexiones.

## Pruebas

Pruebas de normalización, secretos, CSV, paginación, cobertura desconocida, usuarios vigentes, margen, pagos recientes, tareas, conexión, duplicados y permisos. La consulta conserva todos los hashes históricos de la muestra. La integración en Postgres desechable también valida la consulta y la configuración cifrada sin cambiar un pago histórico. Los recorridos de navegador prueban API/CSV con respuestas ficticias y la ausencia del reporte para atención.
