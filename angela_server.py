import os
import json
import datetime
import firebase_admin
from firebase_admin import credentials, firestore, storage
from fastapi import FastAPI, UploadFile, File, Form
from fastapi.middleware.cors import CORSMiddleware

# ================================
# Configuración Firebase con VAR EN RENDER
# ================================
firebase_key = os.getenv("FIREBASE_KEY")
if not firebase_key:
    raise Exception("FIREBASE_KEY no está configurada en Render")

cred_dict = json.loads(firebase_key)
cred = credentials.Certificate(cred_dict)

firebase_admin.initialize_app(cred, {
    "storageBucket": "angela-memoria.appspot.com"
})

db = firestore.client()
bucket = storage.bucket()

# ================================
# FastAPI
# ================================
app = FastAPI(title="Angela Memoria API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Guardar memoria
@app.post("/guardar_memoria")
def guardar_memoria_post(texto: str = Form(...), etiqueta: str = Form("general")):
    doc_ref = db.collection("Memoria").document()
    doc_ref.set({
        "texto": texto,
        "etiqueta": etiqueta,
        "fecha": datetime.datetime.now()
    })
    return {"mensaje": f"Memoria guardada: {texto}"}

# Guardar estado
@app.post("/guardar_estado")
def guardar_estado_post(estado: str = Form(...)):
    doc_ref = db.collection("Estados").document()
    doc_ref.set({
        "estado": estado,
        "fecha": datetime.datetime.now()
    })
    return {"mensaje": f"Estado guardado: {estado}"}

# Subir archivo
@app.post("/subir_archivo")
async def subir_archivo_post(file: UploadFile = File(...)):
    blob = bucket.blob(file.filename)
    blob.upload_from_file(file.file)
    blob.make_public()

    doc_ref = db.collection("Archivos").document()
    doc_ref.set({
        "nombre": file.filename,
        "tipo": file.content_type,
        "url": blob.public_url,
        "fecha": datetime.datetime.now()
    })

    return {"mensaje": f"Archivo subido: {file.filename}", "url": blob.public_url}
