import os
import json
import re
from datetime import datetime, timedelta
import dateparser
from flask import Flask, request, jsonify

# Nota: Asegúrate de que pytz esté instalado en requirements.txt
# pip install pytz

# --- CONFIGURACIÓN DE NOTION ---
NOTION_TOKEN = os.environ.get("NOTION_TOKEN")
DATABASE_ID = os.environ.get("DATABASE_ID")

# --- CONFIGURACIÓN DE FECHA/HORA ---
TIMEZONE = 'America/Lima' 

app = Flask(__name__)

# Función para convertir fechas de Python a formato ISO 8601 (requerido por Notion)
def format_date_to_iso(dt_object):
    """Convierte un objeto datetime con zona horaria a formato ISO 8601."""
    if dt_object:
        # Si no tiene tzinfo, asumimos la zona horaria de Lima
        if dt_object.tzinfo is None or dt_object.tzinfo.utcoffset(dt_object) is None:
            import pytz
            tz = pytz.timezone(TIMEZONE)
            # Intentar localizar solo si no es aware, si es naive lo localiza.
            dt_object = tz.localize(dt_object)
        
        # Notion requiere el formato ISO 8601
        return dt_object.isoformat()
    return None

# Función principal para procesar el comando y construir la carga útil de Notion
def process_command(comando_completo):
    # --- 1. CONFIGURACIÓN DE VALORES POR DEFECTO ---
    
    # 🚨 Buscamos el separador estricto '#'
    if '#' in comando_completo:
        # Dividimos el comando en Título y Comando de Fecha/Regla
        tarea_titulo, comando_regla = comando_completo.split('#', 1)
        comando_regla = comando_regla.strip()
    else:
        # Si no hay separador, asumimos que todo es el título/comando
        tarea_titulo = comando_completo
        comando_regla = comando_completo
        
    prioridad = 'Normal' 
    estado = 'Sin empezar' 
    recordatorio_base = 'Manual'
    
    fecha_tarea_dt = None
    fecha_recordatorio_dt = None
    regla_timedelta = None
    
    # --- 2. DETECCIÓN DE REGLAS FIJAS (Prioridad y Recordatorio) ---
    
    # Detección de Prioridad (Usando la regla completa)
    if re.search(r'prioridad alta|urgente', comando_regla, re.IGNORECASE):
        prioridad = 'Alta'
    elif re.search(r'prioridad baja|luego', comando_regla, re.IGNORECASE):
        prioridad = 'Baja'
    
    # Detección de Reglas de Recordatorio Fijas
    if re.search(r'un d[ií]a antes', comando_regla, re.IGNORECASE):
        recordatorio_base = '1 día antes'
        regla_timedelta = timedelta(days=1)
    elif re.search(r'una hora antes', comando_regla, re.IGNORECASE):
        recordatorio_base = '1 hora antes'
        regla_timedelta = timedelta(hours=1)
    
    # --- 3. EXTRACCIÓN DE FECHAS ---
    
    settings = {
        'PREFER_DATES_FROM': 'future', 
        'RETURN_AS_TIMEZONE_AWARE': True,
        'TIMEZONE': TIMEZONE 
    }
    
    # Primero intentamos detección personalizada para expresiones españolas no soportadas
    import pytz
    from datetime import date
    
    tz = pytz.timezone(TIMEZONE)
    hoy = datetime.now(tz)
    fecha_encontrada = None
    
    # Mapeo de días de la semana
    dias_semana = {
        'lunes': 0, 'martes': 1, 'miércoles': 2, 'miercoles': 2,
        'jueves': 3, 'viernes': 4, 'sábado': 5, 'sabado': 5, 'domingo': 6
    }
    
    # Detectar "pasado mañana"
    if re.search(r'pasado\s+mañana', comando_regla, re.IGNORECASE):
        fecha_encontrada = hoy + timedelta(days=2)
        # Intentar extraer hora
        hora_match = re.search(r'(\d{1,2})\s*(am|pm|de la mañana|de la tarde|de la noche)?', comando_regla, re.IGNORECASE)
        if hora_match:
            hora = int(hora_match.group(1))
            periodo = hora_match.group(2) or ''
            if 'pm' in periodo.lower() or 'tarde' in periodo.lower() or 'noche' in periodo.lower():
                if hora < 12:
                    hora += 12
            fecha_encontrada = fecha_encontrada.replace(hour=hora, minute=0, second=0, microsecond=0)
    
    # Detectar "el [día de la semana]"
    elif match := re.search(r'(?:el\s+)?(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)', comando_regla, re.IGNORECASE):
        dia_nombre = match.group(1).lower().replace('á', 'a').replace('é', 'e')
        dia_objetivo = dias_semana.get(dia_nombre, 0)
        dias_adelante = (dia_objetivo - hoy.weekday()) % 7
        if dias_adelante == 0:
            dias_adelante = 7  # Si es hoy, ir al próximo
        fecha_encontrada = hoy + timedelta(days=dias_adelante)
        # Intentar extraer hora
        hora_match = re.search(r'(\d{1,2})\s*(am|pm|de la mañana|de la tarde|de la noche)?', comando_regla, re.IGNORECASE)
        if hora_match:
            hora = int(hora_match.group(1))
            periodo = hora_match.group(2) or ''
            if 'pm' in periodo.lower() or 'tarde' in periodo.lower() or 'noche' in periodo.lower():
                if hora < 12:
                    hora += 12
            fecha_encontrada = fecha_encontrada.replace(hour=hora, minute=0, second=0, microsecond=0)
    
    # Si no hubo detección personalizada, usar dateparser
    if not fecha_encontrada:
        fecha_encontrada = dateparser.parse(comando_regla, settings=settings)

    if fecha_encontrada:
        fecha_tarea_dt = fecha_encontrada

    # --- 4. CÁLCULO DE LA FECHA DE RECORDATORIO ---
    
    if fecha_tarea_dt and regla_timedelta:
        fecha_recordatorio_dt = fecha_tarea_dt - regla_timedelta
    elif fecha_tarea_dt:
        fecha_recordatorio_dt = fecha_tarea_dt

    # Aseguramos un título limpio
    tarea_titulo = tarea_titulo.strip() 
    if not tarea_titulo:
         tarea_titulo = "Tarea sin nombre"


    # --- 5. CONSTRUCCIÓN DEL JSON FINAL PARA NOTION (CON CLAVES CORREGIDAS) ---
    
    fecha_tarea_iso = format_date_to_iso(fecha_tarea_dt)
    fecha_recordatorio_iso = format_date_to_iso(fecha_recordatorio_dt)

    properties = {
        "Nombre": {
            "title": [
                {
                    "text": {
                        "content": tarea_titulo
                    }
                }
            ]
        },
        "Prioridad": {
            "select": {
                "name": prioridad
            }
        },
        "Estado": {
            "status": {
                "name": estado
            }
        },
        # Clave del campo de fecha (confirmado)
        "Fecha/Hora de Tarea": {
            "date": {
                "start": fecha_tarea_iso
            }
        } if fecha_tarea_iso else None,
        
        # CLAVE CORREGIDA: Usamos el nombre que Notion muestra en el encabezado
        "Base del Registro": { 
            "select": {
                "name": recordatorio_base
            }
        },
        
        "Fecha de Recordatorio": {
            "date": {
                "start": fecha_recordatorio_iso
            }
        } if fecha_recordatorio_iso else None,
    }

    properties = {k: v for k, v in properties.items() if v is not None}

    return properties

