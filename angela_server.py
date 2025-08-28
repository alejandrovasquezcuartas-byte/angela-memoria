# angela_server.py
import os
import json
import csv
import datetime
import logging
import tempfile
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request, Query
from fastapi.middleware.cors import CORSMiddleware

import requests
import firebase_admin
from firebase_admin import credentials, firestore, storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("angela_server")

app = FastAPI(title="Angela Memoria API", version="1.2.2")

# -----------------------------
# CORS (ajusta dominios si quieres)
# -----------------------------
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# -----------------------------
# Firebase bootstrapping
# -----------------------------
def _init_firebase_once():
    if firebase_admin._apps:
        return

    key_json = os.getenv("FIREBASE_KEY_JSON") or os.getenv("FIREBASE_KEY")
    if not key_json:
        raise RuntimeError("FIREBASE_KEY_JSON no está configurada en Environment.")

    try:
        key_dict = json.loads(key_json)
    except Exception as e:
        raise RuntimeError("FIREBASE_KEY_JSON no contiene JSON válido.") from e

    project_id = key_dict.get("project_id")
    inferred_bucket = f"{project_id}.firebasestorage.app" if project_id else None
    bucket_name = os.getenv("FIREBASE_STORAGE_BUCKET") or inferred_bucket
    if not bucket_name:
        raise RuntimeError("No se pudo determinar el bucket. Define FIREBASE_STORAGE_BUCKET.")

    cred = credentials.Certificate(key_dict)
    firebase_admin.initialize_app(cred, {"storageBucket": bucket_name})
    logger.info(f"Firebase inicializado. Bucket: {bucket_name}")

def _db_bucket():
    _init_firebase_once()
    return firestore.client(), storage.bucket()

@app.on_event("startup")
def on_startup():
    _init_firebase_once()

# -----------------------------
# Utilidades
# -----------------------------
def _upload_bytes_to_storage(path: str, data: bytes, content_type: str) -> str:
    _, bucket = _db_bucket()
    blob = bucket.blob(path)
    blob.upload_from_string(data, content_type=content_type)
    blob.make_public()
    return blob.public_url

def _upload_tempfile_to_storage(path: str, data: bytes, content_type: str) -> str:
    with tempfile.NamedTemporaryFile(delete=False) as tmp:
        tmp.write(data)
        tmp.flush()
        temp_path = tmp.name
    _, bucket = _db_bucket()
    blob = bucket.blob(path)
    blob.upload_from_filename(temp_path, content_type=content_type)
    blob.make_public()
    return blob.public_url

def _parse_iso_date(s: str, end_of_day: bool = False) -> datetime.datetime:
    # Acepta "YYYY-MM-DD" o ISO completo
    try:
        if len(s) == 10:  # YYYY-MM-DD
            dt = datetime.datetime.strptime(s, "%Y-%m-%d")
            if end_of_day:
                dt = dt + datetime.timedelta(hours=23, minutes=59, seconds=59)
            return dt
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Fecha inválida: {s}")

def _fmt_currency(amount: float) -> str:
    try:
        return f"${amount:,.0f}".replace(",", ".")
    except Exception:
        return str(amount)

# -----------------------------
# Endpoints base
# -----------------------------
@app.get("/")
def root():
    return {"service": "Angela Memoria API", "status": "ok"}

@app.get("/health")
def health():
    return {"ok": True, "ts": datetime.datetime.utcnow().isoformat()}

@app.post("/guardar_memoria")
def guardar_memoria_post(texto: str = Form(...), etiqueta: str = Form("general")):
    db, _ = _db_bucket()
    db.collection("Memoria").document().set({
        "texto": texto,
        "etiqueta": etiqueta,
        "fecha": datetime.datetime.utcnow()
    })
    return {"mensaje": f"Memoria guardada: {texto}"}

@app.post("/guardar_estado")
def guardar_estado_post(estado: str = Form(...)):
    db, _ = _db_bucket()
    db.collection("Estados").document().set({
        "estado": estado,
        "fecha": datetime.datetime.utcnow()
    })
    return {"mensaje": f"Estado guardado: {estado}"}

