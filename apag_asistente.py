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
    
    # Patrones de fecha en español para detectar y extraer
    patrones_fecha = [
        r'(pasado\s+mañana(?:\s+a\s+las?\s+\d{1,2}(?:\s*(?:am|pm|de\s+la\s+(?:mañana|tarde|noche)))?)?)',
        r'(mañana(?:\s+a\s+las?\s+\d{1,2}(?:\s*(?:am|pm|de\s+la\s+(?:mañana|tarde|noche)))?)?)',
        r'(hoy(?:\s+a\s+las?\s+\d{1,2}(?:\s*(?:am|pm|de\s+la\s+(?:mañana|tarde|noche)))?)?)',
        r'((?:el\s+)?(?:lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)(?:\s+a\s+las?\s+\d{1,2}(?:\s*(?:am|pm|de\s+la\s+(?:mañana|tarde|noche)))?)?)',
        r'(\d{1,2}\s+de\s+(?:enero|febrero|marzo|abril|mayo|junio|julio|agosto|septiembre|octubre|noviembre|diciembre)(?:\s+(?:de\s+)?\d{4})?(?:\s+a\s+las?\s+\d{1,2}(?:\s*(?:am|pm|de\s+la\s+(?:mañana|tarde|noche)))?)?)',
        r'(a\s+las?\s+\d{1,2}(?:\s*(?:am|pm|de\s+la\s+(?:mañana|tarde|noche)))?)',
    ]

    # Helper function to extract and remove matching patterns from text
    def extract_and_remove(text, patterns_dict, default_val):
        found_val = default_val
        cleaned_text = text
        for val, regex_pattern in patterns_dict.items():
            match = re.search(regex_pattern, cleaned_text, re.IGNORECASE)
            if match:
                found_val = val
                # Remove the matched text from the command
                cleaned_text = cleaned_text.replace(match.group(0), " ").strip()
                # We stop after first match per category to avoid conflicts
                break
        return found_val, cleaned_text

    # Buscamos el separador estricto '#' primero
    if '#' in comando_completo:
        tarea_titulo, comando_regla = comando_completo.split('#', 1)
        comando_regla = comando_regla.strip()
    else:
        # Sin separador: intentamos extraer automáticamente la fecha del texto
        comando_regla = None
        tarea_titulo = comando_completo
        
        for patron in patrones_fecha:
            match = re.search(patron, comando_completo, re.IGNORECASE)
            if match:
                comando_regla = match.group(1)
                # Remover la fecha del título (DESACTIVADO: El usuario quiere conservar la fecha en el título)
                # tarea_titulo = comando_completo.replace(match.group(0), '').strip()
                break
        
        # Si no se encontró fecha, usar todo el comando como regla también
        if not comando_regla:
            comando_regla = comando_completo
        
    prioridad = 'Normal' 
    estado = 'Sin empezar' 
    recordatorio_base = 'Manual'
    
    fecha_tarea_dt = None
    fecha_recordatorio_dt = None
    regla_timedelta = None
    
    # --- 2. DETECCIÓN Y EXTRACCIÓN DE METADATOS (Prioridad, Estado, Recordatorio) ---
    
    # Prioridad
    # Prioridad
    prioridad_patterns = {
        'Alta': r'prioridad\s+alta|urgente|muy\s+importante|importante|importe',
        'Baja': r'prioridad\s+baja|luego|no\s+urgente',
        'Media': r'prioridad\s+media|normal' # Optional explicit normal
    }
    prioridad, tarea_titulo = extract_and_remove(tarea_titulo, prioridad_patterns, prioridad)

    # Estado
    estado_patterns = {
        'En curso': r'estado\s+en\s+curso|en\s+proceso|trabajando',
        'Listo': r'estado\s+listo|hecho|terminado|completado|finalizado',
        'Sin empezar': r'estado\s+sin\s+empezar|pendiente'
    }
    estado, tarea_titulo = extract_and_remove(tarea_titulo, estado_patterns, estado)

    # Recordatorio
    # Maps internal value to regex
    recordatorio_patterns = {
        '1 día antes': r'recor?d[aá]r?me?\s+(?:un|1)\s+d[ií]a\s+antes|(?:un|1)\s+d[ií]a\s+antes',
        '1 hora antes': r'recor?d[aá]r?me?\s+(?:una|1)\s+hora\s+antes|(?:una|1)\s+hora\s+antes'
    }
    recordatorio_base, tarea_titulo = extract_and_remove(tarea_titulo, recordatorio_patterns, recordatorio_base)
    
    # Logic to set timedelta object based on the extracted string
    if recordatorio_base == '1 día antes':
        regla_timedelta = timedelta(days=1)
    elif recordatorio_base == '1 hora antes':
        regla_timedelta = timedelta(hours=1)

    # Limpieza final del título
    # Remover conectores residuales al inicio
    tarea_titulo = re.sub(r'^(que\s+|para\s+|tengo\s+que\s+)', '', tarea_titulo, flags=re.IGNORECASE)
    # Remover espacios múltiples
    tarea_titulo = re.sub(r'\s{2,}', ' ', tarea_titulo).strip()


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
    try:
        hoy = datetime.now(tz)
    except:
        # Fallback if tz fails (unlikely)
        hoy = datetime.now()
        
    fecha_encontrada = None
    
    # Mapeo de días de la semana
    dias_semana = {
        'lunes': 0, 'martes': 1, 'miércoles': 2, 'miercoles': 2,
        'jueves': 3, 'viernes': 4, 'sábado': 5, 'sabado': 5, 'domingo': 6
    }
    
    # Detectar "pasado mañana"
    if comando_regla and re.search(r'pasado\s+mañana', comando_regla, re.IGNORECASE):
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
    elif comando_regla and (match := re.search(r'(?:el\s+)?(lunes|martes|mi[eé]rcoles|jueves|viernes|s[aá]bado|domingo)', comando_regla, re.IGNORECASE)):
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
    if not fecha_encontrada and comando_regla:
        fecha_encontrada = dateparser.parse(comando_regla, settings=settings)

    # --- 3.1. EXTRACCIÓN DE HORA INDEPENDIENTE (Fix para "mañana ... a las 6 pm") ---
    # Regex para buscar "a las X [pm]", "a la 1 [pm]"
    time_regex = r'(?:a\s+las?|a\s+la)\s+(\d{1,2}(?::\d{2})?)\s*(am|pm|p\.?m\.?|a\.?m\.?|de\s+la\s+(?:mañana|tarde|noche))?'
    
    match_time = re.search(time_regex, tarea_titulo, re.IGNORECASE)
    if match_time:
        # Extraer datos de hora
        hora_str = match_time.group(1)
        periodo = match_time.group(2) or ''
        
        # Parsear hora y minutos
        if ':' in hora_str:
            hora_val, min_val = map(int, hora_str.split(':'))
        else:
            hora_val = int(hora_str)
            min_val = 0
            
        # Ajuste AM/PM
        periodo = periodo.lower().replace('.', '')
        if 'pm' in periodo or 'tarde' in periodo or 'noche' in periodo:
            if hora_val < 12:
                hora_val += 12
        elif 'am' in periodo or 'mañana' in periodo:
            if hora_val == 12:
                hora_val = 0
                
        # Si ya teníamos fecha, actualizamos su hora
        if fecha_encontrada:
            fecha_encontrada = fecha_encontrada.replace(hour=hora_val, minute=min_val, second=0, microsecond=0)
        else:
            # Si no, asumimos Hoy + Hora
            fecha_encontrada = hoy.replace(hour=hora_val, minute=min_val, second=0, microsecond=0)
            
        # Remover la hora del título (DESACTIVADO: El usuario quiere conservarla)
        # tarea_titulo = tarea_titulo.replace(match_time.group(0), " ").strip()

    if fecha_encontrada:
        fecha_tarea_dt = fecha_encontrada

    # --- 4. CÁLCULO DE LA FECHA DE RECORDATORIO ---
    
    if fecha_tarea_dt and regla_timedelta:
        fecha_recordatorio_dt = fecha_tarea_dt - regla_timedelta
    elif fecha_tarea_dt:
        fecha_recordatorio_dt = fecha_tarea_dt

    # Aseguramos un título limpio
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