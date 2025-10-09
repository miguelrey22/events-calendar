"""
Calendario Motorsport Enterprise - Alkamel Management
Optimizado para Railway.app deployment

Versión: 1.0 Railway Production
Autor: Claude AI para Alkamel Management
Fecha: 28/01/2025
"""

import os
import json
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import requests
import msal
import threading
import schedule
import time
from flask import Flask, render_template_string, request, jsonify
import logging
from typing import Dict, List, Optional
import sqlite3
from io import BytesIO
import warnings

warnings.filterwarnings('ignore')

# Configuración de logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class MotorsportCalendarEnterprise:
    """Sistema empresarial de calendario motorsport"""
    
    def __init__(self, config: Dict):
        self.config = config
        self.airtable_token = config.get('airtable_token')
        self.airtable_base_id = config.get('airtable_base_id', 'app4p2TY96NofXW4u')
        
        # Microsoft Graph
        self.tenant_id = config.get('tenant_id')
        self.client_id = config.get('client_id')
        self.client_secret = config.get('client_secret')
        self.sharepoint_site_url = config.get('sharepoint_site_url')
        
        # Configuración
        self.auto_update_interval = config.get('auto_update_interval', 15)
        self.max_retries = 3
        self.timeout_seconds = 30
        
        # Cache
        self.cache = {}
        self.cache_expiry = {}
        
        # Headers Airtable
        self.airtable_headers = {
            'Authorization': f'Bearer {self.airtable_token}',
            'Content-Type': 'application/json'
        }
        
        # MSAL
        self.msal_app = self._init_msal()
        self.graph_token = None
        
        # Colores por SET
        self.color_mapping = {
            'SET 1': '#FF6B6B',      # FIA WEC
            'SET 2': '#4ECDC4',      # CIRCUITCAT
            'SET 3': '#45B7D1',      # FERRARI
            'MICROSET': '#96CEB4',   # Verde claro
            'SET RW': '#FFEAA7',     # F4-E3
            'EVENTS 3': '#DDA0DD',   # Ferrari NA
            'EVENTS 4': '#98D8C8',   # Ferrari UK
            'EVENTS 5': '#F7DC6F',   # Amarillo claro
            'EVENTS 6': '#BB8FCE',   # Púrpura claro
            'SCER': '#F8C471',       # Naranja claro
            'CERVH': '#85C1E9',      # Azul claro
            'SET6': '#F1C40F',       # E1 Series
            'SET 5': '#27AE60',      # ELMS
            'default': '#BDC3C7'
        }
        
        # Mapeo campeonatos a SETs
        self.championship_to_set = {
            'WEC': 'SET 1', 'FIA': 'SET 1',
            'CIRCUITCAT': 'SET 2', 'KATEYAMA': 'SET 2',
            'FERRARI': 'SET 3', 'MCLAREN': 'SET 3',
            'ELMS': 'SET 5',
            'F4': 'SET RW', 'E3': 'SET RW', 'GSERIES': 'SET RW',
            'E1': 'SET6',
            'SCER': 'SCER',
            'CERVH': 'CERVH'
        }
        
        logger.info("✅ Sistema inicializado correctamente")
    
    def _init_msal(self):
        """Inicializar MSAL"""
        try:
            if not all([self.tenant_id, self.client_id, self.client_secret]):
                logger.warning("⚠️ Credenciales de Microsoft Graph incompletas")
                return None
            
            return msal.ConfidentialClientApplication(
                client_id=self.client_id,
                client_credential=self.client_secret,
                authority=f"https://login.microsoftonline.com/{self.tenant_id}"
            )
        except Exception as e:
            logger.error(f"❌ Error inicializando MSAL: {str(e)}")
            return None
    
    def get_graph_token(self) -> Optional[str]:
        """Obtener token Microsoft Graph"""
        if not self.msal_app:
            return None
        
        try:
            result = self.msal_app.acquire_token_for_client(
                scopes=["https://graph.microsoft.com/.default"]
            )
            
            if "access_token" in result:
                self.graph_token = result["access_token"]
                return self.graph_token
            else:
                logger.error(f"❌ Error token: {result.get('error_description')}")
                return None
        except Exception as e:
            logger.error(f"❌ Excepción obteniendo token: {str(e)}")
            return None
    
    def get_airtable_data(self, table_name: str) -> List[Dict]:
        """Obtener datos de Airtable con cache"""
        cache_key = f"airtable_{table_name}"
        
        # Verificar cache
        if cache_key in self.cache:
            if datetime.now() < self.cache_expiry.get(cache_key, datetime.min):
                logger.info(f"📦 Usando cache para {table_name}")
                return self.cache[cache_key]
        
        # Mapeo de tablas
        table_ids = {
            'EVENTS': 'tblVb1BuNKkUoS96b',
            'EVENTS RESERVATIONS': 'tbllmzrlZvphVWaP7',
            'Employee directory': 'tblzwiTaABBdqaJ3G',
            'GUARDIAS': 'tblZtKR9x67vxayAF'
        }
        
        table_id = table_ids.get(table_name, table_name)
        url = f"https://api.airtable.com/v0/{self.airtable_base_id}/{table_id}"
        
        all_records = []
        
        try:
            params = {'pageSize': 100}
            
            while True:
                response = requests.get(
                    url, 
                    headers=self.airtable_headers, 
                    params=params,
                    timeout=self.timeout_seconds
                )
                
                if response.status_code == 200:
                    data = response.json()
                    all_records.extend(data.get('records', []))
                    
                    if 'offset' in data:
                        params['offset'] = data['offset']
                    else:
                        break
                else:
                    logger.error(f"❌ Error Airtable {table_name}: {response.status_code}")
                    break
            
            if all_records:
                # Guardar en cache por 5 minutos
                self.cache[cache_key] = all_records
                self.cache_expiry[cache_key] = datetime.now() + timedelta(minutes=5)
                logger.info(f"📊 Obtenidos {len(all_records)} registros de {table_name}")
                
            return all_records
            
        except Exception as e:
            logger.error(f"❌ Excepción obteniendo datos de {table_name}: {str(e)}")
            return []
    
    def process_motorsport_data(self) -> Dict:
        """Procesar datos completos de motorsport"""
        logger.info("🏁 Procesando datos de motorsport...")
        
        # Obtener datos
        events_data = self.get_airtable_data('EVENTS')
        reservations_data = self.get_airtable_data('EVENTS RESERVATIONS')
        
        if not events_data:
            logger.error("❌ No se encontraron eventos")
            return {}
        
        # Rango de fechas (próximos 12 meses)
        start_date = datetime.now().date()
        end_date = start_date + timedelta(days=365)
        
        processed_events = []
        unassigned_events = []
        stats = {
            'total_events': 0,
            'confirmed_events': 0,
            'cancelled_events': 0,
            'unassigned_events': 0,
            'total_reservations': 0,
            'remote_assignments': 0,
            'events_by_set': {},
            'events_by_coordinator': {},
            'critical_dates': []
        }
        
        # Procesar eventos
        for event_record in events_data:
            fields = event_record.get('fields', {})
            
            # Verificar fechas
            if 'From' not in fields or 'To' not in fields:
                continue
            
            try:
                event_start = datetime.strptime(fields['From'], '%Y-%m-%d').date()
                event_end = datetime.strptime(fields['To'], '%Y-%m-%d').date()
            except:
                continue
            
            # Filtrar rango
            if event_start > end_date or event_end < start_date:
                continue
            
            # Determinar SET
            championship = fields.get('CAMPEONATO-CIRCUITO-ENTIDAD (from CHAMPIONSHIP)', [''])[0] if fields.get('CAMPEONATO-CIRCUITO-ENTIDAD (from CHAMPIONSHIP)') else ''
            set_name = self._determine_set(championship)
            
            # Estados
            status = fields.get('STATUS', '')
            confirmed = fields.get('CONFIRMED', False)
            coordinator = fields.get('Name (from Event Coordinator)', [''])[0] if fields.get('Name (from Event Coordinator)') else 'Sin coordinador'
            
            # Buscar reservaciones
            event_reservations = []
            for res_record in reservations_data:
                res_fields = res_record.get('fields', {})
                if res_fields.get('EVENT', [''])[0] == event_record['id']:
                    if 'FROM' in res_fields and 'TO' in res_fields:
                        try:
                            res_start = datetime.strptime(res_fields['FROM'], '%Y-%m-%d').date()
                            res_end = datetime.strptime(res_fields['TO'], '%Y-%m-%d').date()
                            
                            employee_name = res_fields.get('Name (from Employee directory)', ['Sin asignar'])[0] if res_fields.get('Name (from Employee directory)') else 'Sin asignar'
                            is_remote = res_fields.get('REMOTE', False)
                            
                            event_reservations.append({
                                'employee': employee_name,
                                'from_date': res_start,
                                'to_date': res_end,
                                'remote': is_remote,
                                'days': (res_end - res_start).days + 1
                            })
                            
                            if is_remote:
                                stats['remote_assignments'] += 1
                        except:
                            continue
            
            # Crear evento
            event_entry = {
                'event_id': event_record['id'],
                'event_name': fields.get('EVENT NAME', 'Sin nombre'),
                'full_event': fields.get('EVENT', ''),
                'city': fields.get('EVENT CITY', ''),
                'championship': championship,
                'set_name': set_name,
                'color': self.color_mapping.get(set_name, self.color_mapping['default']),
                'coordinator': coordinator,
                'status': status,
                'confirmed': confirmed,
                'from_date': event_start,
                'to_date': event_end,
                'duration_days': (event_end - event_start).days + 1,
                'reservations': event_reservations,
                'employees_count': len(event_reservations),
                'is_critical': (event_start - start_date).days <= 30,
                'needs_attention': len(event_reservations) == 0 and confirmed
            }
            
            processed_events.append(event_entry)
            
            # Actualizar estadísticas
            stats['total_events'] += 1
            stats['total_reservations'] += len(event_reservations)
            
            if confirmed:
                stats['confirmed_events'] += 1
            
            if status == 'CANCELLED':
                stats['cancelled_events'] += 1
            
            if len(event_reservations) == 0 and confirmed:
                stats['unassigned_events'] += 1
                unassigned_events.append(event_entry)
            
            # Por SET
            stats['events_by_set'][set_name] = stats['events_by_set'].get(set_name, 0) + 1
            
            # Por coordinador
            stats['events_by_coordinator'][coordinator] = stats['events_by_coordinator'].get(coordinator, 0) + 1
            
            # Fechas críticas (próximos 7 días sin asignar)
            if (event_start - start_date).days <= 7 and len(event_reservations) == 0 and confirmed:
                stats['critical_dates'].append(event_entry)
        
        # Ordenar
        processed_events.sort(key=lambda x: x['from_date'])
        
        result = {
            'events': processed_events,
            'unassigned_events': unassigned_events,
            'stats': stats,
            'last_updated': datetime.now().isoformat(),
            'date_range': {
                'start': start_date.isoformat(),
                'end': end_date.isoformat()
            }
        }
        
        logger.info(f"✅ Procesados {stats['total_events']} eventos, {stats['unassigned_events']} sin asignar")
        return result
    
    def _determine_set(self, championship: str) -> str:
        """Determinar SET por campeonato"""
        if not championship:
            return 'default'
        
        championship_upper = championship.upper()
        
        for key, value in self.championship_to_set.items():
            if key in championship_upper:
                return value
        
        return 'default'
    
    def create_sharepoint_excel(self, processed_data: Dict) -> bool:
        """Crear Excel en SharePoint"""
        token = self.get_graph_token()
        if not token:
            logger.error("❌ No se pudo obtener token de Microsoft Graph")
            return False
        
        headers = {
            'Authorization': f'Bearer {token}',
            'Content-Type': 'application/json'
        }
        
        try:
            logger.info("📊 Creando Excel en SharePoint...")
            
            # Obtener IDs
            site_id = self._get_site_id(headers)
            if not site_id:
                return False
            
            drive_id = self._get_drive_id(site_id, headers)
            if not drive_id:
                return False
            
            # Crear Excel
            success = self._create_excel_file(drive_id, processed_data, headers)
            
            if success:
                logger.info("✅ Excel creado en SharePoint exitosamente")
                return True
            else:
                logger.error("❌ Error creando Excel")
                return False
                
        except Exception as e:
            logger.error(f"❌ Excepción creando Excel: {str(e)}")
            return False
    
    def _get_site_id(self, headers: Dict) -> Optional[str]:
        """Obtener site ID"""
        try:
            site_url_parts = self.sharepoint_site_url.replace('https://', '').split('/')
            hostname = site_url_parts[0]
            site_path = '/' + '/'.join(site_url_parts[1:]) if len(site_url_parts) > 1 else ''
            
            url = f"https://graph.microsoft.com/v1.0/sites/{hostname}:{site_path}"
            response = requests.get(url, headers=headers, timeout=self.timeout_seconds)
            
            if response.status_code == 200:
                return response.json().get('id')
            else:
                logger.error(f"❌ Error obteniendo site ID: {response.text}")
                return None
        except Exception as e:
            logger.error(f"❌ Excepción obteniendo site ID: {str(e)}")
            return None
    
    def _get_drive_id(self, site_id: str, headers: Dict) -> Optional[str]:
        """Obtener drive ID"""
        try:
            url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/drive"
            response = requests.get(url, headers=headers, timeout=self.timeout_seconds)
            
            if response.status_code == 200:
                return response.json().get('id')
            else:
                logger.error(f"❌ Error obteniendo drive ID: {response.text}")
                return None
        except Exception as e:
            logger.error(f"❌ Excepción obteniendo drive ID: {str(e)}")
            return None
    
    def _create_excel_file(self, drive_id: str, processed_data: Dict, headers: Dict) -> bool:
        """Crear archivo Excel con todas las pestañas"""
        try:
            
            filename = "Calendario_Motorsport_Alkamel.xlsx"
            
            buffer = BytesIO()
            
            with pd.ExcelWriter(buffer, engine='openpyxl') as writer:
                # 1. Calendario principal
                calendar_df = self._create_calendar_sheet(processed_data['events'])
                calendar_df.to_excel(writer, sheet_name='Calendario', index=False)
                
                # 2. Sin asignar
                if processed_data['unassigned_events']:
                    unassigned_df = self._create_unassigned_sheet(processed_data['unassigned_events'])
                    unassigned_df.to_excel(writer, sheet_name='Sin Asignar', index=False)
                
                # 3. Resumen ejecutivo
                summary_df = self._create_summary_sheet(processed_data['stats'])
                summary_df.to_excel(writer, sheet_name='Resumen Ejecutivo', index=False)
                
                # 4. Críticos
                if processed_data['stats']['critical_dates']:
                    critical_df = self._create_critical_sheet(processed_data['stats']['critical_dates'])
                    critical_df.to_excel(writer, sheet_name='Criticos', index=False)
                
                # 5. Coordinadores
                coordinators_df = self._create_coordinators_sheet(processed_data['events'])
                coordinators_df.to_excel(writer, sheet_name='Coordinadores', index=False)
                
                # 6. SETs
                sets_df = self._create_sets_sheet(processed_data['events'])
                sets_df.to_excel(writer, sheet_name='SETs', index=False)
            
            buffer.seek(0)
            file_content = buffer.read()
            
            # Subir a SharePoint
            url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{filename}:/content"
            
            upload_headers = {
                'Authorization': headers['Authorization'],
                'Content-Type': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
            }
            
            response = requests.put(url, headers=upload_headers, data=file_content, timeout=60)
            
            if response.status_code in [200, 201]:
                file_info = response.json()
                sharepoint_url = file_info.get('webUrl', 'URL no disponible')
                logger.info(f"✅ Excel creado: {sharepoint_url}")
                return True
            else:
                logger.error(f"❌ Error subiendo Excel: {response.text}")
                return False
                
        except Exception as e:
            logger.error(f"❌ Excepción creando Excel: {str(e)}")
            return False
    
    def _create_calendar_sheet(self, events: List[Dict]) -> pd.DataFrame:
        """Crear hoja de calendario principal"""
        rows = []
        
        for event in events:
            if event['reservations']:
                for reservation in event['reservations']:
                    rows.append({
                        'Evento': event['event_name'],
                        'Ciudad': event['city'],
                        'SET': event['set_name'],
                        'Coordinador': event['coordinator'],
                        'Fecha Inicio': event['from_date'].strftime('%d/%m/%Y'),
                        'Fecha Fin': event['to_date'].strftime('%d/%m/%Y'),
                        'Empleado': reservation['employee'],
                        'Empleado Desde': reservation['from_date'].strftime('%d/%m/%Y'),
                        'Empleado Hasta': reservation['to_date'].strftime('%d/%m/%Y'),
                        'Remoto': 'Si' if reservation['remote'] else 'No',
                        'Actualizado': datetime.now().strftime('%d/%m/%Y %H:%M')
                    })
            else:
                rows.append({
                    'Evento': event['event_name'],
                    'Ciudad': event['city'],
                    'SET': event['set_name'],
                    'Coordinador': event['coordinator'],
                    'Fecha Inicio': event['from_date'].strftime('%d/%m/%Y'),
                    'Fecha Fin': event['to_date'].strftime('%d/%m/%Y'),
                    'Empleado': 'SIN ASIGNAR',
                    'Empleado Desde': 'N/A',
                    'Empleado Hasta': 'N/A',
                    'Remoto': 'N/A',
                    'Actualizado': datetime.now().strftime('%d/%m/%Y %H:%M')
                })
        
        return pd.DataFrame(rows)
    
    def _create_unassigned_sheet(self, unassigned_events: List[Dict]) -> pd.DataFrame:
        """Crear hoja de eventos sin asignar"""
        rows = []
        
        for event in unassigned_events:
            days_until = (event['from_date'] - datetime.now().date()).days
            urgency = 'INMEDIATO' if days_until <= 3 else 'URGENTE' if days_until <= 7 else 'PENDIENTE'
            
            rows.append({
                'Urgencia': urgency,
                'Dias Restantes': days_until,
                'Evento': event['event_name'],
                'Ciudad': event['city'],
                'SET': event['set_name'],
                'Coordinador': event['coordinator'],
                'Fecha Inicio': event['from_date'].strftime('%d/%m/%Y'),
                'Accion': 'Asignar empleado/guardia'
            })
        
        df = pd.DataFrame(rows)
        if not df.empty:
            urgency_order = {'INMEDIATO': 0, 'URGENTE': 1, 'PENDIENTE': 2}
            df['urgency_sort'] = df['Urgencia'].map(urgency_order)
            df = df.sort_values('urgency_sort').drop('urgency_sort', axis=1)
        
        return df
    
    def _create_summary_sheet(self, stats: Dict) -> pd.DataFrame:
        """Crear hoja de resumen"""
        rows = [
            {'Metrica': 'Total eventos', 'Valor': stats['total_events']},
            {'Metrica': 'Eventos confirmados', 'Valor': stats['confirmed_events']},
            {'Metrica': 'Sin asignar', 'Valor': stats['unassigned_events']},
            {'Metrica': 'Total asignaciones', 'Valor': stats['total_reservations']},
            {'Metrica': 'Trabajo remoto', 'Valor': stats['remote_assignments']},
        ]
        
        return pd.DataFrame(rows)
    
    def _create_critical_sheet(self, critical_events: List[Dict]) -> pd.DataFrame:
        """Crear hoja de eventos críticos"""
        rows = []
        
        for event in critical_events:
            days_left = (event['from_date'] - datetime.now().date()).days
            
            rows.append({
                'Nivel': 'INMEDIATO' if days_left <= 2 else 'URGENTE',
                'Dias': days_left,
                'Evento': event['event_name'],
                'Ciudad': event['city'],
                'SET': event['set_name'],
                'Coordinador': event['coordinator'],
                'Fecha': event['from_date'].strftime('%d/%m/%Y')
            })
        
        return pd.DataFrame(rows)
    
    def _create_coordinators_sheet(self, events: List[Dict]) -> pd.DataFrame:
        """Crear hoja de coordinadores"""
        coordinator_stats = {}
        
        for event in events:
            coord = event['coordinator']
            if coord not in coordinator_stats:
                coordinator_stats[coord] = {
                    'total': 0,
                    'confirmados': 0,
                    'sin_asignar': 0,
                    'empleados': 0
                }
            
            coordinator_stats[coord]['total'] += 1
            if event['confirmed']:
                coordinator_stats[coord]['confirmados'] += 1
            if event['employees_count'] == 0 and event['confirmed']:
                coordinator_stats[coord]['sin_asignar'] += 1
            coordinator_stats[coord]['empleados'] += event['employees_count']
        
        rows = []
        for coord, stats in coordinator_stats.items():
            eficiencia = round((stats['confirmados'] - stats['sin_asignar']) / max(stats['confirmados'], 1) * 100, 1)
            
            rows.append({
                'Coordinador': coord,
                'Total Eventos': stats['total'],
                'Confirmados': stats['confirmados'],
                'Sin Asignar': stats['sin_asignar'],
                'Total Empleados': stats['empleados'],
                'Eficiencia %': eficiencia
            })
        
        return pd.DataFrame(rows)
    
    def _create_sets_sheet(self, events: List[Dict]) -> pd.DataFrame:
        """Crear hoja de SETs"""
        sets_stats = {}
        
        for event in events:
            set_name = event['set_name']
            if set_name not in sets_stats:
                sets_stats[set_name] = {
                    'eventos': 0,
                    'confirmados': 0,
                    'sin_asignar': 0,
                    'empleados': 0
                }
            
            sets_stats[set_name]['eventos'] += 1
            if event['confirmed']:
                sets_stats[set_name]['confirmados'] += 1
            if event['employees_count'] == 0 and event['confirmed']:
                sets_stats[set_name]['sin_asignar'] += 1
            sets_stats[set_name]['empleados'] += event['employees_count']
        
        rows = []
        for set_name, stats in sets_stats.items():
            cobertura = round((stats['confirmados'] - stats['sin_asignar']) / max(stats['confirmados'], 1) * 100, 1)
            
            rows.append({
                'SET': set_name,
                'Total Eventos': stats['eventos'],
                'Confirmados': stats['confirmados'],
                'Sin Personal': stats['sin_asignar'],
                'Total Empleados': stats['empleados'],
                'Cobertura %': cobertura
            })
        
        return pd.DataFrame(rows)
    
    def run_full_update(self) -> bool:
        """Ejecutar actualización completa"""
        try:
            logger.info("🚀 Iniciando actualización completa...")
            
            processed_data = self.process_motorsport_data()
            
            if not processed_data:
                logger.warning("⚠️ No hay datos para procesar")
                return False
            
            success = self.create_sharepoint_excel(processed_data)
            
            if success:
                stats = processed_data['stats']
                logger.info(f"✅ Actualización completada - {stats['total_events']} eventos, {stats['unassigned_events']} sin asignar")
                return True
            else:
                logger.error("❌ Error en actualización")
                return False
                
        except Exception as e:
            logger.error(f"❌ Excepción en actualización: {str(e)}")
            return False