@app.post("/subir_archivo")
async def subir_archivo_post(file: UploadFile = File(...)):
    filename = file.filename or "archivo_sin_nombre"
    content_type = file.content_type or "application/octet-stream"
    data = await file.read()
    if not data:
        raise HTTPException(status_code=400, detail="Archivo vacío")
    try:
        url = _upload_bytes_to_storage(filename, data, content_type)
    except Exception as e1:
        logger.warning(f"upload_from_string falló ({type(e1).__name__}: {e1}); usando fallback tempfile…")
        try:
            url = _upload_tempfile_to_storage(filename, data, content_type)
        except Exception as e2:
            logger.exception(f"Error subiendo a Storage: {type(e2).__name__}: {e2}")
            raise HTTPException(status_code=500, detail=f"upload_error: {type(e2).__name__}: {e2}")

    db, _ = _db_bucket()
    db.collection("Archivos").document().set({
        "nombre": filename,
        "tipo": content_type,
        "url": url,
        "fecha": datetime.datetime.utcnow()
    })
    return {"mensaje": f"Archivo subido: {filename}", "url": url}

# -----------------------------
# WooCommerce Webhook + WhatsApp
# -----------------------------
WOO_BASE_URL = os.getenv("WOO_BASE_URL")  # ej: https://tu-dominio.com/wp-json/wc/v3
WOO_CONSUMER_KEY = os.getenv("WOO_CONSUMER_KEY")
WOO_CONSUMER_SECRET = os.getenv("WOO_CONSUMER_SECRET")
WOO_UPDATE_ON_HOLD = os.getenv("WOO_UPDATE_ON_HOLD", "0")  # "1" para activar

WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")             # token WA Cloud API (opcional)
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")       # ej: 123456789012345 (opcional)
WHATSAPP_NOTIFY_TO = os.getenv("WHATSAPP_NOTIFY_TO")     # número destino en formato internacional (opcional)

def _update_woocommerce_status(order_id: int, status: str = "on-hold") -> Optional[dict]:
    if not (WOO_BASE_URL and WOO_CONSUMER_KEY and WOO_CONSUMER_SECRET):
        return None
    try:
        url = f"{WOO_BASE_URL}/orders/{order_id}"
        resp = requests.put(
            url,
            params={"consumer_key": WOO_CONSUMER_KEY, "consumer_secret": WOO_CONSUMER_SECRET},
            json={"status": status},
            timeout=20
        )
        if resp.status_code >= 400:
            logger.warning(f"Woo update status {resp.status_code}: {resp.text}")
        return resp.json()
    except Exception as e:
        logger.warning(f"No se pudo actualizar estado Woo: {e}")
        return None

def _send_whatsapp_message(text: str) -> Optional[dict]:
    # Nota: WhatsApp Cloud API no envía a grupos; enviará a un número individual.
    if not (WHATSAPP_TOKEN and WHATSAPP_PHONE_ID and WHATSAPP_NOTIFY_TO):
        return None
    try:
        url = f"https://graph.facebook.com/v19.0/{WHATSAPP_PHONE_ID}/messages"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": WHATSAPP_NOTIFY_TO,
            "type": "text",
            "text": {"body": text[:4096]}
        }
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        if r.status_code >= 400:
            logger.warning(f"WhatsApp API {r.status_code}: {r.text}")
        return r.json()
    except Exception as e:
        logger.warning(f"No se pudo enviar WhatsApp: {e}")
        return None

