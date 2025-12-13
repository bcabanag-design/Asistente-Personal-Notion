import os
import json
import re
from datetime import datetime, timedelta
import dateparser
from flask import Flask, request, jsonify

# Nota: Asegúrate de que pytz esté instalado en requirements.txt
# pìp install pytz
import requests
import threading
import time

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
        r'(en\s+(?:\d+|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|media|med\w+)\s+(?:horas?|hr?s?|minutos?|mins?))',
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
    
    # Lista / Contexto (Supermercado, Viaje, etc.)
    lista = None
    # Regex para: "para la lista X", "en la lista X", "lista X"
    match_lista = re.search(r'(?:para|en|a)\s+(?:la\s+)?lista\s+(?:de\s+)?([a-zA-Z0-9áéíóúÁÉÍÓÚñÑ]+)', tarea_titulo, re.IGNORECASE)
    if match_lista:
        lista = match_lista.group(1).title() # Capitalize "Supermercado"
        # Remover del título
        tarea_titulo = tarea_titulo.replace(match_lista.group(0), '').strip()

    
    # Logic to set timedelta object based on the extracted string
    if recordatorio_base == '1 día antes':
        regla_timedelta = timedelta(days=1)
    elif recordatorio_base == '1 hora antes':
        regla_timedelta = timedelta(hours=1)

    # Limpieza final del título
    # Remover conectores residuales al inicio
    tarea_titulo = re.sub(r'^(poner\s+|agregar\s+|anotar\s+|avisar\s+|avisa\s+|avisame\s+|avísame\s+|recuerda\s+|recuérdame\s+|recuerdame\s+|que\s+|para\s+|tengo\s+que\s+)', '', tarea_titulo, flags=re.IGNORECASE)
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

    # --- NUEVO: CÁLCULO MANUAL PARA "EN X HORAS/MINUTOS" ---
    # Esto evita depender de dateparser que a veces falla con "en una hora"
    elif comando_regla and (match := re.search(r'en\s+(.+?)\s+(horas?|hr?s?|minutos?|mins?|segundos?|segs?)', comando_regla, re.IGNORECASE)):
        cantidad_txt = match.group(1).lower().strip()
        unidad = match.group(2).lower()
        
        # Normalizar cantidad
        num_map = {
            'un': 1, 'una': 1, 'dos': 2, 'tres': 3, 'cuatro': 4,
            'cinco': 5, 'seis': 6, 'siete': 7, 'ocho': 8, 'nueve': 9, 'diez': 10,
            'media': 0.5
        }
        
        cantidad = 0
        if cantidad_txt.isdigit():
            cantidad = float(cantidad_txt)
        else:
            cantidad = num_map.get(cantidad_txt, 0)
            
        if cantidad > 0:
            if 'hora' in unidad or 'hr' in unidad:
                fecha_encontrada = hoy + timedelta(hours=cantidad)
            elif 'min' in unidad:
                fecha_encontrada = hoy + timedelta(minutes=cantidad)
            elif 'seg' in unidad:
                fecha_encontrada = hoy + timedelta(seconds=cantidad)
    
    # Si no hubo detección personalizada, usar dateparser
    if not fecha_encontrada and comando_regla:
        # (Mantener normalización por si acaso entra aquí por otra ruta)
        # --- NORMALIZACIÓN DE NÚMEROS EN TEXTO (Fix para "en dos horas") ---
        # Map simple Spanish numbers to digits
        num_map = {
            'un': '1', 'una': '1', 'dos': '2', 'tres': '3', 'cuatro': '4',
            'cinco': '5', 'seis': '6', 'siete': '7', 'ocho': '8', 'nueve': '9', 'diez': '10',
            'media': '0.5' # Special case, dateparser might need help 
        }
        
        # Regex to find these words isolated
        for word, digit in num_map.items():
            # Replace whole word matches only
            comando_regla = re.sub(r'\b' + re.escape(word) + r'\b', digit, comando_regla, flags=re.IGNORECASE)
            
        # Fix "en 0.5 hora" -> "en 30 minutos" for better parsing if needed, but "en 0.5 horas" might work.
        # Let's handle "media hora" explicitly if the above is clunky
        comando_regla = re.sub(r'media\s+hora', '30 minutos', comando_regla, flags=re.IGNORECASE)
        
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
        
        # PROPIEDAD LISTA (Nueva)
        "Lista": {
            "select": {
                "name": lista
            }
        } if lista else None,
    }

    properties = {k: v for k, v in properties.items() if v is not None}

    # Meta datos para lógica de scheduling
    meta_data = {
        "reminder_dt": fecha_recordatorio_dt
    }

    return properties, meta_data

