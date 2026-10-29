# API, permisos y seguridad

## Endpoints principales

Prefijo `/agenda/`.

| Método y ruta | Descripción |
|---|---|
| `GET /slots/` | Horarios desde hoy en adelante |
| `GET /slots_por_fecha/?fecha=AAAA-MM-DD&dentista_id=1&servicio_id=2` | Horarios de un día, opcionalmente de un dentista. Cada horario indica `bloqueado` (lo cubre la duración de una cita anterior) y `cabe` (el servicio pedido entra desde ese horario) |
| `POST /dentistas/{id}/generar_slots/` | Genera bloques de 30 minutos entre `desde` y `hasta` (el último termina a la hora final; entre 08:00 y 18:00) durante `dias` días seguidos desde `fecha`. Responde `created` (nuevos) y `existing` (ya existían) |
| `POST /reservas/` | Crea una reserva en un horario existente (`slot`, o `dentista`, `fecha` y `hora_inicio`), más `paciente`; rechaza horarios que ya pasaron y no crea horarios nuevos |
| `GET /api/pacientes/buscar/?rut=` | Devuelve solo al paciente con ese RUT (200), 404 si no existe o 400 si el RUT no es válido |
| `POST /auth/login/` | Inicia sesión (`username` o RUT, `password`) y devuelve un token con el rol (`recepcion`, `dentista` o `paciente`) |
| `POST /auth/activar-cuenta/` | Un paciente crea su cuenta con su RUT, el correo registrado en la clínica y una contraseña |
| `POST /auth/logout/`, `GET /auth/me/` | Cierra la sesión / devuelve el usuario actual (requieren token) |
| `POST /auth/cambiar-clave/` | Cambia la contraseña del usuario con sesión (`actual`, `nueva`) y devuelve un token nuevo |
| `POST /api/dentistas/{id}/cuenta/`, `POST /api/pacientes/{id}/cuenta/` | Recepción crea la cuenta de acceso o restablece su contraseña; devuelve el usuario y una contraseña temporal |
| `GET /semana/?desde=AAAA-MM-DD&dentista=1` | Horarios de 7 días con el detalle de sus reservas (personal) |
| `PATCH /api/reservas/{id}/` | Cambia estado, observaciones, servicio o reprograma la reserva (personal) |
| `POST /api/reservas/{id}/archivos/`, `GET/DELETE /archivos/{id}/` | Sube, descarga o elimina exámenes adjuntos |
| `PUT /api/reservas/{id}/atencion/` | El dentista registra diagnóstico, procedimiento e indicaciones |
| `GET /api/pacientes/{id}/historial/` | Historial clínico del paciente (personal) |
| `GET /mi/historial/` | Citas próximas e historial del paciente que inició sesión |
| `/api/regiones/`, `/api/dentistas/`, `/api/servicios/`, `/api/pacientes/`, `/api/reservas/` | CRUD de cada recurso (`?region=` para dentistas; `?dentista=` y `?fecha=` para reservas) |

### Listados

Los listados de pacientes y de reservas vienen paginados (`count`, `next`, `previous`, `results`; 25 por página, con `?page=` y `?page_size=` hasta 100). `GET /api/pacientes/?q=` busca en el servidor por nombre, apellido, correo o RUT, con o sin puntos y guion, y todas las palabras deben coincidir.

### Acceso y permisos

Las operaciones del público son: consultar dentistas, servicios y horarios (con la cantidad de reservas de cada horario, sin datos de pacientes), buscar un paciente por RUT, registrarse como paciente y reservar una hora, opcionalmente adjuntando exámenes. Todo lo demás exige un token en la cabecera `Authorization: Token <token>` y depende del rol:

| Rol | Cómo se define | Qué puede hacer |
|---|---|---|
| Recepción | Usuario con `is_staff` | Ver y modificar todo: pacientes, reservas, agenda de cualquier dentista y catálogo. Lee las atenciones clínicas, pero no las escribe |
| Dentista | Usuario enlazado al campo `usuario` de un dentista | Ver solo sus pacientes, sus reservas y su agenda; registrar la atención clínica de sus reservas |
| Paciente | Usuario enlazado al campo `usuario` de un paciente | Ver solo su propio historial, con el profesional que lo atendió |

Medidas de seguridad: las sesiones vencen a las 12 horas (`TOKEN_TTL_HORAS`); el público no ve el teléfono ni el correo completos de un paciente al buscarlo por RUT (solo recepción y dentistas); el ingreso, la búsqueda por RUT, el registro de pacientes y las reservas públicas tienen límite de solicitudes por IP; el CORS solo admite los orígenes configurados; con `DEBUG=False` se exigen `DJANGO_SECRET_KEY` y `ALLOWED_HOSTS`, y se activan HTTPS obligatorio, HSTS y cookies seguras.

