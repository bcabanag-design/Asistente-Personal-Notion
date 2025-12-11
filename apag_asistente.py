import os
import re
import json 
from datetime import datetime, timezone

from dotenv import load_dotenv
from flask import Flask, request, jsonify
from notion_client import Client
import dateparser

# --- 1. CONFIGURACIÓN INICIAL Y CLIENTES ---
load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")

if not NOTION_TOKEN or not DATABASE_ID:
    print("ERROR: NOTION_TOKEN o DATABASE_ID no encontrados en el archivo .env.")
    exit(1)

notion = Client(auth=NOTION_TOKEN)

app = Flask(__name__)

# --- 2. FUNCIONES CENTRALES DEL ASISTENTE ---

def obtener_propiedades_por_comando(comando_texto: str) -> dict:
    """
    Procesa el texto del comando para extraer Nombre, Fecha y Prioridad.
    """
    
    fecha_limite = dateparser.parse(comando_texto, settings={'PREFER_DATES_FROM': 'future'})
    
    # Prioridades con mayúscula inicial (Alta, Media, Baja) para las opciones de Select
    prioridad = "Media" 
    comando_lower = comando_texto.lower()
    if 'urgente' in comando_lower or 'ahora' in comando_lower or 'inmediato' in comando_lower:
        prioridad = "Alta"
    elif 'cuando tenga tiempo' in comando_lower or 'luego' in comando_lower:
        prioridad = "Baja"
    
    nombre_tarea = comando_texto 

    fecha_notion = {"start": fecha_limite.isoformat()} if fecha_limite else None
    
    # CLAVE FINAL: Usamos "Fecha" para coincidir con tu BD.
    return {
        "Nombre": nombre_tarea,
        "Fecha": fecha_notion, 
        "Prioridad": prioridad, 
    }


def crear_tarea_en_notion(nombre: str, fecha_limite: dict, prioridad: str):
    """Inserta una nueva página (tarea) en la base de datos principal."""
    
    propiedades = {
        "Nombre": {"title": [{"text": {"content": nombre}}]},
        "Prioridad": {"select": {"name": prioridad}},
        # Usamos el tipo "Status" (compatible con "Sin empezar")
        "Estado": {"status": {"name": "Sin empezar"}}, 
    }
    
    if fecha_limite:
        # CLAVE FINAL: Usamos "Fecha" para la columna Date.
        propiedades["Fecha"] = {"date": fecha_limite} 

    try:
        notion.pages.create(
            parent={"database_id": DATABASE_ID},
            properties=propiedades
        )
        return True
    except Exception as e:
        print(f"Error al crear tarea en Notion: {e}") 
        return False


# --- 3. ENDPOINT DE LA API (WEBHOOK) ---

@app.route('/agendar', methods=['POST'])
def agendar_tarea():
    """
    Recibe el comando de voz/texto desde el móvil o PC a través de un POST.
    """
    try:
        data_raw = request.data
        
        # Solución de codificación
        try:
            data_str = data_raw.decode('windows-1252')
        except UnicodeDecodeError:
            data_str = data_raw.decode('utf-8')
        
        data = json.loads(data_str)
        
    except Exception as e:
        return jsonify({"status": "error", "mensaje": f"Fallo al procesar JSON o codificación: {e}"}), 400

    comando = data.get('comando', '').strip()
    
    if not comando:
        return jsonify({"status": "error", "mensaje": "Comando vacío."}), 400
    
    try:
        datos_extraidos = obtener_propiedades_por_comando(comando) 
        
        exito = crear_tarea_en_notion(
            nombre=datos_extraidos['Nombre'],
            fecha_limite=datos_extraidos['Fecha'], # Usamos "Fecha"
            prioridad=datos_extraidos['Prioridad']
        )
        
        if exito:
            return jsonify({
                "status": "éxito", 
                "mensaje": f"Tarea '{datos_extraidos['Nombre']}' agendada con éxito.",
                "prioridad": datos_extraidos['Prioridad']
            }), 200
        else:
            return jsonify({"status": "error", "mensaje": "Fallo al insertar en Notion."}), 500

    except Exception as e:
        return jsonify({"status": "error", "mensaje": f"Error interno del asistente: {e}"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', debug=True)