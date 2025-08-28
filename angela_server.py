# angela_server.py
import os
import json
import datetime
import logging

from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, firestore, storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("angela_server")

app = FastAPI(title="Angela Memoria API", version="1.0.0")

# CORS abierto (ajusta dominios si quieres)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _init_firebase_once():
    """Inicializa Firebase solo una vez, usando variables de entorno."""
    if firebase_admin._apps:
        return

    key_json = os.getenv("FIREBASE_KEY_JSON")
    if not key_json:
        raise RuntimeError(
            "FIREBASE_KEY_JSON no está configurada. "
            "En Render, ve a Environment y crea esta variable con el JSON completo de la service account."
        )

    try:
        key_dict = json.loads(key_json)
    except Exception as e:
        raise RuntimeError("FIREBASE_KEY_JSON no contiene un JSON válido.") from e

    # Deducción del bucket por PROJECT_ID si no viene por variable
    project_id = key_dict.get("project_id")
    inferred_bucket = f"{project_id}.appspot.com" if project_id else None
    bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET") or inferred_bucket
    if not bucket_name:
        raise RuntimeError(
            "No se pudo determinar el bucket de Storage. "
            "Define FIREBASE_STORAGE_BUCKET o asegúrate de que el JSON tenga project_id."
        )

    cred = credentials.Certificate(key_dict)
    firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})
    logger.info(f"Firebase inicializado. Bucket: {bucket_name}")


def _get_clients():
    """Devuelve db y bucket ya listos (inicializando si hace falta)."""
    _init_firebase_once()
    db = firestore.client()
    bucket = storage.bucket()
    return db, bucket


@app.on_event("startup")
def on_startup():
    _init_firebase_once()


@app.get("/")
def root():
    return {"service": "Angela Memoria API", "status": "ok"}


@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.datetime.utcnow().isoformat()}


@app.post("/guardar_memoria")
def guardar_memoria_post(texto: str = Form(...), etiqueta: str = Form("general")):
    db, _ = _get_clients()
    doc_ref = db.collection("Memoria").document()
    doc_ref.set({
        "texto": texto,
        "etiqueta": etiqueta,
        "fecha": datetime.datetime.utcnow()
    })
    return {"mensaje": f"Memoria guardada: {texto}"}


@app.post("/guardar_estado")
def guardar_estado_post(estado: str = Form(...)):
    db, _ = _get_clients()
    doc_ref = db.collection("Estados").document()
    doc_ref.set({
        "estado": estado,
        "fecha": datetime.datetime.utcnow()
    })
    return {"mensaje": f"Estado guardado: {estado}"}


@app.post("/subir_archivo")
async def subir_archivo_post(file: UploadFile = File(...)):
    db, bucket = _get_clients()
    blob = bucket.blob(file.filename)
    blob.upload_from_file(file.file)
    blob.make_public()

    doc_ref = db.collection("Archivos").document()
    doc_ref.set({
        "nombre": file.filename,
        "tipo": file.content_type,
        "url": blob.public_url,
        "fecha": datetime.datetime.utcnow()
    })

    return {"mensaje": f"Archivo subido: {file.filename}", "url": blob.public_url}