def create_task_logic(comando):
    """
    Lógica central para crear tareas en Notion.
    Retorna un diccionario con el resultado y un código de estado sugerido.
    """
    if not comando:
        return {"error": "No se recibió el comando"}, 400

    properties_payload, meta_data = process_command(comando)

    if not properties_payload:
        return {"error": "No se pudo procesar el comando"}, 400

    # DETECCIÓN DE MÚLTIPLES ITEMS (SOLO SI HAY LISTA)
    items_a_guardar = []
    is_multilist = False
    
    if "Lista" in properties_payload:
        original_title = properties_payload["Nombre"]["title"][0]["text"]["content"]
        # import re removed
        split_items = re.split(r',\s*|\s+(?:y|e)\s+', original_title)
        split_items = [i.strip() for i in split_items if i.strip()]
        
        if len(split_items) > 1:
            is_multilist = True
            for item in split_items:
                import copy
                new_props = copy.deepcopy(properties_payload)
                new_props["Nombre"]["title"][0]["text"]["content"] = item.capitalize()
                items_a_guardar.append(new_props)
        else:
            items_a_guardar.append(properties_payload)
    else:
        items_a_guardar.append(properties_payload)

    url = "https://api.notion.com/v1/pages"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28" 
    }
    
    created_count = 0
    last_response = None
    
    for props in items_a_guardar:
        payload = {
            "parent": {"database_id": DATABASE_ID},
            "properties": props
        }
        last_response = requests.post(url, headers=headers, json=payload)
        if last_response.status_code == 200:
            created_count += 1
    
    if created_count > 0:
        msg_exito = f"{created_count} tareas agendadas" if is_multilist else "Tarea agendada con éxito"
        result_json = {
            "mensaje": msg_exito, 
            "data": properties_payload,
            "titulo_principal": items_a_guardar[0]["Nombre"]["title"][0]["text"]["content"] # Útil para feedback
        }
        
        # --- SMART SCHEDULING LOGIC ---
        reminder_dt = meta_data.get("reminder_dt")
        if reminder_dt:
            import pytz
            tz = pytz.timezone(TIMEZONE)
            now = datetime.now(tz)
            if reminder_dt.tzinfo is None:
                reminder_dt = tz.localize(reminder_dt)
            
            diff = (reminder_dt - now).total_seconds()
            
            if 0 < diff < 3900:
                diff_int = int(diff)
                if diff_int >= 60:
                    minutos = diff_int // 60
                    seg_rest = diff_int % 60
                    if seg_rest > 30: minutos += 1
                    msg_voz = f"Listo. Te aviso en {minutos} minutos."
                else:
                    msg_voz = f"Listo. Te aviso en {diff_int} segundos."

                result_json["smart_schedule"] = {
                    "wait_seconds": diff_int,
                    "is_soon": True,
                    "msg": msg_voz
                }
                
                # --- THREADING TRIGGER ---
                # Retrieve the page ID from the LAST response found
                if last_response and last_response.status_code == 200:
                    try:
                        new_page_id = last_response.json().get('id')
                        title_safe = items_a_guardar[0]["Nombre"]["title"][0]["text"]["content"]
                        priority_safe = items_a_guardar[0]["Prioridad"]["select"]["name"]
                        
                        # Start Timer
                        timer = threading.Timer(diff_int, send_reminder_now, args=[title_safe, priority_safe, new_page_id])
                        timer.start()
                    except Exception as e:
                         print(f"Error starting timer: {e}")
        
        return result_json, 200
    else:
        # Error (usamos la última respuesta para info)
        try:
            notion_error = last_response.json()
        except:
            notion_error = {"raw_text": last_response.text if last_response else "No requests made"}
        
        return {
            "error": "Error al insertar en Notion",
            "notion_response": notion_error
        }, last_response.status_code if last_response else 500


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
        
        # Delegar lógica central
        result, status_code = create_task_logic(comando)
        return jsonify(result), status_code

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
        properties_payload, meta_data = process_command(comando)

        # Devolver el payload generado antes de enviarlo a Notion
        return jsonify({
            "status": "DEBUG OK",
            "comando_entrada": comando,
            "payload_generado": properties_payload,
            "meta_generada": str(meta_data)
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

# --- CONFIGURACIÓN TELEGRAM ---
TELEGRAM_TOKEN = "8277083663:AAFQzy180bpJGhcHn-BN9ESgVvVySjTRGAo"
TELEGRAM_CHAT_ID = "2135365686"

# --- ENDPOINT DE RECORDATORIOS INTERACTIVOS ---
@app.route("/check_reminders", methods=["GET"])
def check_reminders():
    if not NOTION_TOKEN or not DATABASE_ID:
        return jsonify({"error": "Configuración incompleta"}), 500

    import pytz
    
    # 1. Definir ventana de tiempo (Persistencia: Desde hoy temprano hasta 2 horas adelante)
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    
    # "Siga haciendo el recordatorio": Buscamos tareas de las últimas 24h que sigan pendientes
    start_window = now - timedelta(hours=24) 
    end_window = now + timedelta(hours=2) 
    
    start_iso = start_window.isoformat()
    end_iso = end_window.isoformat()
    
    # 2. Construir Query a Notion
    url = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    headers = {
        "Authorization": f"Bearer {NOTION_TOKEN}",
        "Content-Type": "application/json",
        "Notion-Version": "2022-06-28"
    }
    
    # Filtro: (Fecha >= Ayer) AND (Fecha <= Ahora + 2h) AND (Estado != Listo)
    query_payload = {
        "filter": {
            "and": [
                {
                    "property": "Fecha de Recordatorio",
                    "date": {
                        "on_or_after": start_iso
                    }
                },
                {
                    "property": "Fecha de Recordatorio",
                    "date": {
                        "on_or_before": end_iso
                    }
                },
                {
                    "property": "Estado",
                    "status": {
                        "does_not_equal": "Listo"
                    }
                }
            ]
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=query_payload)
        
        if response.status_code != 200:
             return jsonify({"error": "Error consultando Notion", "details": response.json()}), response.status_code
             
        data = response.json()
        tasks_sent = 0
        tasks_text_list = []
        
        # 3. ENVIAR MENSAJES INDIVIDUALES CON BOTÓN
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        
        for result in data.get("results", []):
            page_id = result.get("id") # ID de la página para el callback
            props = result.get("properties", {})
            
            # Título
            title_list = props.get("Nombre", {}).get("title", [])
            title = title_list[0].get("text", {}).get("content", "Sin título") if title_list else "Sin título"
            
            # Hora
            date_prop = props.get("Fecha de Recordatorio", {}).get("date", {})
            start_date_str = date_prop.get("start")
            hora_legible = "Hora?"
            if start_date_str:
                try:
                    dt = dateparser.parse(start_date_str)
                    hora_legible = dt.strftime("%I:%M %p")
                except:
                    pass
            
            # Prioridad
            priority = props.get("Prioridad", {}).get("select", {}).get("name", "Normal")
            icon = "🔴" if "Alta" in priority or "Urgente" in priority else "🔵"

            # Mensaje Bonito
            msg_text = f"{icon} *RECORDATORIO* {icon}\n\n📌 *{title}*\n⏰ {hora_legible}\n🚨 Prioridad: {priority}"
            
            # Guardar texto para voz
            tasks_text_list.append(f"Recordatorio: {title}")
            
            # Teclado Inline (Botones: Listo y Posponer)
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "✅ Hecho / Terminar", "callback_data": f"done_{page_id}"},
                    {"text": "⏱ Posponer", "callback_data": f"snooze_{page_id}"}
                ]]
            }

            tg_payload = {
                "chat_id": TELEGRAM_CHAT_ID, 
                "text": msg_text, 
                "parse_mode": "Markdown",
                "reply_markup": reply_markup
            }
            requests.post(tg_url, json=tg_payload)
            tasks_sent += 1
            
        return jsonify({
            "count": tasks_sent,
            "status": "Messages sent" if tasks_sent > 0 else "No pending tasks",
            "voice_texts": tasks_text_list
        }), 200

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

