# Usa una imagen oficial de Python
FROM python:3.9

# Establece el directorio de trabajo
WORKDIR /app

# Copia el archivo requirements.txt primero (para optimizar el cache de Docker)
COPY requirements.txt .

# Instala las dependencias principales
RUN pip install --upgrade pip
RUN pip install Django==4.2.25 djangorestframework==3.14.0 django-cors-headers==4.3.1

# Copia los archivos del proyecto al contenedor
COPY . /app

# Crear directorios para archivos estáticos y media
RUN mkdir -p /app/static /app/media

# Ejecutar migraciones
RUN python manage.py makemigrations || true
RUN python manage.py migrate || true
RUN python manage.py collectstatic --noinput || true

# Expone el puerto 8000
EXPOSE 8000

# Comando para iniciar el servidor
CMD ["python", "manage.py", "runserver", "0.0.0.0:8000"]