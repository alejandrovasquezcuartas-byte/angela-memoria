# angela_server.py
import os
import json
import csv
import datetime
import logging
import tempfile
from typing import Optional, List, Dict, Any

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Query, Body
from fastapi.middleware.cors import CORSMiddleware

import requests
import firebase_admin
from firebase_admin import credentials, firestore, storage

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("angela_server")

app = FastAPI(title="Angela Memoria API", version="1.4.0")

# -----------------------------
# CORS
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
    try:
        if len(s) == 10:
            dt = datetime.datetime.strptime(s, "%Y-%m-%d")
            if end_of_day:
                dt = dt + datetime.timedelta(hours=23, minutes=59, seconds=59)
            return dt
        return datetime.datetime.fromisoformat(s.replace("Z", "+00:00")).replace(tzinfo=None)
    except Exception:
        raise HTTPException(status_code=400, detail=f"Fecha inválida: {s}")

def _fmt_currency(amount: float) -> str:
    # COP estilo "86.010" (separador de miles con punto, sin decimales)
    try:
        return f"{round(amount):,}".replace(",", ".")
    except Exception:
        return str(amount)

def _get_meta_value(meta_list: List[Dict[str, Any]], keys: List[str]) -> Optional[str]:
    # Busca en meta_data de Woo keys típicas para cédula/nota u otros
    keyset = set([k.lower() for k in keys])
    for m in meta_list or []:
        k = str(m.get("key") or "").lower()
        if k in keyset:
            val = m.get("value")
            if isinstance(val, dict):
                # algunos plugins guardan diccionarios
                for vv in val.values():
                    if vv:
                        return str(vv)
            if val:
                return str(val)
    return None

# -----------------------------
# WhatsApp (Cloud API)
# -----------------------------
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")
# Uno o varios destinatarios separados por coma. Ej: "57XXXXXXXXXX,57YYYYYYYYY"
WHATSAPP_NOTIFY_TO = os.getenv("WHATSAPP_NOTIFY_TO", "").strip()

# Envío de texto (sesión abierta)
def _send_whatsapp_message(text: str, to: Optional[str] = None) -> Optional[dict]:
    token = os.getenv("WHATSAPP_TOKEN")
    phone_id = os.getenv("WHATSAPP_PHONE_ID")
    destino = (to or "").strip() or None
    if not destino and WHATSAPP_NOTIFY_TO:
        destino = WHATSAPP_NOTIFY_TO.split(",")[0].strip()

    if not (token and phone_id and destino):
        logger.warning("WA texto: faltan token/phone_id/destino")
        return None
    try:
        url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": destino,
            "type": "text",
            "text": {"body": text[:4096]},
        }
        r = requests.post(url, headers=headers, json=payload, timeout=20)
        if r.status_code >= 400:
            logger.warning(f"WhatsApp API {r.status_code}: {r.text[:500]}")
        return r.json()
    except Exception as e:
        logger.warning(f"No se pudo enviar WhatsApp: {e}")
        return None

def _send_whatsapp_to_all(text: str):
    if not (WHATSAPP_TOKEN and WHATSAPP_PHONE_ID and WHATSAPP_NOTIFY_TO):
        return []
    results = []
    for raw in WHATSAPP_NOTIFY_TO.split(","):
        num = raw.strip()
        if num:
            results.append(_send_whatsapp_message(text, num))
    return results

# Envío de plantilla (opcional)
WA_USE_TEMPLATE   = os.getenv("WA_USE_TEMPLATE", "0")  # "1" para activar
WA_TEMPLATE_NAME  = os.getenv("WA_TEMPLATE_NAME", "").strip()  # p.ej. "pedido_resumen"
WA_TEMPLATE_LANG  = os.getenv("WA_TEMPLATE_LANG", "es_CO").strip()  # p.ej. "es_CO"

