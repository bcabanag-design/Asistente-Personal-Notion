
import requests

url = "http://127.0.0.1:5000/debug"

def test(comando):
    print(f"Testing: {comando}")
    try:
        response = requests.post(url, json={"comando": comando})
        if response.status_code == 200:
            data = response.json().get('payload_generado', {})
            date_field = data.get('Fecha/Hora de Tarea')
            if date_field:
                print(f"  -> SUCCESS. Date found: {date_field['date']['start']}")
            else:
                print("  -> FAILURE. No date parsed.")
        else:
            print(f"  -> ERROR {response.status_code}: {response.text}")
    except Exception as e:
        print(f"  -> EXCEPTION: {e}")

test("hoy")
test("mañana")
