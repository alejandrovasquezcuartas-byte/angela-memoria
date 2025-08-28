import datetime
import firebase_admin
from firebase_admin import firestore, storage

# Clientes de Firebase
db = firestore.client()
bucket = storage.bucket()

def guardar_memoria(texto, etiqueta="general"):
    doc_ref = db.collection("Memoria").document()
    doc_ref.set({
        "texto": texto,
        "etiqueta": etiqueta,
        "fecha": datetime.datetime.now()
    })
    return f"Memoria guardada: {texto}"

def guardar_estado(estado):
    doc_ref = db.collection("Estados").document()
    doc_ref.set({
        "estado": estado,
        "fecha": datetime.datetime.now()
    })
    return f"Estado guardado: {estado}"

def subir_archivo(nombre_local, nombre_destino=None, tipo="desconocido"):
    if not nombre_destino:
        nombre_destino = nombre_local

    blob = bucket.blob(nombre_destino)
    blob.upload_from_filename(nombre_local)
    blob.make_public()

    doc_ref = db.collection("Archivos").document()
    doc_ref.set({
        "nombre": nombre_destino,
        "tipo": tipo,
        "url": blob.public_url,
        "fecha": datetime.datetime.now()
    })

    return f"Archivo subido: {nombre_destino}\nURL pública: {blob.public_url}"
