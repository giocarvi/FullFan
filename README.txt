╔══════════════════════════════════════════════════════╗
║           IPTV Panel - Control de Clientes           ║
╚══════════════════════════════════════════════════════╝

REQUISITOS
──────────
• Python 3.8 o superior
• Pip instalado

INSTALACIÓN EN EL SERVIDOR
───────────────────────────
1. Copia TODA esta carpeta a tu servidor

2. Coloca el archivo "IPTV Nuevo (2).xlsx" dentro
   de la carpeta iptv_app/ (al mismo nivel que app.py)

3. Ejecuta:
      chmod +x setup_and_run.sh
      ./setup_and_run.sh

   Esto instala dependencias, migra los datos del Excel
   a la base de datos, y arranca el servidor.

4. Accede desde cualquier dispositivo en la red:
      http://TU_IP_SERVIDOR:5000

USUARIOS POR DEFECTO
─────────────────────
  admin      → admin123      (acceso completo)
  atencion   → atencion123   (atención al cliente)

  ⚠️ CAMBIA LAS CONTRASEÑAS después de la primera vez.
  Para cambiarlas, edita la base de datos o agrega un
  endpoint en app.py

FUNCIONES
──────────
  📊 Dashboard  — Estadísticas: activos, vencidos,
                  ingresos del mes, próximos a vencer,
                  gráfico de últimos 6 meses

  👥 Clientes   — Buscar por nombre / usuario / teléfono
                  Filtrar: Todos / Activos / Por vencer / Vencidos
                  Ver detalle completo del cliente
                  Ver historial de pagos

  💳 Pago       — Registrar pago desde el detalle del cliente
                  Actualiza vencimiento automáticamente

ESTRUCTURA DE ARCHIVOS
───────────────────────
  app.py          → Servidor Flask (backend + API)
  migrate.py      → Migración del Excel a SQLite
  database.db     → Base de datos (se crea al migrar)
  templates/
    login.html    → Pantalla de login
    index.html    → App principal (dashboard + clientes)
  requirements.txt
  setup_and_run.sh

INICIAR EL SERVIDOR (sin migrar de nuevo)
──────────────────────────────────────────
  python app.py

COMO SERVICIO PERMANENTE (con systemd)
───────────────────────────────────────
  Crea /etc/systemd/system/iptv-panel.service:

  [Unit]
  Description=IPTV Panel
  After=network.target

  [Service]
  WorkingDirectory=/ruta/a/iptv_app
  ExecStart=/usr/bin/python3 app.py
  Restart=always

  [Install]
  WantedBy=multi-user.target

  Luego: systemctl enable iptv-panel && systemctl start iptv-panel
