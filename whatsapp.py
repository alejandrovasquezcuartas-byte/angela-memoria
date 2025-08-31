# whatsapp.py
import os, requests

WA_TOKEN = os.getenv("WHATSAPP_TOKEN")
WA_PHONE_ID = os.getenv("WHATSAPP_PHONE_ID")

def _post(payload: dict):
    url = f"https://graph.facebook.com/v20.0/{WA_PHONE_ID}/messages"
    headers = {"Authorization": f"Bearer {WA_TOKEN}", "Content-Type": "application/json"}
    r = requests.post(url, json=payload, headers=headers, timeout=20)
    print("WA ->", r.status_code, r.text[:400])
    r.raise_for_status()
    return r.json()

def send_template(to: str, order_id: int, customer_name: str, total_str: str,
                  template_name: str = "pedido_confirmado", language: str = "es_CO"):
    """Envía la plantilla para abrir ventana 24h."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,  # 57XXXXXXXXXX (sin '+')
        "type": "template",
        "template": {
            "name": template_name,
            "language": {"code": language},  # usa el MISMO código con el que creaste la plantilla (es/es_CO/es_ES)
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
    return _post(payload)

def send_text(to: str, body: str):
    """Envía tu mensaje interno con el layout de la empresa."""
    payload = {
        "messaging_product": "whatsapp",
        "to": to,
        "type": "text",
        "text": {"preview_url": False, "body": body}
    }
    return _post(payload)

def format_internal_message(order: dict) -> str:
    """Arma el texto con el formato que usas en la empresa."""
    b = order.get("billing", {})
    items = order.get("line_items", []) or []
    name = f'{b.get("first_name","")} {b.get("last_name","")}'.strip()
    city = b.get("city","")
    address = b.get("address_1","")
    email = b.get("email","")
    phone = b.get("phone","")
    doc   = b.get("document","") or b.get("dni","") or ""

    lines = []
    lines.append(f"Pedido {order.get('id')}")
    if name:    lines.append(name)
    if address: lines.append(address)
    if city:    lines.append(city)
    lines.append("")
    if email:
        lines.append("Dirección de correo electrónico:")
        lines.append(email)
        lines.append("")
    if phone:
        lines.append("Teléfono:")
        lines.append(phone)
        lines.append("")
    if doc:
        lines.append("Cédula de Ciudadanía:")
        lines.append(doc)
        lines.append("")

    # Productos
    for it in items:
        qty  = it.get("quantity", 1)
        title = it.get("name", "")
        lines.append(f"{qty} x {title}")
    lines.append("")

    total = order.get("total", "0")
    pm    = order.get("payment_method", "")
    lines.append(str(total))
    if pm:
        lines.append(pm + " - web")

    return "\n".join(lines)
