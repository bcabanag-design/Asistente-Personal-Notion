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
    
    # Logic to set timedelta object based on the extracted string
    if recordatorio_base == '1 día antes':
        regla_timedelta = timedelta(days=1)
    elif recordatorio_base == '1 hora antes':
        regla_timedelta = timedelta(hours=1)

    # Limpieza final del título
    # Remover conectores residuales al inicio
    tarea_titulo = re.sub(r'^(avisar\s+|avisa\s+|avisame\s+|avísame\s+|recuerda\s+|recuérdame\s+|recuerdame\s+|que\s+|para\s+|tengo\s+que\s+)', '', tarea_titulo, flags=re.IGNORECASE)
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
    elif comando_regla and (match := re.search(r'en\s+(.+?)\s+(horas?|hr?s?|minutos?|mins?)', comando_regla, re.IGNORECASE)):
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
    }

    properties = {k: v for k, v in properties.items() if v is not None}

    # Meta datos para lógica de scheduling
    meta_data = {
        "reminder_dt": fecha_recordatorio_dt
    }

    return properties, meta_data

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

        properties_payload, meta_data = process_command(comando)

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
            result_json = {"mensaje": "Tarea agendada con éxito", "data": properties_payload}
            
            # --- SMART SCHEDULING LOGIC ---
            # Si el recordatorio es pronto (menos de 65 mins), le decimos a Tasker que espere
            reminder_dt = meta_data.get("reminder_dt")
            if reminder_dt:
                import pytz
                tz = pytz.timezone(TIMEZONE)
                now = datetime.now(tz)
                
                # Asegurar que ambos sean comparables (aware)
                if reminder_dt.tzinfo is None:
                    reminder_dt = tz.localize(reminder_dt)
                
                diff = (reminder_dt - now).total_seconds()
                
                # Si falta entre 1 segundo y 65 minutos (3900 segs)
                if 0 < diff < 3900:
                    diff_int = int(diff)
                    if diff_int >= 60:
                        minutos = diff_int // 60
                        seg_rest = diff_int % 60
                        # Round up if close
                        if seg_rest > 30: minutos += 1
                        msg_voz = f"Listo. Te aviso en {minutos} minutos."
                    else:
                        msg_voz = f"Listo. Te aviso en {diff_int} segundos."

                    result_json["smart_schedule"] = {
                        "wait_seconds": diff_int,
                        "is_soon": True,
                        "msg": msg_voz
                    }
            
            return jsonify(result_json), 200
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

    import requests
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
            
            # Teclado Inline (Botón)
            reply_markup = {
                "inline_keyboard": [[
                    {"text": "✅ Hecho / Terminar", "callback_data": f"done_{page_id}"}
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
            
            import requests
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

    return "OK", 200

if __name__ == "__main__":
    app.run(debug=True)
