import requests
import json

tests = [
    # Con separador #
    'Comprar pan # mañana a las 10am',
    'Reunión importante # el viernes a las 3pm',
    
    # Sin separador (detección inteligente)
    'mañana a las 3 pm tengo que salir',
    'pasado mañana tengo cita con el doctor',
    'el viernes a las 4pm es la fiesta',
    'hoy a las 5pm llamar a mamá',
    '15 de diciembre es navidad',
    'tengo que estudiar mañana',
    
    # Sin fecha
    'recordar comprar leche',
]

print("🔍 Probando detección inteligente de fechas...")
print("-" * 60)

for t in tests:
    print(f"Comando: {t}")
    try:
        r = requests.post('https://asistente-personal-notion.onrender.com/debug', 
                          json={'comando': t}, timeout=60)
        data = r.json().get('payload_generado', {})
        titulo = data.get('Nombre', {}).get('title', [{}])[0].get('text', {}).get('content', 'N/A')
        fecha = data.get('Fecha/Hora de Tarea')
        print(f"  📝 Título: {titulo}")
        if fecha:
            print(f"  ✅ Fecha: {fecha['date']['start']}")
        else:
            print(f"  ❌ Sin fecha")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()
