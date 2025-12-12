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
DATABASE_ID = os.environ.get("NOTION_DATABASE_ID")

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
    tarea_titulo = comando_completo
    prioridad = 'Media' 
    estado = 'Pendiente' 
    recordatorio_base = 'Manual'
    
    fecha_tarea_dt = None
    fecha_recordatorio_dt = None
    regla_timedelta = None
    comando_limpio = comando_completo 

    # --- 2. DETECCIÓN DE REGLAS FIJAS (Prioridad y Recordatorio) ---
    
    # Detección de Prioridad 
    if re.search(r'prioridad alta|urgente', comando_completo, re.IGNORECASE):
        prioridad = 'Alta'
    elif re.search(r'prioridad baja|luego', comando_completo, re.IGNORECASE):
        prioridad = 'Baja'
    
    # Detección de Reglas de Recordatorio Fijas
    if re.search(r'un d[ií]a antes', comando_completo, re.IGNORECASE):
        recordatorio_base = '1 día antes'
        regla_timedelta = timedelta(days=1)
        comando_limpio = re.sub(r',? y recuérdamelo un d[ií]a antes\.?', '', comando_completo, flags=re.IGNORECASE).strip()
    elif re.search(r'una hora antes', comando_completo, re.IGNORECASE):
        recordatorio_base = '1 hora antes'
        regla_timedelta = timedelta(hours=1)
        comando_limpio = re.sub(r',? y recuérdamelo una hora antes\.?', '', comando_completo, flags=re.IGNORECASE).strip()
    
    # --- 3. EXTRACCIÓN DE FECHAS ---
    
    settings = {
        'PREFER_DATES_FROM': 'future', 
        'RETURN_AS_TIMEZONE_AWARE': True,
        'TIMEZONE': TIMEZONE 
    }
    
    # Intentamos parsear el comando LIMPIO
    fecha_encontrada = dateparser.parse(comando_limpio, settings=settings, languages=['es'])

    if fecha_encontrada:
        fecha_tarea_dt = fecha_encontrada
        # Título: Intentamos eliminar la cadena de fecha del comando limpio
        try:
            # Crea una representación de la fecha encontrada para eliminarla del comando
            fecha_str_to_remove = fecha_encontrada.strftime("%Y-%m-%d %H:%M:%S")
            tarea_titulo = comando_limpio.replace(fecha_str_to_remove, '').strip() 
        except Exception:
            tarea_titulo = comando_limpio

    if not tarea_titulo:
        tarea_titulo = comando_limpio

    # --- 4. CÁLCULO DE LA FECHA DE RECORDATORIO ---
    
    if fecha_tarea_dt and regla_timedelta:
        fecha_recordatorio_dt = fecha_tarea_dt - regla_timedelta
    elif fecha_tarea_dt:
        fecha_recordatorio_dt = fecha_tarea_dt


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
            "select": {
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
        return jsonify({"error": "Configuración de Notion faltante"}), 500

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
        
        if response.status_code == 200:
            return jsonify({"mensaje": "Tarea agendada con éxito", "data": properties_payload}), 200
        else:
            return jsonify({
                "error": "Error al insertar en Notion",
                "status_code": response.status_code,
                "notion_response": response.json(),
                "payload_sent": properties_payload 
            }), response.status_code

    except Exception as e:
        return jsonify({"error": f"Error interno del servidor: {str(e)}"}), 500

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

if __name__ == "__main__":
    app.run(debug=True)