def _send_whatsapp_template(to: str, order_id: str, customer_name: str, total_str: str) -> Optional[dict]:
    if not (WHATSAPP_TOKEN and WHATSAPP_PHONE_ID and to and WA_TEMPLATE_NAME):
        logger.warning("WA plantilla: faltan token/phone_id/destino/template_name")
        return None
    try:
        url = f"https://graph.facebook.com/v20.0/{WHATSAPP_PHONE_ID}/messages"
        headers = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": to,
            "type": "template",
            "template": {
                "name": WA_TEMPLATE_NAME,
                "language": {"code": WA_TEMPLATE_LANG},
                "components": [{
                    "type": "body",
                    "parameters": [
                        {"type": "text", "text": str(order_id)},
                        {"type": "text", "text": customer_name},
                        {"type": "text", "text": total_str},
                    ],
                }],
            },
        }
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        if r.status_code >= 400:
            logger.warning(f"WA plantilla {r.status_code}: {r.text[:500]}")
        return r.json()
    except Exception as e:
        logger.warning(f"No se pudo enviar WA plantilla: {e}")
        return None

# -----------------------------
# WooCommerce config
# -----------------------------
WOO_BASE_URL = os.getenv("WOO_BASE_URL")  # ej: https://yavalva.com.co/wp-json/wc/v3
WOO_CONSUMER_KEY = os.getenv("WOO_CONSUMER_KEY")
WOO_CONSUMER_SECRET = os.getenv("WOO_CONSUMER_SECRET")
WOO_UPDATE_ON_HOLD = os.getenv("WOO_UPDATE_ON_HOLD", "0")  # "1" para activar

# "1" = enviar el formato largo por WhatsApp (texto)
WA_SEND_FORMATTED = os.getenv("WA_SEND_FORMATTED", "1")

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
            logger.warning(f"Woo update status {resp.status_code}: {resp.text[:500]}")
        return resp.json()
    except Exception as e:
        logger.warning(f"No se pudo actualizar estado Woo: {e}")
        return None

# -----------------------------
# Formateo Yavalva para WhatsApp
# -----------------------------
def _extraer_cedula(payload: Dict[str, Any]) -> str:
    """Intenta obtener la cédula desde billing o meta_data (varias claves posibles)."""
    billing = payload.get("billing") or {}
    direct_keys = [
        "cedula", "dni", "document", "documento", "cc", "numero_documento", "nit",
        "billing_cc", "billing_cedula", "billing_dni", "billing_documento", "billing_document",
        "billing_nit", "shipping_cc", "shipping_cedula",
    ]
    for k in direct_keys:
        v = billing.get(k)
        if v:
            return str(v).strip()

    meta = payload.get("meta_data") or []
    meta_keys = [
        "cedula", "dni", "document", "documento", "cc", "numero_documento", "nit",
        "billing_cc", "billing_cedula", "billing_dni", "billing_documento", "billing_document",
        "billing_nit", "shipping_cc", "shipping_cedula",
    ]
    val = _get_meta_value(meta, [k.lower() for k in meta_keys])
    return str(val).strip() if val else ""

def _get_order_note(payload: Dict[str, Any]) -> str:
    """Obtiene la nota escrita por el cliente en el pedido."""
    note = (payload.get("customer_note") or "").strip()
    if note:
        return note
    meta = payload.get("meta_data") or []
    val = _get_meta_value(meta, [
        "customer_note", "order_note", "order_comments", "order_comment", "nota", "notes"
    ])
    return str(val).strip() if val else ""

