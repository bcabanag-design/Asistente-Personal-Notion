
import os
import sys
from notion_client import Client
from notion_client.errors import APIResponseError
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")

print(f"Token: {NOTION_TOKEN[:10]}... (len={len(NOTION_TOKEN) if NOTION_TOKEN else 0})")
print(f"Database ID: {DATABASE_ID}")

if not NOTION_TOKEN or not DATABASE_ID:
    print("Error: NOTION_TOKEN or DATABASE_ID not found in .env")
    sys.exit(1)

client = Client(auth=NOTION_TOKEN)


def list_accessible_objects():
    print("\n--- Listando Objetos Accesibles (Search) ---")
    try:
        results = client.search().get("results")
        
        if not results:
            print("LA BÚSQUEDA NO DEVOLVIÓ NADA.")
            print("Esto confirma que la integración NO TIENE ACCESO a ninguna base de datos.")
            print("Posible solución: Eliminar la conexión en la página y volver a agregarla.")
            return False
            
        print(f"Se encontraron {len(results)} bases de datos accesibles:")
        found_target = False
        for db in results:
            db_id = db['id'].replace("-", "")
            title_list = db.get('title', [])
            title = title_list[0].get('plain_text', 'Sin título') if title_list else 'Sin título'
            print(f"- Nombre: '{title}' | ID: {db_id}")
            
            if db_id == DATABASE_ID.replace("-", ""):
                found_target = True
                print("  -> ¡ESTA ES LA BASE DE DATOS CORRECTA (POR ID)!")
                print(f"     Type: {db.get('object')}")
                print(f"     Archived: {db.get('archived')}")
                print(f"     URL: {db.get('url')}")
                print(f"     Parent: {db.get('parent')}")
                print(f"     Full Title Object: {db.get('title')}")
                
                if db.get('object') == 'page':
                    print("\n¡DETECTADO! El ID proporcionado es una PÁGINA, no una base de datos.")
                    print("Buscando base de datos hija dentro de la página...")
                    try:
                        children = client.blocks.children.list(db_id).get('results')
                        for block in children:
                            if block['type'] == 'child_database':
                                real_db_id = block['id']
                                real_db_title = block['child_database']['title']
                                print(f"\n¡ENCONTRADA BASE DE DATOS HIJA!")
                                print(f"Nombre: {real_db_title}")
                                print(f"REAL DATABASE ID: {real_db_id}")
                                print(f"Prepara tu .env con este ID.")
                                return True
                        print("No se encontró ninguna 'child_database' dentro de esta página.")
                    except Exception as e:
                        print(f"Error al buscar hijos: {e}")
                
                # Try retrieve again explicitly now that we know search sees it
                try:
                    print("     Intentando retrieve directo...")
                    direct = client.databases.retrieve(db['id'])
                    print("     Retrieve ÉXITO.")
                except Exception as e:
                    print(f"     Retrieve FALLÓ: {e}")
        
        if found_target:
             print("\n¡El ID coincide en la búsqueda!")
        else:
             print(f"\nADVERTENCIA: El ID {DATABASE_ID} no apareció en los primeros resultados de búsqueda.")
             print("Intentando acceso directo de todas formas...")

        # ALWAYS try to retrieve and show properties
        try:
            print("\n--- Verificando Esquema de la Base de Datos ---")
            db_obj = client.databases.retrieve(DATABASE_ID)
            print("Propiedades encontradas:")
            for prop_name, prop_data in db_obj.get("properties", {}).items():
                print(f" - {prop_name} ({prop_data['type']})")
        except Exception as e:
            print(f"No se pudieron leer las propiedades: {e}")

        return True

    except Exception as e:
        print(f"FALLO en la búsqueda: {e}")
        return False

def verify_create_permissions():
    print("\n--- Verificando Permisos de Escritura (Create Page con Propiedades) ---")
    try:
        # Test exact payload structure from the app
        new_page = client.pages.create(
            parent={"database_id": DATABASE_ID},
            properties={
                "Nombre": {"title": [{"text": {"content": "Prueba de Diagnóstico"}}]},
                "Prioridad": {"select": {"name": "Media"}}, 
                "Estado": {"status": {"name": "Sin empezar"}}, # CORRECCION: Usar 'status' en lugar de 'select'
                # "Fecha Límite": {"date": {"start": "2025-12-12"}}
            }
        )
        print("ÉXITO: Página de prueba creada correctamente.")
        print(f"ID de página: {new_page['id']}")
        return True
    except APIResponseError as e:
        print(f"FALLO al crear página: {e}")
        return False

if __name__ == "__main__":
    list_accessible_objects()
    verify_create_permissions()

