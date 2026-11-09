# Publicación del control de clientes

La actualización adapta administración a computadora y atención a celular. Incluye pagos con protección contra reintentos, ficha por pestañas, historial paginado, reportes y correcciones de vencimientos/dispositivos. Se retiran los accesos a Migrar y Quiniela del panel; sus datos existentes se conservan.

## Cambios de datos

`init_db` añade `payment_submissions` para reconocer operaciones repetidas. No copia, elimina ni reescribe pagos históricos. Las actualizaciones normales conservan los dispositivos existentes cuando no se indica un cambio. Al cancelar tareas se conserva la tarea, su orden y el pago anulado, incluido su comprobante.

Los planes familiares existentes pasan a tener 6 conexiones según la definición comercial de Fénix. Esto no cambia automáticamente los dispositivos de cada cliente: conserva los valores existentes y permite su actualización explícita. No se ejecuta ninguna sincronización masiva de XUI al publicar.

## Verificación antes de producción

1. Confirmar que el servicio Railway `web` del dominio de Fénix apunta a este repositorio y a la rama prevista.
2. Crear y comprobar un respaldo recuperable de Postgres. Coordinar una ventana sin registros nuevos para tomar la referencia y contrastar el historial.
3. En una sesión con `DATABASE_URL` de la base correcta, obtener la referencia:

   ```text
   python scripts/snapshot_payment_history.py --output history_snapshot_antes.json
   ```

   El manifiesto contiene hashes, no sustituye un respaldo restaurable. La herramienta abre Postgres en modo de solo lectura; exige una conexión explícita.
4. Validar las pruebas automatizadas y probar el cambio con una copia aislada de Postgres antes de actualizar el servicio público.
5. Publicar únicamente el código revisado. No subir bases locales, exportaciones, credenciales, respaldos, imágenes de pruebas o archivos de clientes al repositorio.
6. Comparar después de publicar:

   ```text
   python scripts/snapshot_payment_history.py --compare history_snapshot_antes.json
   ```

   La comparación muestra filas faltantes, modificadas y nuevas. Toda diferencia requiere revisión; no restaura ni modifica datos automáticamente. Si hay pagos legítimos nuevos durante la publicación, deben conservarse y conciliarse.
7. Revisar pagos/comprobantes, dashboard, búsqueda, plan familiar y perfiles de administrador y atención. La web mantiene su acceso con usuario y contraseña.

## Pruebas aisladas

```text
python -m unittest discover -s tests -v
python tests/test_control.py --preview
node tests/control_browser.cjs
```

La suite usa una base temporal y datos ficticios. La comprobación de Postgres solo permite un servidor local y la base desechable `fenix_ci`; GitHub Actions aprovisiona ese servidor. No utiliza secretos ni conexiones de producción. La prueba de navegador requiere Playwright con Chromium o `BROWSER_EXECUTABLE` configurado.

Las rutas `/demo/admin` y `/demo/atencion` existen exclusivamente en el servidor de pruebas local; no forman parte de `app.py` ni de la aplicación pública.

## Reversión

Si falla el código, se puede desplegar la versión anterior conservando la base y la tabla adicional. No restaurar automáticamente un respaldo antiguo: podría descartar pagos legítimos registrados después de tomarlo. Investigar primero y preservar esos registros.
