import requests

url = "http://127.0.0.1:5000/agendar"
data = {"comando": "Probar integración con Notion"}

try:
    response = requests.post(url, json=data)
    print(f"Status Code: {response.status_code}")
    print(f"Response: {response.json()}")
except requests.exceptions.ConnectionError:
    print("Error: No se pudo conectar al servidor. Asegúrate de que apag_asistente.py esté ejecutándose.")
