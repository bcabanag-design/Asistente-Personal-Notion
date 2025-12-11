import requests
import json

url = "http://127.0.0.1:5000/agendar"
payload = {"comando": "Tarea de prueba exitosa, prioridad media, para el viernes al mediodía"}
headers = {"Content-Type": "application/json"}

try:
    response = requests.post(url, json=payload, headers=headers)
    print(f"Status Code: {response.status_code}")
    print("Response JSON:")
    print(json.dumps(response.json(), indent=2))
except Exception as e:
    print(f"Error: {e}")
