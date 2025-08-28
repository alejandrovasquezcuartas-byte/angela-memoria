import requests

API_URL = "http://localhost:8000"

print("🤖 Cliente Angela conectado...")

# Probar guardar memoria
resp = requests.post(f"{API_URL}/guardar_memoria", data={"texto": "Angela recuerda mi primera prueba", "etiqueta": "demo"})
print("📌 Respuesta memoria:", resp.json())

# Probar guardar estado
resp = requests.post(f"{API_URL}/guardar_estado", data={"estado": "Activo"})
print("📌 Respuesta estado:", resp.json())

# Probar subir archivo
with open("ejemplo.xlsx", "rb") as f:
    resp = requests.post(f"{API_URL}/subir_archivo", files={"file": f})
print("📌 Respuesta archivo:", resp.json())
