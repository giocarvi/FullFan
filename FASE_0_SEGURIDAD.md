# Fase 0 — Seguridad y preparación

Esta fase prepara la plataforma para evolucionar de Full Fan a Fénix Digital TV sin tocar todavía la lógica histórica de clientes y pagos.

## Cambios incluidos

- Se agregó `.gitignore` para excluir bases de datos, Excel, backups y archivos `.env`.
- `SECRET_KEY` ahora puede venir de variable de entorno.
- Las contraseñas internas nuevas se guardan con hash usando Werkzeug.
- Las contraseñas legacy en texto plano siguen funcionando temporalmente.
- Al iniciar sesión con una contraseña legacy válida, el sistema la actualiza automáticamente a hash.
- Al cambiar contraseña desde el panel, se guarda siempre como hash.

## Antes de desplegar en producción

1. Avisar al equipo de atención que cierre sesión.
2. Confirmar que nadie registre pagos ni edite clientes.
3. Crear backup de la base de datos PostgreSQL de Railway.
4. Exportar clientes desde el panel actual.
5. Exportar pagos/reportes disponibles.
6. Configurar `SECRET_KEY` en Railway.
7. Desplegar.
8. Probar login con un usuario admin.
9. Probar cambio de contraseña.
10. Validar conteos antes/después.

## Variables de entorno necesarias

```text
SECRET_KEY
DATABASE_URL
```

Necesarias solo si se crea una base vacía y se quieren sembrar usuarios iniciales:

```text
DEFAULT_ADMIN_PASSWORD
DEFAULT_ATENCION_PASSWORD
DEFAULT_JACKYE_PASSWORD
DEFAULT_INGRID_PASSWORD
DEFAULT_TURCIOS_PASSWORD
```

## Validación después del despliegue

Ejecutar o revisar:

- Total de clientes.
- Total de pagos.
- Clientes activos.
- Clientes vencidos.
- Últimos pagos.
- Login admin.
- Login atención.
- Cambio de contraseña.

## Rollback

Si algo falla:

1. Revertir el despliegue en Railway al commit anterior.
2. Restaurar backup solo si hubo daño de datos.
3. No restaurar base si el problema fue únicamente login/configuración.

El cambio de contraseñas a hash es compatible hacia adelante. Una contraseña legacy solo se convierte a hash después de un login exitoso.

Nota: el código ya no crea usuarios nuevos con contraseñas por defecto si las variables `DEFAULT_*_PASSWORD` no existen. En producción actual no debería afectar porque los usuarios ya están creados.