# --- ENDPOINT QUE ENVÍA A NOTION (EL ORIGINAL) ---
@app.route("/agendar", methods=["POST"])
def agendar_tarea():
    if not NOTION_TOKEN or not DATABASE_ID:
        return jsonify({
            "error": "Configuración de Notion faltante",
            "NOTION_TOKEN_exists": bool(NOTION_TOKEN),
            "DATABASE_ID_exists": bool(DATABASE_ID)
        }), 500

    try:
        data = request.get_json()
        comando = data.get('comando', '')
        
        if not comando:
            return jsonify({"error": "No se recibió el comando"}), 400

        properties_payload = process_command(comando)

        if not properties_payload:
            return jsonify({"error": "No se pudo procesar el comando o no se extrajo información útil"}), 400

        import requests
        
        url = "https://api.notion.com/v1/pages"
        headers = {
            "Authorization": f"Bearer {NOTION_TOKEN}",
            "Content-Type": "application/json",
            "Notion-Version": "2022-06-28" 
        }
        
        payload = {
            "parent": {"database_id": DATABASE_ID},
            "properties": properties_payload
        }
        
        response = requests.post(url, headers=headers, json=payload)
        
        # Notion devuelve 200 para creación exitosa
        if response.status_code == 200:
            return jsonify({"mensaje": "Tarea agendada con éxito", "data": properties_payload}), 200
        else:
            # Intentar obtener el JSON de error de Notion
            try:
                notion_error = response.json()
            except:
                notion_error = {"raw_text": response.text}
            
            return jsonify({
                "error": "Error al insertar en Notion",
                "status_code": response.status_code,
                "notion_response": notion_error,
                "payload_sent": properties_payload 
            }), response.status_code

    except Exception as e:
        import traceback
        return jsonify({
            "error": f"Error interno del servidor: {str(e)}",
            "traceback": traceback.format_exc()
        }), 500

# --- ENDPOINT DEPURACIÓN AÑADIDO (PARA VER EL JSON GENERADO) ---
@app.route("/debug", methods=["POST"])
def debug_command():
    try:
        data = request.get_json()
        comando = data.get('comando', '')
        
        if not comando:
            return jsonify({"error": "No se recibió el comando"}), 400

        # Procesar el comando para obtener todas las propiedades
        properties_payload = process_command(comando)

        # Devolver el payload generado antes de enviarlo a Notion
        return jsonify({
            "status": "DEBUG OK",
            "comando_entrada": comando,
            "payload_generado": properties_payload
        }), 200

    except Exception as e:
        return jsonify({"error": f"Error interno en debug: {str(e)}"}), 500

# --- ENDPOINT DE DIAGNÓSTICO (VERIFICAR CONFIGURACIÓN) ---
@app.route("/health", methods=["GET"])
def health_check():
    """Endpoint para verificar la configuración del servidor."""
    token_status = "✅ Configurado" if NOTION_TOKEN else "❌ NO CONFIGURADO"
    db_status = "✅ Configurado" if DATABASE_ID else "❌ NO CONFIGURADO"
    
    # Mostrar solo los primeros/últimos caracteres por seguridad
    token_preview = f"{NOTION_TOKEN[:10]}...{NOTION_TOKEN[-4:]}" if NOTION_TOKEN and len(NOTION_TOKEN) > 14 else "N/A"
    db_preview = f"{DATABASE_ID[:8]}...{DATABASE_ID[-4:]}" if DATABASE_ID and len(DATABASE_ID) > 12 else "N/A"
    
    return jsonify({
        "status": "Server Running",
        "config": {
            "NOTION_TOKEN": token_status,
            "NOTION_TOKEN_preview": token_preview,
            "DATABASE_ID": db_status,
            "DATABASE_ID_preview": db_preview
        }
    }), 200

if __name__ == "__main__":
    app.run(debug=True)