# Aplicación Flask
app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'motorsport-alkamel-secret-2025')

# Variables globales
calendar_instance = None
last_update_status = {'success': False, 'timestamp': None, 'message': ''}
update_stats = {'total_updates': 0, 'successful_updates': 0}

# Base de datos SQLite
def init_database():
    """Inicializar BD"""
    conn = sqlite3.connect('motorsport_logs.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS update_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            status TEXT,
            message TEXT,
            events_processed INTEGER,
            unassigned_events INTEGER
        )
    ''')
    
    conn.commit()
    conn.close()

def log_update(status: str, message: str, events_processed: int = 0, unassigned_events: int = 0):
    """Log de actualización"""
    conn = sqlite3.connect('motorsport_logs.db')
    cursor = conn.cursor()
    
    cursor.execute('''
        INSERT INTO update_logs (status, message, events_processed, unassigned_events)
        VALUES (?, ?, ?, ?)
    ''', (status, message, events_processed, unassigned_events))
    
    conn.commit()
    conn.close()

init_database()

# Template HTML Dashboard
DASHBOARD_HTML = """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Events Management AKS - Alkamel Management</title>
    <style>
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Segoe UI', sans-serif;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            min-height: 100vh; padding: 20px;
        }
        .container {
            max-width: 1200px; margin: 0 auto; background: white;
            border-radius: 15px; box-shadow: 0 20px 60px rgba(0,0,0,0.1);
        }
        .header {
            background: linear-gradient(45deg, #2c3e50, #34495e);
            color: white; padding: 30px; text-align: center; border-radius: 15px 15px 0 0;
        }
        .header h1 { font-size: 2.5em; margin-bottom: 10px; }
        .main-content { padding: 40px; }
        .status-grid {
            display: grid; grid-template-columns: repeat(auto-fit, minmax(250px, 1fr));
            gap: 20px; margin-bottom: 40px;
        }
        .status-card {
            background: #f8f9fa; border-radius: 10px; padding: 25px;
            border-left: 4px solid #3498db;
        }
        .status-card.success { border-left-color: #27ae60; }
        .status-card.warning { border-left-color: #f39c12; }
        .status-card h3 { color: #2c3e50; margin-bottom: 15px; }
        .status-value { font-size: 2em; font-weight: bold; color: #3498db; }
        .status-card.success .status-value { color: #27ae60; }
        .action-buttons {
            display: flex; flex-wrap: wrap; gap: 15px; justify-content: center; margin: 40px 0;
        }
        .btn {
            background: linear-gradient(45deg, #3498db, #2980b9);
            color: white; padding: 15px 30px; border: none; border-radius: 8px;
            cursor: pointer; font-size: 16px; text-decoration: none;
        }
        .btn-success { background: linear-gradient(45deg, #27ae60, #229954); }
        .btn-warning { background: linear-gradient(45deg, #f39c12, #e67e22); }
        .alert { padding: 15px; border-radius: 8px; margin: 20px 0; display: none; }
        .alert-success { background: #d4edda; color: #155724; }
        .alert-error { background: #f8d7da; color: #721c24; }
        .alert-warning { background: #fff3cd; color: #856404; }
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h1>🏁 Events Management</h1>
            <p>Alkamel Management - Sistema Enterprise</p>
        </div>
        
        <div class="main-content">
            <div class="status-grid">
                <div class="status-card {{ 'success' if configured else 'warning' }}">
                    <h3>Sistema</h3>
                    <div class="status-value">{{ '✅' if configured else '⚙️' }}</div>
                    <p>{{ 'Configurado' if configured else 'Sin configurar' }}</p>
                </div>
                
                <div class="status-card {{ 'success' if last_success else '' }}">
                    <h3>Última Actualización</h3>
                    <div class="status-value">{{ '✅' if last_success else '❌' }}</div>
                    <p>{{ last_timestamp or 'Nunca' }}</p>
                </div>
                
                <div class="status-card">
                    <h3>Estadísticas</h3>
                    <div class="status-value">{{ successful }}/{{ total }}</div>
                    <p>Actualizaciones exitosas</p>
                </div>
            </div>
            
            <div class="action-buttons">
                <a href="/config" class="btn">⚙️ Configurar</a>
                <button onclick="updateCalendar()" class="btn btn-success">🔄 Actualizar</button>
                <button onclick="checkStatus()" class="btn btn-warning">📊 Estado</button>
            </div>
            
            <div id="status-message" class="alert"></div>
            
            {% if not configured %}
            <div class="alert alert-warning" style="display:block;">
                ⚠️ <strong>Sistema no configurado.</strong> Haz clic en Configurar para empezar.
            </div>
            {% endif %}
        </div>
    </div>
    
    <script>
        function showMessage(msg, type) {
            const div = document.getElementById('status-message');
            div.className = 'alert alert-' + type;
            div.innerHTML = msg;
            div.style.display = 'block';
            if (type === 'success') setTimeout(() => div.style.display = 'none', 5000);
        }
        
        function updateCalendar() {
            showMessage('🔄 Actualizando...', 'warning');
            fetch('/update', {method: 'POST'})
                .then(r => r.json())
                .then(data => {
                    if (data.success) {
                        showMessage('✅ ' + data.message, 'success');
                        setTimeout(() => location.reload(), 2000);
                    } else {
                        showMessage('❌ ' + data.error, 'error');
                    }
                });
        }
        
        function checkStatus() {
            fetch('/status')
                .then(r => r.json())
                .then(data => {
                    let html = '<h3>📊 Estado</h3>';
                    if (data.configured) {
                        html += '<p>✅ Sistema operativo</p>';
                        html += '<p>Última actualización: ' + data.last_update + '</p>';
                        html += '<p>Actualizaciones: ' + data.successful_updates + '/' + data.total_updates + '</p>';
                    } else {
                        html += '<p>⚠️ No configurado</p>';
                    }
                    showMessage(html, 'success');
                });
        }
    </script>
</body>
</html>
"""

@app.route('/')
def dashboard():
    """Dashboard"""
    return render_template_string(DASHBOARD_HTML,
        configured=calendar_instance is not None,
        last_success=last_update_status.get('success', False),
        last_timestamp=last_update_status.get('timestamp', ''),
        successful=update_stats['successful_updates'],
        total=update_stats['total_updates']
    )

@app.route('/config', methods=['GET', 'POST'])
def config():
    """Configuración"""
    if request.method == 'POST':
        try:
            config_data = {
                'airtable_token': request.form.get('airtable_token'),
                'airtable_base_id': request.form.get('airtable_base_id', 'app4p2TY96NofXW4u'),
                'tenant_id': request.form.get('tenant_id'),
                'client_id': request.form.get('client_id'),
                'client_secret': request.form.get('client_secret'),
                'sharepoint_site_url': request.form.get('sharepoint_site_url'),
                'auto_update_interval': int(request.form.get('auto_update_interval', 15))
            }
            
            required = ['airtable_token', 'tenant_id', 'client_id', 'client_secret', 'sharepoint_site_url']
            missing = [f for f in required if not config_data.get(f)]
            
            if missing:
                return jsonify({'error': f'Faltan campos: {", ".join(missing)}'}), 400
            
            global calendar_instance
            calendar_instance = MotorsportCalendarEnterprise(config_data)
            
            # Probar
            test_token = calendar_instance.get_graph_token()
            if not test_token:
                return jsonify({'error': 'Error con Microsoft Graph'}), 400
            
            test_airtable = calendar_instance.get_airtable_data('EVENTS')
            if not test_airtable:
                return jsonify({'error': 'Error con Airtable'}), 400
            
            start_scheduler()
            log_update('CONFIG', f'Sistema configurado')
            
            return jsonify({'success': True, 'message': 'Sistema configurado correctamente'})
            
        except Exception as e:
            return jsonify({'error': str(e)}), 500
    
    # Formulario
    return """
<!DOCTYPE html>
<html lang="es">
<head>
    <meta charset="UTF-8">
    <title>Configuración</title>
    <style>
        body { font-family: sans-serif; background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); padding: 20px; }
        .container { max-width: 600px; margin: 0 auto; background: white; padding: 30px; border-radius: 15px; }
        h1 { color: #2c3e50; }
        .form-group { margin: 20px 0; }
        label { display: block; margin-bottom: 5px; font-weight: bold; }
        input { width: 100%; padding: 10px; border: 1px solid #ddd; border-radius: 5px; }
        .btn { background: #3498db; color: white; padding: 12px 24px; border: none; border-radius: 5px; cursor: pointer; width: 100%; }
        .alert { padding: 10px; border-radius: 5px; margin: 10px 0; display: none; }
        .alert-success { background: #d4edda; color: #155724; }
        .alert-error { background: #f8d7da; color: #721c24; }
    </style>
</head>
<body>
    <div class="container">
        <h1>⚙️ Configuración</h1>
        <form id="config-form">
            <h3>📊 Airtable</h3>
            <div class="form-group">
                <label>Token Airtable *</label>
                <input type="password" name="airtable_token" required>
            </div>
            
            <h3>☁️ Microsoft SharePoint</h3>
            <div class="form-group">
                <label>Tenant ID *</label>
                <input type="text" name="tenant_id" required>
            </div>
            <div class="form-group">
                <label>Client ID *</label>
                <input type="text" name="client_id" required>
            </div>
            <div class="form-group">
                <label>Client Secret *</label>
                <input type="password" name="client_secret" required>
            </div>
            <div class="form-group">
                <label>URL SharePoint *</label>
                <input type="url" name="sharepoint_site_url" required placeholder="https://tuempresa.sharepoint.com/sites/motorsport">
            </div>
            
            <button type="submit" class="btn">💾 Guardar</button>
        </form>
        
        <div id="message" class="alert"></div>
    </div>
    
    <script>
        document.getElementById('config-form').onsubmit = function(e) {
            e.preventDefault();
            const msg = document.getElementById('message');
            msg.className = 'alert alert-warning';
            msg.innerHTML = '🔄 Guardando...';
            msg.style.display = 'block';
            
            fetch('/config', {
                method: 'POST',
                body: new FormData(this)
            })
            .then(r => r.json())
            .then(data => {
                if (data.success) {
                    msg.className = 'alert alert-success';
                    msg.innerHTML = '✅ ' + data.message;
                    setTimeout(() => window.location.href = '/', 2000);
                } else {
                    msg.className = 'alert alert-error';
                    msg.innerHTML = '❌ ' + data.error;
                }
            });
        };
    </script>
</body>
</html>
    """

@app.route('/update', methods=['POST'])
def manual_update():
    """Actualización manual"""
    global calendar_instance, last_update_status, update_stats
    
    if not calendar_instance:
        return jsonify({'error': 'No configurado'}), 400
    
    try:
        success = calendar_instance.run_full_update()
        
        update_stats['total_updates'] += 1
        if success:
            update_stats['successful_updates'] += 1
            last_update_status = {
                'success': True,
                'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'message': 'OK'
            }
            
            processed_data = calendar_instance.process_motorsport_data()
            stats = processed_data.get('stats', {})
            
            log_update('SUCCESS', 'Manual OK', stats.get('total_events', 0), stats.get('unassigned_events', 0))
            
            return jsonify({
                'success': True,
                'message': f'{stats.get("total_events", 0)} eventos, {stats.get("unassigned_events", 0)} sin asignar'
            })
        else:
            last_update_status = {'success': False, 'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M')}
            log_update('ERROR', 'Error manual')
            return jsonify({'error': 'Error actualizando'}), 500
            
    except Exception as e:
        log_update('ERROR', str(e))
        return jsonify({'error': str(e)}), 500

@app.route('/status')
def status():
    """Estado"""
    return jsonify({
        'configured': calendar_instance is not None,
        'last_update': last_update_status.get('timestamp', 'Nunca'),
        'last_success': last_update_status.get('success', False),
        'auto_update_interval': calendar_instance.auto_update_interval if calendar_instance else 0,
        'total_updates': update_stats['total_updates'],
        'successful_updates': update_stats['successful_updates']
    })

# Scheduler
scheduler_running = False

def auto_update():
    """Auto-actualización"""
    global calendar_instance, last_update_status, update_stats
    
    if not calendar_instance:
        return
    
    try:
        success = calendar_instance.run_full_update()
        
        update_stats['total_updates'] += 1
        
        if success:
            update_stats['successful_updates'] += 1
            last_update_status = {
                'success': True,
                'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M'),
                'message': 'OK'
            }
            
            processed_data = calendar_instance.process_motorsport_data()
            stats = processed_data.get('stats', {})
            
            log_update('SUCCESS', 'Auto OK', stats.get('total_events', 0), stats.get('unassigned_events', 0))
            logger.info(f"✅ Auto-actualización OK - {stats.get('total_events', 0)} eventos")
        else:
            last_update_status = {'success': False, 'timestamp': datetime.now().strftime('%d/%m/%Y %H:%M')}
            log_update('ERROR', 'Error auto')
            
    except Exception as e:
        logger.error(f"❌ Error auto: {str(e)}")
        log_update('ERROR', str(e))

def start_scheduler():
    """Iniciar scheduler"""
    global scheduler_running, calendar_instance
    
    if scheduler_running or not calendar_instance:
        return
    
    schedule.clear()
    
    interval = calendar_instance.auto_update_interval
    schedule.every(interval).minutes.do(auto_update)
    
    def run_scheduler():
        global scheduler_running
        scheduler_running = True
        logger.info(f"⏰ Scheduler iniciado - cada {interval} min")
        
        while scheduler_running:
            schedule.run_pending()
            time.sleep(30)
    
    scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
    scheduler_thread.start()

if __name__ == "__main__":
    logger.info("🏁 Calendario Motorsport Enterprise")
    logger.info("🌐 Optimizado para Railway deployment")
    
    port = int(os.environ.get('PORT', 5000))
    
    app.run(
        host='0.0.0.0',
        port=port,
        debug=False,
        threaded=True
    )