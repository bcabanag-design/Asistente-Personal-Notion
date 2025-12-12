import requests
import json

print("🔍 Probando conexión a Render...")
print("-" * 50)

# Test 1: Health check
try:
    r = requests.get('https://asistente-personal-notion.onrender.com/health', timeout=120)
    print(f"✅ /health - Status: {r.status_code}")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
except Exception as e:
    print(f"❌ /health falló: {e}")

print("-" * 50)

# Test 2: Debug endpoint
try:
    r = requests.post('https://asistente-personal-notion.onrender.com/debug', 
                      json={'comando': 'Prueba # mañana a las 10am'}, 
                      timeout=120)
    print(f"✅ /debug - Status: {r.status_code}")
    print(json.dumps(r.json(), indent=2, ensure_ascii=False))
except Exception as e:
    print(f"❌ /debug falló: {e}")

print("-" * 50)

# Test 3: Agendar endpoint
try:
    r = requests.post('https://asistente-personal-notion.onrender.com/agendar', 
                      json={'comando': 'Tarea de prueba # mañana a las 10am'}, 
                      timeout=120)
    print(f"📝 /agendar - Status: {r.status_code}")
    try:
        print(json.dumps(r.json(), indent=2, ensure_ascii=False))
    except:
        print(r.text)
except Exception as e:
    print(f"❌ /agendar falló: {e}")

print("-" * 50)
print("✅ Prueba completada")
