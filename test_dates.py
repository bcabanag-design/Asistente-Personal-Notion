import requests
import json

tests = [
    'Test # mañana a las 10am',
    'Test # pasado mañana',
    'Test # el viernes a las 3pm',
    'Test # 15 de diciembre',
    'Test # hoy',
    'Test sin fecha'
]

print("🔍 Probando diferentes formatos de fecha...")
print("-" * 60)

for t in tests:
    print(f"Comando: {t}")
    try:
        r = requests.post('https://asistente-personal-notion.onrender.com/debug', 
                          json={'comando': t}, timeout=60)
        data = r.json().get('payload_generado', {})
        fecha = data.get('Fecha/Hora de Tarea')
        if fecha:
            print(f"  ✅ Fecha detectada: {fecha['date']['start']}")
        else:
            print(f"  ❌ NO se detectó fecha")
    except Exception as e:
        print(f"  ERROR: {e}")
    print()
