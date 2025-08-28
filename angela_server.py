from fastapi import FastAPI, UploadFile, File, Form
from google.cloud import firestore, storage
from google.oauth2 import service_account
from datetime import datetime
import os

# -------------------------------
# CONFIGURACIÓN FIREBASE
# -------------------------------
credenciales = service_account.Credentials.from_service_account_file(
    "firebase_key.json"  # Asegúrate de que este archivo esté en tu carpeta
)

db = firestore.Client(credentials=credenciales, project=credenciales.project_id)
storage_client = storage.Client(credentials=credenciales, project=credenciales.project_id)

# Nombre de tu bucket
bucket_name = "angela-memoria.firebasestorage.app"
bucket = storage_client.bucket(bucket_name)

# -------------------------------
# CREAR API
# -------------------------------
app = FastAPI(title="Angela Memoria", description="API para guardar y consultar memorias, estados y archivos")


# -------------------------------
# ENDPOINTS DE MEMORIA
# -------------------------------
@app.post("/guardar_memoria")
def guardar_memoria(
    origen: str = Form(...),
    texto: str = Form(...),
    categoria: str = Form("general"),
    etiqueta: str = Form(None)
):
    """Guardar recuerdos en Firebase"""
    data = {
        "origen": origen,
        "texto": texto,
        "categoria": categoria,
        "etiquetas": [etiqueta] if etiqueta else [],
        "fecha": datetime.utcnow()
    }
    db.collection("Memoria").add(data)
    return {"mensaje": f"Memoria guardada: {texto}"}


@app.get("/consultar_memorias/{etiqueta}")
def consultar_memorias(etiqueta: str):
    """Consultar recuerdos por etiqueta"""
    docs = db.collection("Memoria").where("etiquetas", "array_contains", etiqueta).stream()
    resultados = []
    for doc in docs:
        resultados.append(doc.to_dict())
    return resultados


# -------------------------------
# ENDPOINTS DE ESTADOS
# -------------------------------
@app.post("/guardar_estado")
def guardar_estado(texto: str = Form(...)):
    """Guardar estados de Angela"""
    data = {
        "texto": texto,
        "fecha": datetime.utcnow()
    }
    db.collection("Estados").add(data)
    return {"mensaje": f"Estado guardado: {texto}"}


@app.get("/consultar_estados")
def consultar_estados():
    """Consultar estados guardados"""
    docs = db.collection("Estados").stream()
    resultados = [doc.to_dict() for doc in docs]
    return resultados


# -------------------------------
# ENDPOINTS DE ARCHIVOS
# -------------------------------
@app.post("/subir_archivo")
def subir_archivo(file: UploadFile = File(...)):
    """Subir archivos a Firebase Storage"""
    blob = bucket.blob(file.filename)
    blob.upload_from_file(file.file, content_type=file.content_type)
    blob.make_public()

    data = {
        "nombre": file.filename,
        "url": blob.public_url,
        "fecha": datetime.utcnow()
    }
    db.collection("Archivos").add(data)

    return {"mensaje": f"Archivo subido: {file.filename}", "url": blob.public_url}


@app.get("/listar_archivos")
def listar_archivos():
    """Listar todos los archivos subidos"""
    docs = db.collection("Archivos").stream()
    resultados = [doc.to_dict() for doc in docs]
    return resultados


# -------------------------------
# ROOT
# -------------------------------
@app.get("/")
def root():
    return {"mensaje": "Angela está lista para recordar, consultar y guardar archivos."}
