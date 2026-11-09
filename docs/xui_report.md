# Reporte de Fénix vs XUI

Vista `Fénix vs XUI` disponible únicamente para administrador. Tanto la pantalla como el endpoint `/api/admin/xui-comparacion` restringen el acceso; atención, revendedores y visitantes no pueden consultar el reporte.

## Consulta y seguridad

- Solo permite iniciar sesión en el panel autorizado y leer todas las páginas de su tabla de líneas. No incluye llamadas para renovar, crear, borrar, editar o desconectar usuarios.
- Filtra por reseller configurado y vuelve a verificar owner exactamente `giocarvi` en cada línea. No permite seleccionar otros owners desde el navegador.
- El reporte no escribe clientes, servicios o pagos, ni crea tablas. Al recordar/olvidar acceso se modifica exclusivamente su clave reservada en `configuracion`. Para la comparación se consultan únicamente las columnas necesarias de clientes y servicios.
- Puede usar `XUI_USER` y `XUI_PASS` del entorno de Railway. Opcionalmente `XUI_BASE_URL` y `XUI_RESELLER_ID` (por defecto el panel xdplustv.online y reseller 3652). Nunca poner estos valores en GitHub.
- La pantalla permite «Recordar acceso en Fénix» (seleccionado por petición del administrador). Solo después de una consulta exitosa guarda usuario/contraseña cifrados y autenticados con Fernet en la clave reservada `integration_credentials.xui`. La clave de cifrado se deriva con separación de propósito de la `SECRET_KEY` obligatoria del servidor; no está en la base. El endpoint general de configuración nunca devuelve ni permite sobrescribir esta clave reservada, tampoco al administrador.
- Sin la opción de recordar no se guarda el acceso. El campo de contraseña siempre se vacía tras cada intento; no se usa almacenamiento del navegador ni se devuelven secretos en el reporte. El acceso guardado tiene prioridad sobre las variables de entorno y puede cambiarse/olvidarse exclusivamente como administrador.
- Conservar la `SECRET_KEY` del servicio para recuperar accesos cifrados después de restaurar un respaldo. Si se rota esta clave, introducir de nuevo el acceso XUI; no afecta al historial de clientes/pagos. Referencia del formato de cifrado: https://cryptography.io/en/latest/fernet/.
- El panel indicado utiliza HTTP. La pantalla advierte que ese tramo de la conexión no está cifrado. Una configuración HTTPS solo debe utilizarse si el panel ofrece HTTPS válido; no se desactiva la verificación TLS.
- Respuestas JSON marcadas `Cache-Control: no-store`. Errores de conexión no devuelven mensajes originales que pudieran contener secretos. Una consulta fallida oculta la fotografía anterior.
- La descarga CSV se genera con los datos filtrados del reporte, sin contraseñas, con protección contra fórmulas en celdas.

## Criterios

Se agrupa por el usuario del servicio guardado en Fénix; si falta, por el usuario de Fénix. Se ignoran mayúsculas y espacios exteriores, no se adivinan coincidencias por nombres o teléfonos. Duplicados en cualquiera de los dos sistemas se muestran juntos y no se comparan arbitrariamente uno a uno.

El vencimiento de referencia es `clientes.vencimiento`, no una fecha antigua de las credenciales del servicio. Fénix conserva su criterio de día completo en Guatemala; XUI aporta su estado activo, vencido, inactivo o bloqueado. Una fecha desconocida no equivale a servicio ilimitado y un dato de conexiones desconocido no se supone de tres.

Filtros: falta de tiempo en XUI, diferencias de fecha/dispositivos/estado, activo en XUI y vencido en Fénix, activo en Fénix pero no activo en XUI, presentes solo en uno, duplicados, activos/vencidos en ambos y datos incompletos. Los archivados se identifican y quedan ocultos por defecto en la tabla. Las tarjetas informan grupos, no sumas de personas únicas; un grupo puede tener varios hallazgos.

Se exige una lectura completa: páginas truncadas, identificadores repetidos o cambios en el total durante la consulta cancelan el reporte. Si XUI no devuelve ninguna línea de giocarvi, no se presenta toda la cartera como ausente por un posible problema de acceso. Cada consulta nueva vuelve a leer ambos sistemas, sin tareas programadas ni renovación automática.

## Pruebas

`tests/test_xui_report.py` cubre transporte paginado de solo lectura, aislamiento del owner, ocultación de secretos, fallos parciales, permisos, fechas, estados, dispositivos desconocidos, alias, duplicados, archivados y conservación de hashes de toda la muestra histórica. `tests/control_browser.cjs` verifica conexión temporal, filtrado, paginación, CSV y apertura de ficha usando exclusivamente respuestas ficticias de XUI.