# --- ENDPOINT REPORT DIARIO (Cierre del día) ---
@app.route("/daily_summary", methods=["GET", "POST"])
def daily_summary():
    if not NOTION_TOKEN or not DATABASE_ID:
        return jsonify({"error": "Configuración incompleta"}), 500

    import pytz
    tz = pytz.timezone(TIMEZONE)
    now = datetime.now(tz)
    
    # Rango: Todo el día de hoy
    start_day = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end_day = now.replace(hour=23, minute=59, second=59, microsecond=999999)
    dia_str = now.strftime("%d/%m")

    # Query Notion
    url_query = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
    
    query_payload = {
        "filter": {
            "and": [
                {
                    "property": "Fecha de Recordatorio",
                    "date": {"on_or_after": start_day.isoformat()}
                },
                {
                    "property": "Fecha de Recordatorio",
                    "date": {"on_or_before": end_day.isoformat()}
                }
            ]
        },
        "sorts": [{"property": "Estado", "direction": "ascending"}]
    }
    
    try:
        data = requests.post(url_query, headers=headers, json=query_payload).json()
        results = data.get("results", [])
        
        liquidadas = []
        pendientes = []
        
        for res in results:
            props = res.get("properties", {})
            # Título
            t = props.get("Nombre", {}).get("title", [])
            titulo = t[0].get("text", {}).get("content", "Sin título") if t else "Sin título"
            
            # Estado
            status = props.get("Estado", {}).get("status", {}).get("name", "Sin empezar")
            
            if status == "Listo":
                liquidadas.append(titulo)
            else:
                pendientes.append(titulo)
                
        # Construir Mensaje
        msg = f"🌙 *Cierre del Día ({dia_str})*\n\n"
        
        if liquidadas:
            msg += "✅ *Liquidadas:*\n"
            for t in liquidadas: msg += f"▪️ ~{t}~\n"
        else:
            msg += "✅ *Liquidadas:* 0 (¡A ponerse las pilas!)\n"
            
        msg += "\n"
        
        if pendientes:
            msg += "🚨 *Pendientes (¡Atención!):*\n"
            for t in pendientes: msg += f"▪️ {t}\n"
            msg += "\n_Recuerda: Líquidalas o Pospónlas para mañana._"
        else:
            msg += "✨ *¡Todo limpio! Buen trabajo hoy.*"
            
        # Enviar
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg,
            "parse_mode": "Markdown"
        })
        
        return jsonify({
            "status": "Report sent",
            "liquidadas": len(liquidadas),
            "pendientes": len(pendientes)
        }), 200

    except Exception as e:
        import traceback
        return jsonify({"error": str(e), "trace": traceback.format_exc()}), 500

