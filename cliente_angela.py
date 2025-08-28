import requests

BASE_URL = "http://127.0.0.1:8000"

def guardar_memoria():
    data = {
        "origen": "usuario",
        "texto": "Angela recuerda mi primera prueba",
        "categoria": "prueba",
        "etiquetas": ["demo"]
    }
    response = requests.post(f"{BASE_URL}/guardar_memoria", json=data)
    print("📝 Respuesta memoria:", response.json())

def consultar_memoria():
    etiqueta = "demo"
    response = requests.get(f"{BASE_URL}/consultar_memoria/{etiqueta}")
    print("🔎 Consulta memoria:", response.json())

def guardar_estado():
    data = {
        "estado": "Revisar inventario"
    }
    response = requests.post(f"{BASE_URL}/guardar_estado", json=data)
    print("📌 Respuesta estado:", response.json())

def consultar_estado():
    response = requests.get(f"{BASE_URL}/consultar_estado")
    print("📋 Consulta estado:", response.json())

def subir_archivo():
    file_path = "ejemplo.xlsx"  # Cambia aquí el archivo que quieras subir
    with open(file_path, "rb") as f:
        files = {"file": (file_path, f, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
        response = requests.post(f"{BASE_URL}/subir_archivo", files=files)
    print("📂 Respuesta archivo:", response.json())

def listar_archivos():
    response = requests.get(f"{BASE_URL}/listar_archivos")
    print("📁 Archivos guardados:", response.json())

if __name__ == "__main__":
    print("🤖 Cliente Angela conectado...\n")

    guardar_memoria()
    consultar_memoria()
    guardar_estado()
    consultar_estado()
    subir_archivo()
    listar_archivos()
