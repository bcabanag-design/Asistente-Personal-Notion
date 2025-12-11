import os
import json
from notion_client import Client
from dotenv import load_dotenv

load_dotenv()
NOTION_TOKEN = os.getenv("NOTION_TOKEN")
DATABASE_ID = os.getenv("DATABASE_ID")

client = Client(auth=NOTION_TOKEN)

print(f"Inspecting Database ID: {DATABASE_ID}")

try:
    db = client.databases.retrieve(DATABASE_ID)
    print("Database retrieve successful.")
    
    props = db.get("properties", {})
    if not props:
        print("WARNING: 'properties' is empty.")
    
    print("\nAvailable Properties:")
    for name, data in props.items():
        print(f"['{name}'] -> Type: {data['type']}")
        
except Exception as e:
    print(f"Error retrieving database: {e}")
