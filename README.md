# dental-clinic-backend
=================================

Resumen
-------
Este repositorio contiene un backend Django mínimo para una clínica dental. Incluye una app `agenda` que gestiona pacientes, dentistas, servicios, slots de agenda y reservas con control de sobrecupo.

Estructura clave
----------------
- `backendClinica/` - configuración del proyecto Django
- `agenda/` - app principal con modelos, vistas, serializadores, admin y tests
- `api/` - app con ViewSets CRUD (existente)
- `db.sqlite3` - base de datos SQLite (por defecto)

Modelos principales (resumen)
-----------------------------
- Paciente: datos básicos del paciente.
- Dentista: nombre, especialidad, `max_overbook_day` (límite diario de sobrecupos).
- Servicio: nombre, duración (min), precio.
- SlotAgenda: dentista, servicio, fecha, hora, `capacidad`, `max_overbook` (sobrecupos permitidos por slot).
- Reserva: referencia a `SlotAgenda` y `Paciente`, `sobrecupo` booleano.

Puntos importantes de comportamiento
-----------------------------------
- Horarios permitidos: solo slots entre 08:00 y 16:00.
- Bloques de 30 minutos: la hora debe ser mm = 00 o 30.
- No se pueden crear dos slots para el mismo dentista a la misma fecha y hora (validación + unique_together).
- Reservas: creación transaccional con `select_for_update()` para contar reservas actuales.
  - Si slot.capacidad no está lleno → crear reserva normal (sobrecupo=False).
  - Si está lleno → se permite sobrecupo solo si:
    - slot.max_overbook > sobrecupos_actuales_slot
---------------------------------
1. Activar entorno virtual (si existe):
```powershell
# Si tu venv está en ./venv
# o ejecutar python desde venv como:
& "C:/Users/Pedro/Documents/Dental Clinic- Backend/venv/Scripts/python.exe" -m pip install -r requirements.txt
```

2. Instalar dependencias (si no están instaladas):

```powershell
& "C:/Users/Pedro/Documents/Dental Clinic- Backend/venv/Scripts/python.exe" -m pip install djangorestframework
```

3. Migraciones y servidor:
& "C:/Users/Pedro/Documents/Dental Clinic- Backend/venv/Scripts/python.exe" manage.py makemigrations
& "C:/Users/Pedro/Documents/Dental Clinic- Backend/venv/Scripts/python.exe" manage.py migrate
& "C:/Users/Pedro/Documents/Dental Clinic- Backend/venv/Scripts/python.exe" manage.py runserver
```

4. Crear superusuario para acceder al admin:

```powershell
& "C:/Users/Pedro/Documents/Dental Clinic- Backend/venv/Scripts/python.exe" manage.py createsuperuser
```

Endpoints clave (abrir en el navegador)
---------------------------------------
- Admin UI:
  - http://127.0.0.1:8000/admin/

- App `agenda` (JSON / browsable API):
  - GET  /agenda/slots/           — listar slots disponibles (fecha >= hoy)
  - POST /agenda/reservas/        — crear reserva
  - POST /agenda/dentistas/{id}/generar_slots/ — generar slots de 30min para un dentista (body: {"fecha":"YYYY-MM-DD","desde":"08:00","hasta":"16:00"})

- App `api` (ViewSets CRUD):
  - /api/pacientes/   (GET, POST)
  - /api/citas/       (GET, POST)
  - /api/dentistas/   (GET, POST)
-----------------------------------


Respuestas esperadas al crear reservas
-------------------------------------
- 201 Created: { "id": <id_reserva>, "sobrecupo": false }
- 201 Created con sobrecupo: { "id": <id_reserva>, "sobrecupo": true } (sólo si los límites lo permiten)
- 400 Bad Request: { "detail": "El slot está lleno y no se permiten sobrecupos adicionales." }

Probar reglas de validación de slots
------------------------------------
- Intentar crear un slot fuera del horario (07:30 o 17:00) → error de validación.
- Intentar crear un slot con minutos diferentes de 00 o 30 (p.ej. 10:15) → error de validación.
- Intentar crear dos slots iguales para el mismo dentista/fecha/hora → error de validación.

Tests
-----
- Ejecuta los tests de la app agenda:

```powershell
& "C:/Users/Pedro/Documents/Dental Clinic- Backend/venv/Scripts/python.exe" manage.py test agenda -v 2
```

Notas sobre sobrecupo (recomendación)
-------------------------------------
- Política por defecto del sistema: rechazar reservas públicas cuando el slot está lleno.
- Para excepciones, puedes permitir crear sobrecupo a través del admin (añadiendo `sobrecupo=True` en la reserva) o configurando `slot.max_overbook` y `dentista.max_overbook_day`.
- Si quieres automatizar overbooking, es mejor basarlo en métricas (tasa de no-shows) y tener límites por slot/dentista.

Archivos importantes para consultar
----------------------------------
- `agenda/models.py` — definiciones de modelos y validaciones
- `agenda/serializers.py` — lógica transaccional de creación de reservas
- `agenda/views.py` — vistas para listar slots, crear reservas y generar slots
- `agenda/urls.py` — rutas públicas de la app
- `agenda/tests.py` — tests de capacidad de reservas

