# gunicorn_config.py
# Configuración de Gunicorn para Events Calendar AKS
# Optimizado para manejar requests largos de Airtable

import multiprocessing
import os

# =====================
# TIMEOUTS - CRÍTICO
# =====================
# Timeout principal aumentado para requests largos de Airtable
timeout = 180  # 3 minutos (era 30s por defecto)

# Timeout graceful para shutdown limpio
graceful_timeout = 120

# =====================
# WORKERS
# =====================
# En Render free tier (512MB RAM), usar 1 worker es más seguro
workers = 1
worker_class = 'sync'

# Reiniciar workers después de X requests (evita memory leaks)
max_requests = 100
max_requests_jitter = 20

# =====================
# BINDING
# =====================
port = os.getenv('PORT', '10000')
bind = f"0.0.0.0:{port}"

# =====================
# LOGGING
# =====================
loglevel = 'info'
accesslog = '-'  # stdout
errorlog = '-'   # stderr
capture_output = True

# =====================
# PERFORMANCE
# =====================
# Keep alive para conexiones persistentes
keepalive = 5

# Preload app (más eficiente en memoria)
preload_app = False  # False en free tier para evitar problemas

# =====================
# DEBUGGING
# =====================
# Log cuando hay timeouts para debugging
def worker_abort(worker):
    worker.log.error(f"Worker timeout - probablemente Airtable request demasiado largo")
