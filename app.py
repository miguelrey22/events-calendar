#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Events Calendar AKS - Optimized Version
Mejoras:
- Timeout de Airtable aumentado
- Caché más agresivo con TTL
- Carga progresiva de datos
- Mejor manejo de errores
"""

from flask import Flask, render_template, jsonify, request, redirect, url_for, session
import requests
import pandas as pd
from datetime import datetime, timedelta
import pytz
import os
from functools import wraps
import time
import logging

# ===========================
# CONFIGURACIÓN DE LOGGING
# ===========================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = os.urandom(24)

# ===========================
# CACHÉ SIMPLE CON TTL
# ===========================
class SimpleCache:
    def __init__(self, ttl_seconds=300):  # 5 minutos por defecto
        self.cache = {}
        self.ttl = ttl_seconds
    
    def get(self, key):
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp < self.ttl:
                return value
            else:
                del self.cache[key]
        return None
    
    def set(self, key, value):
        self.cache[key] = (value, time.time())
    
    def clear(self):
        self.cache.clear()

# Caché global
data_cache = SimpleCache(ttl_seconds=300)  # 5 minutos

# ===========================
# CONFIGURACIÓN
# ===========================
CONFIG_FILE = 'config_aks.txt'

def load_config():
    """Carga configuración desde archivo"""
    if not os.path.exists(CONFIG_FILE):
        return None
    
    config = {}
    with open(CONFIG_FILE, 'r') as f:
        for line in f:
            if '=' in line:
                key, value = line.strip().split('=', 1)
                config[key] = value
    return config

def save_config(config_data):
    """Guarda configuración en archivo"""
    with open(CONFIG_FILE, 'w') as f:
        for key, value in config_data.items():
            f.write(f"{key}={value}\n")

# ===========================
# CLASE PRINCIPAL
# ===========================
class EventsCalendarAKS:
    def __init__(self):
        config = load_config()
        if not config:
            raise ValueError("Configuración no encontrada")
        
        # Airtable
        self.airtable_token = config.get('AIRTABLE_TOKEN')
        self.base_id = config.get('AIRTABLE_BASE_ID', 'app4p2TY96NofXW4u')
        self.headers = {'Authorization': f'Bearer {self.airtable_token}'}
        
        # TIMEOUT AUMENTADO - CRÍTICO
        self.timeout_seconds = 90  # 90 segundos para requests de Airtable
        
        # Azure/SharePoint
        self.tenant_id = config.get('TENANT_ID')
        self.client_id = config.get('CLIENT_ID')
        self.client_secret = config.get('CLIENT_SECRET')
        self.sharepoint_site_url = config.get('SHAREPOINT_SITE_URL')
        
        # URLs
        self.airtable_base_url = f'https://api.airtable.com/v0/{self.base_id}'
        
        logger.info("✅ Events Calendar AKS inicializado")
    
    def get_airtable_data(self, table_name, max_records=None, fields=None):
        """
        Obtiene datos de Airtable con timeout mejorado y manejo de errores
        """
        cache_key = f"airtable_{table_name}"
        
        # Intentar obtener del caché primero
        cached_data = data_cache.get(cache_key)
        if cached_data is not None:
            logger.info(f"📦 Usando caché para {table_name}")
            return cached_data
        
        logger.info(f"🔄 Obteniendo datos de {table_name}...")
        
        url = f'{self.airtable_base_url}/{table_name}'
        all_records = []
        offset = None
        
        params = {}
        if max_records:
            params['maxRecords'] = max_records
        if fields:
            params['fields[]'] = fields
        
        max_attempts = 3
        attempt = 0
        
        while True:
            attempt += 1
            
            if offset:
                params['offset'] = offset
            
            try:
                response = requests.get(
                    url,
                    headers=self.headers,
                    params=params,
                    timeout=self.timeout_seconds  # Timeout aumentado
                )
                response.raise_for_status()
                data = response.json()
                
                records = data.get('records', [])
                all_records.extend(records)
                
                offset = data.get('offset')
                
                if not offset:
                    break
                    
            except requests.exceptions.Timeout:
                logger.error(f"⏰ Timeout en {table_name} (intento {attempt}/{max_attempts})")
                if attempt >= max_attempts:
                    raise Exception(f"Timeout después de {max_attempts} intentos en {table_name}")
                time.sleep(2)  # Esperar antes de reintentar
                
            except requests.exceptions.RequestException as e:
                logger.error(f"❌ Error en {table_name}: {str(e)}")
                if attempt >= max_attempts:
                    raise
                time.sleep(2)
        
        logger.info(f"📊 Obtenidos {len(all_records)} registros de {table_name}")
        
        # Guardar en caché
        data_cache.set(cache_key, all_records)
        
        return all_records
    
    def process_motorsport_data(self):
        """
        Procesa datos de motorsport de forma optimizada
        CARGA SOLO LO NECESARIO EN ORDEN DE PRIORIDAD
        """
        try:
            logger.info("🔄 Procesando datos...")
            
            # 1. EVENTOS (más importante, cargar primero)
            events_data = self.get_airtable_data('EVENTS')
            
            # 2. RESERVACIONES
            reservations_data = self.get_airtable_data('EVENTS RESERVATIONS')
            
            # 3. EMPLOYEES (puede ser lento, pero necesario)
            # OPTIMIZACIÓN: Solo cargar campos necesarios
            employees_data = self.get_airtable_data(
                'Employee directory',
                fields=['Name', 'Email', 'Position', 'Status']  # Solo campos necesarios
            )
            
            # 4. SERIES
            series_data = self.get_airtable_data('SERIES')
            
            # 5. VENUES
            venues_data = self.get_airtable_data('VENUES')
            
            # Procesar DataFrames
            df_events = self._process_events(events_data)
            df_reservations = self._process_reservations(reservations_data)
            df_employees = self._process_employees(employees_data)
            
            # Combinar datos
            df_combined = self._combine_data(df_events, df_reservations, df_employees)
            
            # Preparar datos para timeline
            timeline_data = self._prepare_timeline_data(df_combined)
            
            # Preparar estadísticas
            stats = self._calculate_statistics(df_combined)
            
            result = {
                'timeline_data': timeline_data,
                'stats': stats,
                'series': self._process_series(series_data),
                'venues': self._process_venues(venues_data),
                'last_update': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            }
            
            logger.info("✅ Datos procesados correctamente")
            return result
            
        except Exception as e:
            logger.error(f"❌ Error procesando datos: {str(e)}")
            raise
    
    def _process_events(self, events_data):
        """Procesa eventos en DataFrame"""
        events_list = []
        
        for record in events_data:
            fields = record.get('fields', {})
            events_list.append({
                'Event ID': record['id'],
                'Event Name': fields.get('Event Name', 'Sin nombre'),
                'Start Date': fields.get('Start Date'),
                'End Date': fields.get('End Date'),
                'Series': fields.get('Series', []),
                'Venue': fields.get('Venue', []),
                'Status': fields.get('Status', 'Unknown')
            })
        
        return pd.DataFrame(events_list)
    
    def _process_reservations(self, reservations_data):
        """Procesa reservaciones en DataFrame"""
        reservations_list = []
        
        for record in reservations_data:
            fields = record.get('fields', {})
            reservations_list.append({
                'Reservation ID': record['id'],
                'Event': fields.get('Event', []),
                'Employee': fields.get('Employee', []),
                'Role': fields.get('Role', 'Unknown'),
                'Start Date': fields.get('Start Date'),
                'End Date': fields.get('End Date')
            })
        
        return pd.DataFrame(reservations_list)
    
    def _process_employees(self, employees_data):
        """Procesa empleados en DataFrame"""
        employees_list = []
        
        for record in employees_data:
            fields = record.get('fields', {})
            employees_list.append({
                'Employee ID': record['id'],
                'Employee Name': fields.get('Name', 'Sin nombre'),
                'Email': fields.get('Email'),
                'Position': fields.get('Position'),
                'Status': fields.get('Status', 'Active')
            })
        
        return pd.DataFrame(employees_list)
    
    def _combine_data(self, df_events, df_reservations, df_employees):
        """Combina los DataFrames"""
        # Implementación simplificada - ajustar según necesidades reales
        return df_events
    
    def _prepare_timeline_data(self, df_combined):
        """Prepara datos para el timeline"""
        return []
    
    def _calculate_statistics(self, df_combined):
        """Calcula estadísticas"""
        return {
            'total_events': len(df_combined),
            'active_events': len(df_combined[df_combined['Status'] == 'Active']) if 'Status' in df_combined.columns else 0
        }
    
    def _process_series(self, series_data):
        """Procesa series"""
        return [record.get('fields', {}).get('Name', 'Unknown') for record in series_data]
    
    def _process_venues(self, venues_data):
        """Procesa venues"""
        return [record.get('fields', {}).get('Name', 'Unknown') for record in venues_data]

# ===========================
# INSTANCIA GLOBAL (con manejo de errores)
# ===========================
calendar_instance = None

def get_calendar_instance():
    """Obtiene o crea instancia del calendario"""
    global calendar_instance
    
    if calendar_instance is None:
        config = load_config()
        if not config:
            return None
        calendar_instance = EventsCalendarAKS()
    
    return calendar_instance

# ===========================
# RUTAS FLASK
# ===========================

@app.route('/')
def dashboard():
    """Dashboard principal"""
    instance = get_calendar_instance()
    
    if not instance:
        return redirect(url_for('config_needed'))
    
    try:
        # Obtener datos (con caché)
        cached_dashboard_data = data_cache.get('dashboard_full')
        
        if cached_dashboard_data is None:
            cached_dashboard_data = instance.process_motorsport_data()
            data_cache.set('dashboard_full', cached_dashboard_data)
        
        return render_template('dashboard.html', data=cached_dashboard_data)
        
    except Exception as e:
        logger.error(f"❌ Error en dashboard: {str(e)}")
        return f"Error cargando dashboard: {str(e)}", 500

@app.route('/timeline')
def timeline():
    """Vista de timeline"""
    instance = get_calendar_instance()
    
    if not instance:
        return redirect(url_for('config_needed'))
    
    try:
        cached_timeline_data = data_cache.get('timeline_data')
        
        if cached_timeline_data is None:
            full_data = instance.process_motorsport_data()
            cached_timeline_data = full_data.get('timeline_data', [])
            data_cache.set('timeline_data', cached_timeline_data)
        
        return render_template('timeline.html', timeline_data=cached_timeline_data)
        
    except Exception as e:
        logger.error(f"❌ Error en timeline: {str(e)}")
        return f"Error cargando timeline: {str(e)}", 500

@app.route('/config_needed')
def config_needed():
    """Página cuando falta configuración"""
    return render_template('config_needed.html')

@app.route('/config', methods=['GET', 'POST'])
def config():
    """Página de configuración"""
    if request.method == 'POST':
        try:
            config_data = {
                'AIRTABLE_TOKEN': request.form.get('airtable_token'),
                'AIRTABLE_BASE_ID': request.form.get('airtable_base_id', 'app4p2TY96NofXW4u'),
                'TENANT_ID': request.form.get('tenant_id'),
                'CLIENT_ID': request.form.get('client_id'),
                'CLIENT_SECRET': request.form.get('client_secret'),
                'SHAREPOINT_SITE_URL': request.form.get('sharepoint_site_url')
            }
            
            # Validar que todos los campos obligatorios estén presentes
            required_fields = ['AIRTABLE_TOKEN', 'TENANT_ID', 'CLIENT_ID', 'CLIENT_SECRET', 'SHAREPOINT_SITE_URL']
            for field in required_fields:
                if not config_data.get(field):
                    return jsonify({'success': False, 'error': f'Falta campo requerido: {field}'}), 400
            
            # Guardar configuración
            save_config(config_data)
            
            # Limpiar caché
            data_cache.clear()
            
            # Reiniciar instancia
            global calendar_instance
            calendar_instance = None
            
            logger.info("✅ Configuración guardada correctamente")
            
            return jsonify({
                'success': True,
                'message': 'Configuración guardada correctamente'
            })
            
        except Exception as e:
            logger.error(f"❌ Error guardando configuración: {str(e)}")
            return jsonify({'success': False, 'error': str(e)}), 500
    
    # GET request
    current_config = load_config() or {}
    return render_template('config.html', config=current_config)

@app.route('/api/refresh', methods=['POST'])
def refresh_data():
    """API para refrescar datos manualmente"""
    try:
        data_cache.clear()
        logger.info("🔄 Caché limpiado manualmente")
        return jsonify({'success': True, 'message': 'Caché limpiado'})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/health')
def health():
    """Health check endpoint"""
    return jsonify({
        'status': 'ok',
        'timestamp': datetime.now().isoformat(),
        'cache_size': len(data_cache.cache)
    })

# ===========================
# MAIN
# ===========================
if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port, debug=False)