def _fmt_yavalva_whatsapp(payload: Dict[str, Any]) -> str:
    number = str(payload.get("number") or payload.get("id") or "")
    billing = payload.get("billing") or {}
    shipping = payload.get("shipping") or {}

    customer_name = f"{billing.get('first_name','')} {billing.get('last_name','')}".strip() or billing.get("company","")

    addr1 = shipping.get("address_1") or billing.get("address_1") or ""
    addr2 = shipping.get("address_2") or billing.get("address_2") or ""
    city  = shipping.get("city")      or billing.get("city")      or ""
    state = shipping.get("state")     or billing.get("state")     or ""

    email = (billing.get("email") or "").strip()
    phone = (billing.get("phone") or "").replace(" ", "").replace("+", "")  # limpiar para WA
    cedula = _extraer_cedula(payload)
    order_note = _get_order_note(payload)

    # Items
    lines = []
    for it in (payload.get("line_items") or []):
        qty = int(it.get("quantity") or 1)
        sku_or_name = it.get("sku") or it.get("name") or ""
        lines.append(f"{qty} {sku_or_name}")

    # Envío
    if payload.get("shipping_lines"):
        lines.append("1 envío")

    # Total
    total_raw = payload.get("total") or "0"
    try:
        total = float(total_raw)
    except Exception:
        total = float(str(total_raw).replace(".", "").replace(",", "."))
    total_str = _fmt_currency(total)

    pay_title = payload.get("payment_method_title") or payload.get("payment_method") or ""
    pay_line = f"{pay_title} - web".strip()

    parts: List[str] = []
    parts.append(f"Pedido {number}")
    if customer_name: parts.append(customer_name)
    if addr1: parts.append(addr1)
    if addr2: parts.append(addr2)
    if city:  parts.append(city)
    if state: parts.append(state)
    parts.append("")  # línea en blanco

    parts.append("Dirección de correo electrónico:")
    parts.append(email)
    parts.append("")

    parts.append("Teléfono:")
    parts.append(phone)
    parts.append("")

    parts.append("Cédula de Ciudadanía:")
    parts.append(cedula or "")
    parts.append("")

    if lines:
        parts.extend(lines)
        parts.append("")

    # Nota del pedido (si existe)
    if order_note:
        parts.append("Nota del pedido:")
        parts.append(order_note)
        parts.append("")

    parts.append(total_str)
    parts.append(pay_line)

    return "\n".join(parts).strip()

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
# Webhook Woo + guardado + WhatsApp
# -----------------------------
@app.post(
    "/webhook/woocommerce",
    summary="Webhook Woocommerce",
    description=(
        "Recibe JSON de WooCommerce (pedido) y lo guarda en Firestore. "
        "Opcional: cambia estado a on-hold (WOO_UPDATE_ON_HOLD=1) y envía texto o plantilla a WhatsApp."
    ),
)
async def webhook_woocommerce(
    payload: Dict[str, Any] = Body(..., description="Payload crudo del pedido de WooCommerce")
):
    db, _ = _db_bucket()

    # Campos básicos
    try:
        order_id = int(payload.get("id") or payload.get("order_id") or 0)
    except Exception:
        order_id = 0
    number = str(payload.get("number") or (order_id if order_id else "")) or "N/A"
    status = payload.get("status") or "pending"
    currency = payload.get("currency") or "COP"
    try:
        total = float(str(payload.get("total") or "0").replace(",", ".").replace(" ", ""))
    except Exception:
        total = 0.0

    billing = payload.get("billing") or {}
    shipping = payload.get("shipping") or {}
    customer_name = f"{billing.get('first_name','')} {billing.get('last_name','')}".strip() or billing.get("company") or "N/A"

    line_items = payload.get("line_items") or []
    items: List[Dict[str, Any]] = []
    for it in line_items:
        def _to_float(x: Any) -> float:
            try:
                return float(str(x).replace(",", "."))
            except Exception:
                return 0.0
        items.append({
            "name": it.get("name"),
            "sku": it.get("sku"),
            "product_id": it.get("product_id"),
            "quantity": it.get("quantity"),
            "price": _to_float(it.get("price")),
            "subtotal": _to_float(it.get("subtotal")),
            "total": _to_float(it.get("total")),
        })

    created_raw = payload.get("date_created") or payload.get("date_created_gmt")
    try:
        created_at = (
            datetime.datetime.fromisoformat(created_raw.replace("Z", "+00:00")).replace(tzinfo=None)
            if created_raw else datetime.datetime.utcnow()
        )
    except Exception:
        created_at = datetime.datetime.utcnow()

    # Texto formateado para WhatsApp (estilo Yavalva)
    wa_text = _fmt_yavalva_whatsapp(payload)

    # Documento a guardar
    doc = {
        "order_id": order_id,
        "order_number": number,
        "status": status,
        "currency": currency,
        "total": total,
        "customer": {
            "name": customer_name,
            "phone": billing.get("phone"),
            "email": billing.get("email"),
            "billing": billing,
            "shipping": shipping,
        },
        "items": items,
        "raw": payload,
        "wa_text": wa_text,
        "source": "woocommerce",
        "created_at": created_at,
        "ingested_at": datetime.datetime.utcnow(),
    }

    doc_id = str(order_id) if order_id else firestore.AUTO_ID
    db.collection("Pedidos").document(doc_id).set(doc)

    # Opcional: actualizar estado a on-hold
    updated = None
    if WOO_UPDATE_ON_HOLD == "1" and order_id:
        updated = _update_woocommerce_status(order_id, "on-hold")

    # Envío WhatsApp
    wa_resp = []
    if WA_USE_TEMPLATE == "1" and WA_TEMPLATE_NAME:
        total_str = _fmt_currency(total)
        for raw in (WHATSAPP_NOTIFY_TO or "").split(","):
            num = raw.strip()
            if num:
                resp = _send_whatsapp_template(num, number, customer_name, total_str)
                if resp:
                    wa_resp.append(resp)

    elif WA_SEND_FORMATTED == "1":
        wa_resp = _send_whatsapp_to_all(wa_text) or []

    return {
        "ok": True,
        "saved_doc": doc_id,
        "whatsapp_sent": bool(wa_resp),
        "woo_status_updated": bool(updated),
    }

