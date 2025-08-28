# cliente_angela.py
import os
import requests

API_URL = os.getenv("ANGELA_API_URL", "http://127.0.0.1:8000")

print(f"🤖 Cliente Angela apuntando a: {API_URL}")

# Probar guardar memoria
resp = requests.post(f"{API_URL}/guardar_memoria",
                     data={"texto": "Angela recuerda mi primera prueba", "etiqueta": "demo"})
print("📌 Respuesta memoria:", resp.json())

# Probar guardar estado
resp = requests.post(f"{API_URL}/guardar_estado", data={"estado": "Activo"})
print("📌 Respuesta estado:", resp.json())

# Probar subir archivo (asegúrate de tener 'ejemplo.xlsx' en la misma carpeta)
try:
    with open("ejemplo.xlsx", "rb") as f:
        resp = requests.post(f"{API_URL}/subir_archivo", files={"file": f})
    print("📌 Respuesta archivo:", resp.json())
except FileNotFoundError:
    print("⚠️  No se encontró 'ejemplo.xlsx'. Omite esta prueba o coloca un archivo con ese nombre.")
