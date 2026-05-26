# 🌱 Guía de Configuración del Sistema de Plantas

## ✅ Cambios Implementados

Se ha implementado un sistema completo de gestión de plantas con tickets, gráficos, exportación a Excel y notificaciones por WhatsApp.

### Nuevas Características:

1. **🏭 Gestión de Plantas**
   - 4 plantas disponibles (Planta 1, 2, 3, 4)
   - Control de acceso por usuario
   - Dashboard individual para cada planta

2. **📊 Gráficos y Estadísticas**
   - Gráficos de barras mostrando estado de tickets
   - Estadísticas en porcentajes
   - Tarjetas de resumen (completos, incompletos, en proceso)

3. **📥 Exportación a Excel**
   - Exportación de todos los tickets por planta
   - Codificación por colores:
     - 🟢 Verde: Tickets completados
     - 🟠 Naranja: En proceso
     - 🔴 Rojo: Incompletos
   - Información detallada incluida

4. **📱 Notificaciones por WhatsApp**
   - Alertas automáticas para tickets de EMERGENCIA
   - Enviadas a los responsables de la planta
   - Integración con Twilio

5. **📋 Reportes Detallados**
   - Reporte completo de todos los tickets
   - Tabla interactiva e imprimible
   - Estadísticas resumidas

## 🚀 Instrucciones de Configuración

### Paso 1: Instalar Dependencias

```bash
cd c:\Users\Nenas\Desktop\business-manager

# Activar entorno virtual
venv\Scripts\activate.bat

# Instalar nuevas dependencias
pip install -r requirements.txt
```

### Paso 2: Aplicar Migraciones de Base de Datos

```bash
# Aplicar migraciones de Alembic
alembic upgrade head
```

### Paso 3: Inicializar Plantas

```bash
# Crear las 4 plantas de prueba y asignarlas a usuarios
python init_plants.py
```

Output esperado:
```
🌱 Initializing plants...
✅ Created 4 plants
Assigning plants to X users:
  - admin: Acceso a 4 plantas
  - [otros usuarios]...
✅ Plant initialization completed!
✅ Done!
```

### Paso 4: Configurar WhatsApp (Opcional)

Para habilitar notificaciones por WhatsApp:

1. **Crear cuenta en Twilio**: https://www.twilio.com/console
2. **Habilitar WhatsApp API**
3. **Configurar variables de entorno**:

```batch
set WHATSAPP_ACCOUNT_SID=tu_account_sid_aqui
set WHATSAPP_AUTH_TOKEN=tu_auth_token_aqui
set WHATSAPP_PHONE=whatsapp:+14155552671
```

4. **Agregar números de teléfono a empleados**:
   - Ir a /employees
   - Editar cada empleado y agregar número (formato: +5491234567890)

### Paso 5: Ejecutar la Aplicación

```bash
# Establecer variables de entorno
set BACKUP_ENCRYPTION_KEY=D3fu6gCRALTvfznfSYFB6nL-yIQqa6rCUC7SXAoVgUE=
set SECRET_KEY=TuClaveSecretaMuyLargaYSegura123!
set DATABASE_URL=sqlite:///C:/Users/Nenas/Desktop/business-manager/business.db
set ADMIN_PASSWORD=TuPasswordAdminSegura123!
set ENFORCE_HTTPS=false

# Ejecutar servidor
python -m uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

## 📍 URLs Nuevas

| URL | Descripción |
|-----|-------------|
| `/plants` | Selecciona planta (página de inicio) |
| `/plant/{id}` | Dashboard de la planta |
| `/plant/{id}/ticket/new` | Crear nuevo ticket |
| `/plant/{id}/tickets/export` | Descargar tickets en Excel |
| `/plant/{id}/tickets/report` | Ver reporte detallado |

## 🎨 Flujo de Uso

1. **Después de login**:
   - El usuario ve la página de inicio con las 4 plantas
   - Selecciona una planta

2. **En el dashboard de planta**:
   - Ve gráfico de estado de tickets
   - Estadísticas (completos, incompletos, en proceso)
   - Última 5 tickets completados e incompletos
   - Botón para crear nuevo ticket
   - Botón para descargar Excel

3. **Al crear ticket con EMERGENCIA**:
   - Se envía notificación WhatsApp a responsables
   - Se crea notificación en el sistema
   - Se registra en audit log

4. **Exportación a Excel**:
   - Archivo con nombre: `tickets_[PlantName]_[Fecha].xlsx`
   - Colores por estado (verde/naranja/rojo)
   - Se descarga automáticamente

## 🔐 Control de Acceso

- Los usuarios solo ven las plantas a las que tienen acceso
- Verificación en cada endpoint
- Se registra en audit log cualquier acceso a plantas

## 📊 Estructura de Datos

### Nuevas Tablas:
- `plants`: Información de plantas
- `user_plant_access`: Asignación de usuarios a plantas

### Cambios en tablas existentes:
- `employees`: Se agregó `phone_number`
- `support_tickets`: Se agregó `plant_id`

## 🔧 Troubleshooting

### Error: "Plant not found"
- Asegúrate de haber ejecutado `python init_plants.py`
- Verifica que la migración se aplicó correctamente

### Error: "User has no access to plant"
- Verifica que el usuario esté asignado en la tabla `user_plant_access`
- Ejecuta `init_plants.py` nuevamente para reassignar accesos

### WhatsApp no funciona
- Verifica que las variables de entorno estén configuradas
- Comprueba que el número de teléfono tenga formato correcto: +PAIS+NUMERO
- Revisa la consola para mensajes de error

### Excel no se descarga
- Asegúrate de que la carpeta `reports/` existe
- Verifica permisos de escritura en la carpeta

## 📝 Próximas Mejoras (Opcional)

- [ ] Dashboard de admin para gestionar plantas
- [ ] Asignación selectiva de plantas a usuarios
- [ ] Más opciones de filtrado en reportes
- [ ] Gráficos adicionales (tiempo de resolución, etc.)
- [ ] Integración con Google Sheets
- [ ] Webhooks para integraciones externas

---

**Última actualización**: 15 de mayo, 2026
**Versión**: 2.0 - Sistema de Plantas 🌱