Las observaciones internas de una reserva solo las ven recepción y el dentista; el paciente ve el motivo, el diagnóstico, el procedimiento y las indicaciones. Los exámenes se guardan fuera de las rutas públicas y solo se descargan con sesión, por quien tiene acceso a esa reserva. Se aceptan PDF, JPG y PNG de hasta 5 MB, máximo 5 por reserva, y se comprueba que el contenido corresponda a la extensión. El inicio de sesión se limita a 20 intentos por minuto y la búsqueda por RUT a 60 por minuto por dirección IP.

Crea una cuenta de recepción con `python manage.py createsuperuser`. Las cuentas de dentistas y pacientes las crea recepción desde la aplicación (páginas Equipo y Pacientes, botón Crear cuenta): el sistema genera el usuario (`dr.<apellido>` para dentistas, el RUT para pacientes) y una contraseña temporal que se muestra una sola vez. La contraseña temporal es de un solo uso: hasta que la persona la cambie desde Mi cuenta, la API responde 403 a todo salvo cambiar la contraseña y cerrar sesión, y el login informa `debe_cambiar_clave`. Al registrar una atención, la reserva queda siempre como «Atendida», aunque antes estuviera marcada como «No asistió». `seed_data --demo` crea además el usuario `recepcion`, un usuario `dr.<apellido>` por dentista (por ejemplo `dr.rojas`) y cuentas para tres pacientes (usuario = su RUT), todos con la contraseña `recepcion123` o la de la variable `DEMO_STAFF_PASSWORD`; es solo para demostración. También carga atenciones pasadas para probar el historial clínico.

## Sobrecupos

Un sobrecupo es una cita extra en un horario que ya está completo. Se maneja con un límite por día, no por horario:

- **Valor por defecto:** `max_overbook_day` de cada dentista (0 a 10). Lo cambia recepción en Equipo o el propio dentista desde su agenda.
- **Valor de una fecha:** se puede fijar otro límite para un día concreto (`SobrecupoDia`), por ejemplo más sobrecupos un viernes o ninguno antes de un feriado. Reemplaza al valor por defecto solo ese día y se puede quitar para volver a él.
- **Por horario:** un horario completo admite como máximo 1 sobrecupo.
- **Quién los agenda:** solo recepción o el propio dentista, indicándolo de forma explícita (`sobrecupo: true` en `POST /reservas/`). El público y los pacientes nunca agendan sobrecupos: un horario completo les aparece como completo.
- **Reglas:** se rechaza si el horario aún tiene espacio, si ya tiene su sobrecupo, si el dentista no admite sobrecupos ese día o si se alcanzó el límite del día. No se puede bajar el límite de una fecha por debajo de los sobrecupos ya agendados, ni cambiar fechas pasadas.
- **Duración:** un sobrecupo no bloquea los horarios siguientes.

| Método y ruta | Descripción |
|---|---|
| `GET /sobrecupos/?dentista=1&desde=AAAA-MM-DD` | Resumen de 7 días: valor por defecto y, por fecha, sobrecupos `permitidos`, `usados` y si el límite es `personalizado`. Un dentista solo ve el suyo |
| `PUT /sobrecupos/` con `dentista`, `fecha` y `cupos` | Fija el límite de una fecha; `cupos: null` lo quita. Sin `fecha` cambia el valor por defecto |
| `GET /slots_por_fecha/` | Cada horario indica `sobrecupo_disponible`: está completo, no tiene sobrecupo y queda cupo ese día |

## Duración de los servicios

Cada servicio tiene una duración (15 a 240 minutos, en múltiplos de 15) que recepción puede editar en `/api/servicios/`. Los horarios son bloques de 30 minutos y una reserva ocupa tantos bloques seguidos como necesite su servicio, redondeando hacia arriba: 30 minutos ocupa 1 bloque, 45 o 60 ocupan 2 y 90 ocupa 3. Los bloques siguientes quedan bloqueados para otras reservas.

Al reservar, mover una reserva o cambiarle el servicio, el sistema rechaza (400) un horario que ya está cubierto por una cita anterior y un servicio que no cabe porque falta un horario seguido, está reservado o ya pasó el cierre. Una reserva sin servicio ocupa un solo bloque y los sobrecupos no bloquean horarios.

## Nota de seguridad

La autenticación usa tokens con expiración (`TOKEN_TTL_HORAS`, 12 por defecto) y los permisos se definen por rol (recepción, dentista, paciente) en cada vista. CORS solo admite los orígenes de `CORS_ALLOWED_ORIGINS`. Con `DEBUG` desactivado `DJANGO_SECRET_KEY` y `ALLOWED_HOSTS` son obligatorias, y se activan la redirección a HTTPS, las cookies seguras y HSTS.

Las cuentas de `seed_data --demo` (`recepcion`, `dr.<apellido>` y tres pacientes) comparten una contraseña conocida y pública: son solo para demostración y nunca deben existir en un sistema con datos reales.
