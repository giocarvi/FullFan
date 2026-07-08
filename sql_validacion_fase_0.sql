-- Validación antes y después de Fase 0
-- Ejecutar sobre PostgreSQL de producción con una conexión segura.

-- Conteos principales
SELECT COUNT(*) AS total_clientes FROM clientes;
SELECT COUNT(*) AS total_pagos FROM pagos;
SELECT COUNT(*) AS total_usuarios FROM usuarios;

-- Estado de clientes
SELECT COUNT(*) AS clientes_activos
FROM clientes
WHERE vencimiento >= CURRENT_DATE::text;

SELECT COUNT(*) AS clientes_vencidos
FROM clientes
WHERE vencimiento < CURRENT_DATE::text OR vencimiento IS NULL;

-- Últimos pagos, sin mostrar comprobantes
SELECT id, username, mes, monto, fecha_registro
FROM pagos
ORDER BY id DESC
LIMIT 10;

-- Revisar cuántos usuarios siguen con contraseña legacy en texto plano.
-- Después de que cada usuario inicie sesión, este número debería bajar.
SELECT COUNT(*) AS usuarios_password_legacy
FROM usuarios
WHERE password NOT LIKE 'scrypt:%'
  AND password NOT LIKE 'pbkdf2:%'
  AND password NOT LIKE 'argon2:%';

