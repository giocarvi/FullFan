# Checklist Railway — Fase 0

## Preparación

- [ ] Equipo fuera del panel.
- [ ] Sin pagos nuevos durante la ventana.
- [ ] Backup PostgreSQL descargado o snapshot confirmado.
- [ ] Export de clientes descargado.
- [ ] Export de pagos/reportes descargado.

## Variables Railway

- [ ] `DATABASE_URL` existe.
- [ ] `SECRET_KEY` configurada con valor largo y aleatorio.

## Despliegue

- [ ] Subir cambios.
- [ ] Confirmar build correcto.
- [ ] Confirmar app inicia.
- [ ] Entrar con usuario admin.
- [ ] Entrar con usuario atención.
- [ ] Cambiar contraseña de prueba.

## Validación de datos

- [ ] Total clientes coincide.
- [ ] Total pagos coincide.
- [ ] Clientes activos coincide.
- [ ] Clientes vencidos coincide.
- [ ] Últimos pagos visibles.
- [ ] Dashboard carga.
- [ ] Búsqueda de clientes funciona.
- [ ] Detalle de cliente funciona.

## Reapertura

- [ ] Avisar al equipo que puede entrar.
- [ ] Pedir a cada usuario que cambie su contraseña.
- [ ] Monitorear errores durante 30 minutos.

