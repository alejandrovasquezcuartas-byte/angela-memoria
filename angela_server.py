# angela_server.py
import os
import json
import datetime
import logging
import tempfile

from fastapi import FastAPI, UploadFile, File, Form, HTTPException
from fastapi.middleware.cors import CORSMiddleware

import firebase_admin
from firebase_admin import credentials, firestore, storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("angela_server")

app = FastAPI(title="Angela Memoria API", version="1.0.1")

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
        # Compatibilidad con tu código viejo, por si quedó en el entorno:
        key_json = os.getenv("FIREBASE_KEY")

    if not key_json:
        raise RuntimeError(
            "FIREBASE_KEY_JSON no está configurada. "
            "Ve a Environment y crea esta variable con el JSON completo de la service account."
        )

    try:
        key_dict = json.loads(key_json)
    except Exception as e:
        raise RuntimeError("FIREBASE_KEY_JSON no contiene un JSON válido.") from e

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
    db.collection("Memoria").document().set({
        "texto": texto,
        "etiqueta": etiqueta,
        "fecha": datetime.datetime.utcnow()
    })
    return {"mensaje": f"Memoria guardada: {texto}"}

@app.post("/guardar_estado")
def guardar_estado_post(estado: str = Form(...)):
    db, _ = _get_clients()
    db.collection("Estados").document().set({
        "estado": estado,
        "fecha": datetime.datetime.utcnow()
    })
    return {"mensaje": f"Estado guardado: {estado}"}

@app.post("/subir_archivo")
async def subir_archivo_post(file: UploadFile = File(...)):
    """
    Sube un archivo a Firebase Storage y registra metadatos en Firestore.
    Estrategia:
    1) upload_from_string (memoria)
    2) fallback -> archivo temporal + upload_from_filename
    """
    db, bucket = _get_clients()

    filename = file.filename or "archivo_sin_nombre"
    content_type = file.content_type or "application/octet-stream"
    blob = bucket.blob(filename)

    try:
        # 1) Intento directo desde memoria
        data = await file.read()
        if not data:
            raise ValueError("Archivo vacío")

        try:
            blob.upload_from_string(data, content_type=content_type)
            blob.make_public()
        except Exception as e1:
            logger.warning(f"Fallo upload_from_string ({type(e1).__name__}: {e1}). Probando fallback con archivo temporal…")
            # 2) Fallback: archivo temporal
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp.write(data)
                tmp.flush()
                temp_path = tmp.name
            try:
                blob.upload_from_filename(temp_path, content_type=content_type)
                blob.make_public()
            except Exception as e2:
                logger.exception(f"Error subiendo archivo a Storage (fallback): {type(e2).__name__}: {e2}")
                raise HTTPException(status_code=500, detail=f"upload_error: {type(e2).__name__}: {e2}")

        # Registrar en Firestore
        db.collection("Archivos").document().set({
            "nombre": filename,
            "tipo": content_type,
            "url": blob.public_url,
            "fecha": datetime.datetime.utcnow()
        })

        return {"mensaje": f"Archivo subido: {filename}", "url": blob.public_url}

    except HTTPException:
        raise
    except Exception as e:
        logger.exception(f"Error inesperado en /subir_archivo: {type(e).__name__}: {e}")
        raise HTTPException(status_code=500, detail=f"unexpected_error: {type(e).__name__}: {e}")