@app.post("/webhook/woocommerce")
async def webhook_woocommerce(request: Request):
    """
    Recibe JSON de WooCommerce (pedido) y lo guarda en Firestore.
    Opcional:
      - Cambia estado del pedido a on-hold (WOO_UPDATE_ON_HOLD=1)
      - Envía resumen por WhatsApp (si se configuran variables)
    """
    db, _ = _db_bucket()
    payload = await request.json()

    # Campos básicos
    try:
        order_id = int(payload.get("id") or payload.get("order_id") or 0)
    except Exception:
        order_id = 0
    number = payload.get("number") or (str(order_id) if order_id else "N/A")
    status = payload.get("status") or "pending"
    currency = payload.get("currency") or "COP"
    total = float(payload.get("total") or 0.0)

    billing = payload.get("billing") or {}
    shipping = payload.get("shipping") or {}
    customer_name = f"{billing.get('first_name','')} {billing.get('last_name','')}".strip() or billing.get("company") or "N/A"
    customer_phone = billing.get("phone") or ""
    customer_email = billing.get("email") or ""

    line_items = payload.get("line_items") or []
    items: List[Dict[str, Any]] = []
    for it in line_items:
        items.append({
            "name": it.get("name"),
            "sku": it.get("sku"),
            "product_id": it.get("product_id"),
            "quantity": it.get("quantity"),
            "price": float(it.get("price") or 0.0),
            "subtotal": float(it.get("subtotal") or 0.0),
            "total": float(it.get("total") or 0.0),
        })

    # Fecha de creación del pedido
    created_raw = payload.get("date_created") or payload.get("date_created_gmt")
    try:
        created_at = (
            datetime.datetime.fromisoformat(created_raw.replace("Z", "+00:00")).replace(tzinfo=None)
            if created_raw else datetime.datetime.utcnow()
        )
    except Exception:
        created_at = datetime.datetime.utcnow()

    # Documento a guardar
    doc = {
        "order_id": order_id,
        "order_number": number,
        "status": status,
        "currency": currency,
        "total": total,
        "customer": {
            "name": customer_name,
            "phone": customer_phone,
            "email": customer_email,
            "billing": billing,
            "shipping": shipping,
        },
        "items": items,
        "raw": payload,
        "source": "woocommerce",
        "created_at": created_at,
        "ingested_at": datetime.datetime.utcnow(),
    }

    doc_id = str(order_id) if order_id else firestore.AUTO_ID
    db.collection("Pedidos").document(doc_id).set(doc)

    # Acciones opcionales
    updated = None
    if WOO_UPDATE_ON_HOLD == "1" and order_id:
        updated = _update_woocommerce_status(order_id, "on-hold")

    # Texto de WhatsApp (corregido sin escapes raros)
    items_str = ", ".join([f"{i.get('name','')} x{i.get('quantity')}" for i in items]) if items else "—"
    resumen = (
        f"🧾 Nuevo pedido WooCommerce #{number}\n"
        f"Cliente: {customer_name}\n"
        f"Total: {currency} {_fmt_currency(total)}\n"
        f"Items: {items_str}\n"
        f"Estado: {status}"
    )
    wa_resp = _send_whatsapp_message(resumen)

    return {
        "ok": True,
        "saved_doc": doc_id,
        "whatsapp": bool(wa_resp),
        "woo_status_updated": bool(updated),
    }

# -----------------------------
# Reportes de ventas (CSV)
# -----------------------------
@app.get("/reportes/ventas")
def reportes_ventas(
    desde: str = Query(..., description="Fecha inicio (YYYY-MM-DD o ISO)"),
    hasta: str = Query(..., description="Fecha fin (YYYY-MM-DD o ISO)"),
    status: Optional[str] = Query(None, description="Filtrar por estado (opcional)"),
):
    """Genera un CSV con resumen de ventas y devuelve métricas + URL de descarga."""
    db, _ = _db_bucket()
    start_dt = _parse_iso_date(desde)
    end_dt = _parse_iso_date(hasta, end_of_day=True)

    q = db.collection("Pedidos").where("created_at", ">=", start_dt).where("created_at", "<=", end_dt)
    if status:
        q = q.where("status", "==", status)

    docs = list(q.stream())
    total_orders = len(docs)
    total_amount = 0.0
    prod_count: Dict[str, int] = {}
    rows: List[List[Any]] = [["order_number", "fecha", "cliente", "estado", "total", "items"]]

    for d in docs:
        data = d.to_dict()
        total = float(data.get("total") or 0.0)
        total_amount += total
        items = data.get("items") or []
        item_str = "; ".join([f"{i.get('name','')} x{i.get('quantity')}" for i in items])
        for i in items:
            name = i.get("name") or "producto"
            prod_count[name] = prod_count.get(name, 0) + int(i.get("quantity") or 0)
        rows.append([
            data.get("order_number"),
            (data.get("created_at") or datetime.datetime.utcnow()).strftime("%Y-%m-%d %H:%M:%S"),
            (data.get("customer") or {}).get("name", ""),
            data.get("status", ""),
            total,
            item_str
        ])

    # CSV temporal y subida
    with tempfile.NamedTemporaryFile(mode="w", newline="", delete=False, encoding="utf-8") as tmp:
        writer = csv.writer(tmp)
        writer.writerows(rows)
        tmp.flush()
        tmp_path = tmp.name

    with open(tmp_path, "rb") as f:
        csv_bytes = f.read()

    timestamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    csv_name = f"reportes/ventas_{timestamp}.csv"
    url = _upload_bytes_to_storage(csv_name, csv_bytes, "text/csv")

    top = sorted(prod_count.items(), key=lambda x: x[1], reverse=True)[:10]

    return {
        "desde": start_dt.isoformat(),
        "hasta": end_dt.isoformat(),
        "total_orders": total_orders,
        "total_amount": total_amount,
        "top_products": [{"name": k, "qty": v} for k, v in top],
        "csv_url": url
    }
