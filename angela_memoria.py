# angela_memoria.py
import os
import json
import datetime

import firebase_admin
from firebase_admin import credentials, firestore, storage

def _init_if_needed():
    if firebase_admin._apps:
        return

    key_json = os.getenv("FIREBASE_KEY_JSON")
    if not key_json:
        raise RuntimeError("FIREBASE_KEY_JSON no configurada.")

    key_dict = json.loads(key_json)
    project_id = key_dict.get("project_id")
    inferred_bucket = f"{project_id}.appspot.com" if project_id else None
    bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET") or inferred_bucket
    if not bucket_name:
        raise RuntimeError("No se pudo determinar FIREBASE_STORAGE_BUCKET.")

    cred = credentials.Certificate(key_dict)
    firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})


def _clients():
    _init_if_needed()
    return firestore.client(), storage.bucket()


def guardar_memoria(texto, etiqueta="general"):
    db, _ = _clients()
    doc_ref = db.collection("Memoria").document()
    doc_ref.set({
        "texto": texto,
        "etiqueta": etiqueta,
        "fecha": datetime.datetime.utcnow()
    })
    return f"Memoria guardada: {texto}"


def guardar_estado(estado):
    db, _ = _clients()
    doc_ref = db.collection("Estados").document()
    doc_ref.set({
        "estado": estado,
        "fecha": datetime.datetime.utcnow()
    })
    return f"Estado guardado: {estado}"


def subir_archivo(nombre_local, nombre_destino=None, tipo="desconocido"):
    _, bucket = _clients()

    if not nombre_destino:
        nombre_destino = nombre_local

    blob = bucket.blob(nombre_destino)
    blob.upload_from_filename(nombre_local)
    blob.make_public()

    db, _ = _clients()
    doc_ref = db.collection("Archivos").document()
    doc_ref.set({
        "nombre": nombre_destino,
        "tipo": tipo,
        "url": blob.public_url,
        "fecha": datetime.datetime.utcnow()
    })

    return f"Archivo subido: {nombre_destino}\nURL pública: {blob.public_url}"