# --- INTERNAL SCHEDULER (IMMEDIATE REMINDERS) ---
def send_reminder_now(title, priority, page_id):
    """Function to send a reminder immediately via threading."""
    try:
        # Wait a bit or logic handled by Timer
         # Construir payload de mensaje
        icon = "🔴" if "Alta" in priority or "Urgente" in priority else "🔵"
        msg_text = f"{icon} *RECORDATORIO* {icon}\n\n📌 *{title}*\n⏰ AHORA (Programado)\n🚨 Prioridad: {priority}"
        
        reply_markup = {
            "inline_keyboard": [[
                {"text": "✅ Hecho / Terminar", "callback_data": f"done_{page_id}"},
                {"text": "⏱ Posponer", "callback_data": f"snooze_{page_id}"}
            ]]
        }
        
        tg_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(tg_url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": msg_text,
            "parse_mode": "Markdown",
            "reply_markup": reply_markup
        })
        print(f"Immediate reminder sent for: {title}")
        
    except Exception as e:
        print(f"Error in internal scheduler: {e}")

# --- WEBHOOK PARA RECIBIR CLICS DE TELEGRAM ---
@app.route("/telegram_webhook", methods=["POST"])
def telegram_webhook():
    update = request.get_json()
    
    # Verificar si es un callback_query (clic en botón)
    if "callback_query" in update:
        cb = update["callback_query"]
        callback_id = cb["id"]
        chat_id = cb["message"]["chat"]["id"]
        message_id = cb["message"]["message_id"]
        data = cb["data"] # Ej: "done_12345-abcde..."
        
        if data.startswith("done_"):
            page_id = data.split("done_")[1]
            
            # 1. Actualizar Notion a "Listo"
            notion_url = f"https://api.notion.com/v1/pages/{page_id}"
            headers = {
                "Authorization": f"Bearer {NOTION_TOKEN}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28"
            }
            payload = {
                "properties": {
                    "Estado": {
                        "status": {"name": "Listo"}
                    }
                }
            }
            
            res_notion = requests.patch(notion_url, headers=headers, json=payload)
            
            # 2. Responder a Telegram (Feedback visual)
            tg_url_answer = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
            if res_notion.status_code == 200:
                requests.post(tg_url_answer, json={"callback_id": callback_id, "text": "¡Tarea completada! 🎉"})
                
                # Editar el mensaje original para tacharlo o indicar completado
                tg_url_edit = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/editMessageText"
                new_text = f"✅ ~TAREA COMPLETADA~ ✅\n\n(Guardado en Notion)"
                requests.post(tg_url_edit, json={
                    "chat_id": chat_id,
                    "message_id": message_id,
                    "text": new_text,
                    "parse_mode": "Markdown"
                })
            else:
                requests.post(tg_url_answer, json={"callback_id": callback_id, "text": "Error actualizando Notion 😢"})

        elif data.startswith("snooze_"):
            page_id = data.split("snooze_")[1]
            
            # Responder al callback para quitar el estado de carga
            tg_url_answer = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/answerCallbackQuery"
            requests.post(tg_url_answer, json={"callback_id": callback_id, "text": "Ok, ¿para cuándo?"})
            
            # Enviar mensaje preguntando nuevo tiempo (ForceReply)
            # Incluimos el page_id en el texto de forma invisible/sutil para recuperarlo luego
            # Usamos Markdown con link invisible zero-width o al final
            # Estrategia simple: Texto al final
            msg_text = f"⏳ ¿En cuánto tiempo (o a qué hora) quieres que te recuerde esta tarea?\n\n_(Responde a este mensaje. Ej: 30 min, 1 hora, mañana a las 9)_"
            # Hack: Ocultamos el ID en una URL markdown que no se ve
            # O simplemente lo ponemos explicito pero pequeño.
            # Vamos a usar texto invisible : [ ](http://id_context/ID)
            msg_text += f"[\u200b](http://context/{page_id})"

            tg_payload = {
                "chat_id": chat_id,
                "text": msg_text,
                "parse_mode": "Markdown",
                "reply_markup": {
                    "force_reply": True,
                    "input_field_placeholder": "Ej: 15 minutos, mañana..."
                }
            }
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json=tg_payload)

    # 2. Manejo de MENSAJES de texto (Para consultar listas)
    # 1.5. Manejo de MENSAJES DE VOZ (Google Speech Recognition - FREE)
    elif "voice" in update.get("message", {}):
        msg = update["message"]
        chat_id = msg.get("chat", {}).get("id")
        voice_info = msg.get("voice", {})
        file_id = voice_info.get("file_id")
        
        # 1. Obtener Link del Archivo
        tg_file_url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/getFile?file_id={file_id}"
        
        temp_oga = None
        temp_wav = None

        try:
            import speech_recognition as sr
            from pydub import AudioSegment
            import io

            # Get File Path from Telegram
            res_path = requests.get(tg_file_url).json()
            if not res_path.get("ok"):
                raise Exception("Error getting file path from Telegram")
                
            file_path = res_path["result"]["file_path"]
            download_url = f"https://api.telegram.org/file/bot{TELEGRAM_TOKEN}/{file_path}"
            
            # 2. Descargar
            audio_content = requests.get(download_url).content
            
            # Guardar temporalmente como .oga
            import tempfile
            with tempfile.NamedTemporaryFile(suffix=".oga", delete=False) as f:
                f.write(audio_content)
                temp_oga = f.name
            
            # 3. Convertir a WAV (Requerido por SpeechRecognition)
            # pydub usa ffmpeg (debe estar en el sistema/Aptfile)
            temp_wav = temp_oga.replace(".oga", ".wav")
            audio = AudioSegment.from_ogg(temp_oga)
            audio.export(temp_wav, format="wav")
            
            # 4. Transcribir con Google Speech Recognition
            r = sr.Recognizer()
            with sr.AudioFile(temp_wav) as source:
                audio_data = r.record(source)
                # language='es-ES' (Español)
                transcribed_text = r.recognize_google(audio_data, language="es-ES")
            
            # 5. Informar al usuario lo que se entendió
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                "chat_id": chat_id, 
                "text": f"🗣️ *Escuché*: \"{transcribed_text}\"", 
                "parse_mode": "Markdown"
            })
            
            # 6. PROCESAR COMO TEXTO
            text = transcribed_text.strip()
            
            # --- COPIA LÓGICA DE TEXTO (DRY pendiente) ---
            
            # A. AGENDA
            # import re removed
            # import dateparser removed
            agenda_date = None
            if re.search(r'(agenda|que\s+tengo|qué\s+tengo|actividades|pendientes|calendario)', text, re.IGNORECASE):
                 clean_text = re.sub(r'(agenda|que\s+tengo|qué\s+tengo|actividades|pendientes|calendario)', '', text, flags=re.IGNORECASE).strip()
                 if not clean_text: clean_text = "hoy"
                 try: 
                     agenda_date = dateparser.parse(clean_text, settings={'PREFER_DATES_FROM': 'future', 'TIMEZONE': TIMEZONE, 'RETURN_AS_TIMEZONE_AWARE': True})
                 except: pass

            if agenda_date:
                # RECURSIVIDAD SIMULADA:
                # No podemos llamar a la ruta HTTP facilmente, así que lo manejamos como error o "Feature no disponible en voz completa".
                # O mejor, ejecutamos la logica de agenda aqui (duplicada por ahora).
                # (Simplificación: Si es agenda por voz, le decimos que mire el chat escrito o implementamos la Query aqui)
                # Para evitar duplicar 50 lineas, vamos a instanciar la logica de Query directamente.
                pass # Por brevedad, asumiremos que el usuario usa "Agenda" por texto o aceptamos que por voz solo crea tareas por ahora si es complejo.
                # PERO: El usuario pidió funcionalidad completa. Vamos a intentar parsear "Agenda" aqui también.
                # (Mejor: Llamar a create_task_logic solo si no es agenda).
                pass

            # Si es Agenda (y tenemos fecha), ejecutamos la consulta rapida
            if agenda_date:
                # ... Lógica de Agenda (Simplificada) ...
                 import pytz
                 tz = pytz.timezone(TIMEZONE)
                 if agenda_date.tzinfo is None: agenda_date = tz.localize(agenda_date)
                 start_day = agenda_date.replace(hour=0, minute=0, second=0)
                 end_day = agenda_date.replace(hour=23, minute=59, second=59)
                 dia_str = start_day.strftime("%A %d/%m")
                 
                 url_query = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
                 headers_notion = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
                 q_payload = {
                    "filter": {"and": [{"property": "Fecha de Recordatorio", "date": {"on_or_after": start_day.isoformat()}}, {"property": "Fecha de Recordatorio", "date": {"on_or_before": end_day.isoformat()}}]},
                    "sorts": [{"property": "Fecha de Recordatorio", "direction": "ascending"}]
                 }
                 data_n = requests.post(url_query, headers=headers_notion, json=q_payload).json()
                 results = data_n.get("results", [])
                 if results:
                    msg_response = f"📅 *Agenda ({dia_str})*:\n"
                    for res in results:
                        t = res.get("properties", {}).get("Nombre", {}).get("title", [])
                        t_txt = t[0].get("text", {}).get("content", "") if t else ""
                        msg_response += f"▫️ {t_txt}\n"
                 else:
                    msg_response = f"📅 Nada para {dia_str}."
                 
            else:
                # B. CREAR TAREA (Default)
                result, code = create_task_logic(text)
                if code == 200:
                    created_title = result.get("titulo_principal", "Tarea")
                    is_soon = result.get("smart_schedule", {}).get("is_soon", False)
                    msg_voz = result.get("smart_schedule", {}).get("msg", "")
                    
                    msg_response = f"✅ *Agendado*: {created_title}"
                    if is_soon: msg_response += f"\n\n🔔 {msg_voz}"
                else:
                    msg_response = f"❌ Error: {result.get('error')}"

            # Enviar Respuesta Final
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                "chat_id": chat_id, "text": msg_response, "parse_mode": "Markdown"
            })

        except Exception as e:
            requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                "chat_id": chat_id, "text": f"⚠️ Error audio: {str(e)}"
            })
        
        finally:
            # Limpieza
            if temp_oga and os.path.exists(temp_oga): os.remove(temp_oga)
            if temp_wav and os.path.exists(temp_wav): os.remove(temp_wav)

        return "OK", 200

    # 2. Manejo de MENSAJES de texto
    elif "message" in update:
        msg = update["message"]
        chat_id = msg.get("chat", {}).get("id")
        text = msg.get("text", "").strip()
        
        # --- DETECCIÓN DE RESPUESTA A SNOOZE (Reply) ---
        if reply_to:
            page_id = None
            
            # Estrategia 1: Buscar en entities (hidden link)
            entities = reply_to.get("entities", [])
            for ent in entities:
                if ent.get("type") == "text_link":
                    url = ent.get("url", "")
                    if "context/" in url:
                         match_id = re.search(r'context/([a-zA-Z0-9\-]+)', url)
                         if match_id:
                             page_id = match_id.group(1)
                             break
            
            if page_id:
                
                # Calcular nueva fecha usando la lógica existente en process_command o simple dateparser
                # Reutilizamos lógica de clean y dateparser de arriba
                # import dateparser removed
                from datetime import datetime, timedelta
                
                # Usamos el texto del usuario como input de tiempo
                # settings = {'PREFER_DATES_FROM': 'future', 'TIMEZONE': TIMEZONE, 'RETURN_AS_TIMEZONE_AWARE': True}
                # Simplificado: Usamos process_command auxiliar o logica directa
                # Como process_command extrae de todo, a veces es too much. Mejor dateparser limpio + hacks de "en X minutos"
                
                # --- HACK RAPIDO "EN X MINUTOS" (Copied from process_command) ---
                import pytz
                tz = pytz.timezone(TIMEZONE)
                now = datetime.now(tz)
                new_reminder_dt = None
                
                # Regex manual para "en X"
                # Regex manual para "en X"
                match_en = re.search(r'en\s+(.+?)\s+(horas?|hr?s?|minutos?|mins?|segundos?|segs?)', text, re.IGNORECASE)
                if match_en:
                     val = match_en.group(1)
                     unit = match_en.group(2)
                     try:
                        cant = float(val)
                     except:
                        cant = 1 # fallback simple
                        
                     if 'hora' in unit: new_reminder_dt = now + timedelta(hours=cant)
                     elif 'min' in unit: new_reminder_dt = now + timedelta(minutes=cant)
                     elif 'seg' in unit: new_reminder_dt = now + timedelta(seconds=cant)
                
                # Si no match manual, dateparser
                if not new_reminder_dt:
                    new_reminder_dt = dateparser.parse(text, settings={'PREFER_DATES_FROM': 'future', 'TIMEZONE': TIMEZONE, 'RETURN_AS_TIMEZONE_AWARE': True})

                if new_reminder_dt:
                    # Garantizar timezone
                    if new_reminder_dt.tzinfo is None:
                        new_reminder_dt = tz.localize(new_reminder_dt)
                        
                    # ACTUALIZAR NOTION
                    url_patch = f"https://api.notion.com/v1/pages/{page_id}"
                    headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
                    
                    # Formato ISO
                    iso_date = format_date_to_iso(new_reminder_dt)
                    
                    payload = {
                        "properties": {
                            "Fecha de Recordatorio": {
                                "date": {"start": iso_date}
                            },
                             # Opcional: Cambiar estado a "Sin empezar" si estaba en otro (para asegurar que vuelva a salir)
                             # Pero mejor no tocar estado si no se pide.
                        }
                    }
                    
                    r_patch = requests.patch(url_patch, headers=headers, json=payload)
                    
                    if r_patch.status_code == 200:
                        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                            "chat_id": chat_id,
                            "text": f"✅ Pospuesto para: *{new_reminder_dt.strftime('%d/%m %I:%M %p')}*",
                            "parse_mode": "Markdown"
                        })
                    else:
                         requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                            "chat_id": chat_id, "text": f"⚠️ Error Notion: {r_patch.text}"
                        })
                else:
                    requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", json={
                            "chat_id": chat_id, "text": "⚠️ No entendí la fecha. Intenta de nuevo (ej: 'en 30 min')."
                        })
                

                # --- THREADING FOR SNOOZE (Immediate) ---
                # Check directly if it's soon (< 1h)
                if new_reminder_dt:
                    diff_snooze = (new_reminder_dt - now).total_seconds()
                    if 0 < diff_snooze < 3600:
                         try:
                            # Re-fetch title/priority not easy without query.
                            # Just use generic info or assume it's same.
                            # For better UX, we could pass title in hidden link too? No, too long.
                            # Query Notion to start thread with correct info
                            # OR: Just send generic "Recordatorio Pospuesto"
                            
                            # Simple Query to get Title/Priority
                            u_page = f"https://api.notion.com/v1/pages/{page_id}"
                            r_page = requests.get(u_page, headers=headers) # Headers defined above in update
                            if r_page.status_code == 200:
                                p_data = r_page.json()
                                p_props = p_data.get("properties", {})
                                p_title = p_props.get("Nombre", {}).get("title", [])
                                title_real = p_title[0].get("text", {}).get("content", "Tarea") if p_title else "Tarea"
                                p_rio = p_props.get("Prioridad", {}).get("select", {}).get("name", "Normal")
                                
                                timer = threading.Timer(diff_snooze, send_reminder_now, args=[title_real, p_rio, page_id])
                                timer.start()
                                print(f"Thread started for snooze: {diff_snooze}s")
                         except Exception as ex:
                             print(f"Error starting snooze thread: {ex}")

                return "OK", 200 # Stop processing here

        lista_nombre = None
        agenda_date = None
        
        # --- A. DETECTAR LISTA ---
        # Opción 1: Atajo con "@" (Ej: "@Super")
        if text.startswith("@"):
            lista_nombre = text[1:].strip().title()
        
        # Opción 2: "Ver lista X"
        if not lista_nombre:
            # import re removed
            match_lista = re.search(r'^\s*(?:dame|ver|consultar|mostrar|tengo)?\s*(?:la\s+)?lista\s+(?:de\s+|del\s+|para\s+el\s+|para\s+la\s+|para\s+)?(.+)', text, re.IGNORECASE)
            if match_lista and "lista" in text.lower():
                 lista_nombre = match_lista.group(1).strip().title()

        # --- B. DETECTAR AGENDA (Si no es lista) ---
        if not lista_nombre:
            # Palabras clave: Agenda, qué tengo, actividades, calendario
            if re.search(r'(agenda|que\s+tengo|qué\s+tengo|actividades|pendientes|calendario)', text, re.IGNORECASE):
                # Intentar extraer fecha del texto (Ej: "Agenda mañana")
                # Si no hay fecha explícita, asumimos "hoy" si dice "que tengo"
                # import dateparser removed
                settings = {'PREFER_DATES_FROM': 'future', 'TIMEZONE': TIMEZONE, 'RETURN_AS_TIMEZONE_AWARE': True}
                
                # Limpiar keywords para no confundir a dateparser
                # 1. Remover las palabras clave de detección
                clean_text = re.sub(r'(agenda|que\s+tengo|qué\s+tengo|actividades|pendientes|calendario)', '', text, flags=re.IGNORECASE)
                
                # 2. Remover prefijos conversacionales (pásame, dime, las, mis, toda la)
                clean_text = re.sub(r'^(p[áa]same|dime|dame|mu[ée]strame|ver|consultar)\s*', '', clean_text, flags=re.IGNORECASE)
                clean_text = re.sub(r'\b(las|mis|los|el|la|de|del|para|toda|todo|mi|tu)\b', ' ', clean_text, flags=re.IGNORECASE)
                
                clean_text = clean_text.strip()
                if not clean_text: clean_text = "hoy"
                
                try:
                    agenda_date = dateparser.parse(clean_text, settings=settings)
                    if agenda_date:
                         # Si es "que tengo hoy", dateparser puede dar fecha+hora actual. Queremos todo el día.
                         pass
                except:
                    pass

        # --- EJECUCIÓN ---

        # 1. CONSULTAR LISTA
        if lista_nombre:
            url_query = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
            headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
            query_payload = {"filter": {"and": [{"property": "Lista", "select": {"equals": lista_nombre}}, {"property": "Estado", "status": {"does_not_equal": "Listo"}}]}}
            
            try:
                data = requests.post(url_query, headers=headers, json=query_payload).json()
                tasks = [r.get("properties", {}).get("Nombre", {}).get("title", [])[0].get("text", {}).get("content", "") for r in data.get("results", []) if r.get("properties", {}).get("Nombre", {}).get("title")]
                
                if tasks:
                    msg_response = f"🛒 *Lista {lista_nombre}*: \n\n" + "\n".join([f"▫️ {t}" for t in tasks])
                else:
                    msg_response = f"🤷‍♂️ Nada en la lista *{lista_nombre}*."
            except Exception as e:
                msg_response = f"⚠️ Error Notion: {str(e)}"

        # 2. CONSULTAR AGENDA
        elif agenda_date:
            # Rango: Desde inicio del día hasta fin del día
            import pytz
            tz = pytz.timezone(TIMEZONE)
            if agenda_date.tzinfo is None: agenda_date = tz.localize(agenda_date)
            
            start_day = agenda_date.replace(hour=0, minute=0, second=0, microsecond=0)
            end_day = agenda_date.replace(hour=23, minute=59, second=59, microsecond=999999)
            
            dia_str = start_day.strftime("%A %d/%m") # Ej: Lunes 13/12
            
            url_query = f"https://api.notion.com/v1/databases/{DATABASE_ID}/query"
            headers = {"Authorization": f"Bearer {NOTION_TOKEN}", "Notion-Version": "2022-06-28", "Content-Type": "application/json"}
            
            # Filtro: Fecha Recordatorio dentro del rango OR Fecha Tarea dentro del rango
            # Simplificado: Usaremos Fecha Recordatorio para agenda diaria
            query_payload = {
                "filter": {
                    "and": [
                        {
                            "property": "Fecha de Recordatorio",
                            "date": {"on_or_after": start_day.isoformat()}
                        },
                        {
                            "property": "Fecha de Recordatorio",
                            "date": {"on_or_before": end_day.isoformat()}
                        }
                    ]
                },
                "sorts": [{"property": "Fecha de Recordatorio", "direction": "ascending"}]
            }
            
            try:
                data = requests.post(url_query, headers=headers, json=query_payload).json()
                results = data.get("results", [])
                
                if results:
                    msg_response = f"📅 *Agenda para {dia_str}*:\n\n"
                    for res in results:
                        props = res.get("properties", {})
                        title = props.get("Nombre", {}).get("title", [])
                        title_text = title[0].get("text", {}).get("content", "Sin nombre") if title else "Sin nombre"
                        
                        # Hora
                        date_prop = props.get("Fecha de Recordatorio", {}).get("date", {})
                        start_date_str = date_prop.get("start")
                        hora_txt = ""
                        if start_date_str and "T" in start_date_str: # Tiene hora
                             dt_obj = dateparser.parse(start_date_str)
                             hora_txt = f"[{dt_obj.strftime('%I:%M %p')}] "
                        
                        status = props.get("Estado", {}).get("status", {}).get("name", "")
                        check = "✅" if status == "Listo" else "⬜"
                        
                        msg_response += f"{check} {hora_txt}{title_text}\n"
                else:
                    msg_response = f"📅 *Agenda para {dia_str}*:\n\nNada programado. ¡Día libre! 🎉"
            
            except Exception as e:
                msg_response = f"⚠️ Error consultando Agenda: {str(e)}"

        # 3. CREAR TAREA (Default)
        else:
            # Asumimos que es un comando para crear tarea
            # Llamamos al helper compartido
            result, code = create_task_logic(text)
            
            if code == 200:
                created_title = result.get("titulo_principal", "Tarea")
                is_soon = result.get("smart_schedule", {}).get("is_soon", False)
                msg_voz = result.get("smart_schedule", {}).get("msg", "")
                
                msg_response = f"✅ *Agendado*: {created_title}"
                if is_soon:
                    msg_response += f"\n\n🔔 {msg_voz}"
            else:
                 msg_response = f"❌ Error creando tarea: {result.get('error', 'Desconocido')}"

        # ENVIAR RESPUESTA FINAL
        tg_url_send = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        requests.post(tg_url_send, json={
            "chat_id": chat_id,
            "text": msg_response,
            "parse_mode": "Markdown"
        })

    return "OK", 200

if __name__ == "__main__":
    app.run(debug=True)
