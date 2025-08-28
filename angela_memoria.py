import firebase_admin
from firebase_admin import credentials, firestore, storage
from datetime import datetime

# 1. Cargar credenciales (ajusta el nombre de tu JSON si es distinto)
cred = credentials.Certificate("angela-memoria-firebase-adminsdk-fbsvc-16f8acfa18.json")
firebase_admin.initialize_app(cred, {
    "storageBucket": "angela-memoria.firebasestorage.app"
})

# 2. Inicializar Firestore y Storage
db = firestore.client()
bucket = storage.bucket()

# ======================================================
# FUNCIONES DE ANGELA
# ======================================================

# ---------- MEMORIA ----------
def guardar_memoria(origen, texto, etiquetas=None, categoria="tareas cotidianas", contexto=""):
    """Guarda una interacción en la colección 'Memoria'."""
    doc_ref = db.collection("Memoria").document()
    doc_ref.set({
        "timestamp": datetime.now(),
        "origen": origen,
        "texto": texto,
        "etiquetas": etiquetas or [],
        "categoria": categoria,
        "contexto": contexto
    })
    print(f"💾 Memoria guardada: {texto}")


def leer_memoria_por_etiqueta(etiqueta):
    """Lee interacciones que contengan una etiqueta específica."""
    resultados = db.collection("Memoria").where("etiquetas", "array_contains", etiqueta).stream()
    for doc in resultados:
        print(f"📌 {doc.id} => {doc.to_dict()}")


# ---------- ESTADOS / TAREAS ----------
def guardar_estado(tarea, fecha_limite, prioridad="media"):
    """Guarda un estado/tarea en la colección 'Estados'."""
    doc_ref = db.collection("Estados").document()
    doc_ref.set({
        "tarea": tarea,
        "fecha_limite": fecha_limite,
        "prioridad": prioridad,
        "timestamp": datetime.now(),
    })
    print(f"📌 Estado guardado: {tarea}")


# ---------- ARCHIVOS ----------
def subir_archivo(ruta_local, nombre_destino, tipo="archivo"):
    """Sube un archivo a Firebase Storage y lo registra en Firestore."""
    try:
        blob = bucket.blob(nombre_destino)
        blob.upload_from_filename(ruta_local)
        blob.make_public()  # URL accesible públicamente

        # Guardar metadatos en Firestore
        doc_ref = db.collection("Archivos").document()
        doc_ref.set({
            "nombre": nombre_destino,
            "tipo": tipo,
            "fecha": datetime.now(),
            "url": blob.public_url
        })

        print(f"📂 Archivo subido: {nombre_destino}")
        print(f"🌐 URL pública: {blob.public_url}")

    except Exception as e:
        print(f"❌ Error subiendo archivo: {e}")


# ======================================================
# MAIN (solo para pruebas iniciales, luego no hace falta)
# ======================================================
if __name__ == "__main__":
    # Guardar ejemplo en memoria
    guardar_memoria("usuario", "Hola Angela, probando memoria", etiquetas=["prueba", "setup"])

    # Guardar estado
    guardar_estado("Revisar inventario", "2025-08-30", prioridad="alta")

    # Subir archivo de ejemplo
    subir_archivo("ejemplo.xlsx", "ejemplo.xlsx", tipo="excel")