# -----------------------------
# Texto WhatsApp para copiar/pegar
# -----------------------------
@app.get("/pedido/{order_number}/whatsapp_text")
def whatsapp_text(order_number: str):
    """Devuelve el texto formateado (Yavalva) de un pedido para copiar/pegar."""
    db, _ = _db_bucket()
    # primero intenta por doc id
    doc_ref = db.collection("Pedidos").document(order_number).get()
    if doc_ref.exists:
        data = doc_ref.to_dict()
        return {"order_number": order_number, "text": data.get("wa_text", "")}

    # si no existe, busca por campo order_number
    docs = list(db.collection("Pedidos").where("order_number", "==", order_number).limit(1).stream())
    if docs:
        data = docs[0].to_dict()
        return {"order_number": order_number, "text": data.get("wa_text", "")}
    raise HTTPException(status_code=404, detail="Pedido no encontrado")

@app.get("/pedidos/whatsapp_texts")
def whatsapp_texts(
    desde: str = Query(..., description="YYYY-MM-DD o ISO"),
    hasta: str = Query(..., description="YYYY-MM-DD o ISO"),
    limit: int = Query(10, ge=1, le=100),
):
    """Lista los textos formateados de pedidos en un rango (para copiar/pegar rápido)."""
    db, _ = _db_bucket()
    start_dt = _parse_iso_date(desde)
    end_dt = _parse_iso_date(hasta, end_of_day=True)
    q = db.collection("Pedidos").where("created_at", ">=", start_dt).where("created_at", "<=", end_dt).order_by("created_at")
    out = []
    for d in q.stream():
        data = d.to_dict()
        out.append({"order_number": data.get("order_number"), "text": data.get("wa_text", "")})
        if len(out) >= limit:
            break
    return {"desde": start_dt.isoformat(), "hasta": end_dt.isoformat(), "results": out}

# -----------------------------
# Reportes de ventas (CSV)
# -----------------------------
@app.get("/reportes/ventas")
def reportes_ventas(
    desde: str = Query(..., description="Fecha inicio (YYYY-MM-DD o ISO)"),
    hasta: str = Query(..., description="Fecha fin (YYYY-MM-DD o ISO)"),
    status: Optional[str] = Query(None, description="Filtrar por estado (opcional)"),
):
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
