
import requests
import json

url = "http://127.0.0.1:5000/debug"
data = {"comando": "Tarea mañana a las 10am"}

try:
    response = requests.post(url, json=data)
    print(f"Status Code: {response.status_code}")
    try:
        print(f"Response: {json.dumps(response.json(), indent=2)}")
    except:
        print(f"Response Content: {response.text}")
except Exception as e:
    print(f"Error: {e}")
