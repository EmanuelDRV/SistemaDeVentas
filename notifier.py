from datetime import date, timedelta
import os
import requests

# Importamos la app y modelos desde tu proyecto
from app import app, Subscription, render_message, build_wa_link

# === CONFIGURACIÓN DEL BOT TELEGRAM ===
# Ahora viene desde variables de entorno (GitHub Actions y Fly.io)
TELEGRAM_TOKEN = os.getenv("7636575849:AAGp-5XQuIev5OtcbFLrJzzipu3iuq0YFZs")
TELEGRAM_CHAT_ID = os.getenv("-1003331904641")

# Días antes para avisar vencimientos
DIAS_ANTICIPACION = 3


def send_telegram_message(text: str) -> bool:
    """Envía un mensaje a Telegram. Devuelve True si fue exitoso."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ERROR: Falta TELEGRAM_TOKEN o TELEGRAM_CHAT_ID")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
    }

    try:
        r = requests.post(url, json=payload, timeout=10)
        if not r.ok:
            print("Error Telegram:", r.text)
            return False
        return True
    except Exception as e:
        print("Excepción enviando Telegram:", e)
        return False


def build_expiring_section(subs, today: date):
    """Construye el texto de suscripciones por vencer."""
    if not subs:
        return None

    lines = []
    lines.append(
        f"⚠️ <b>SUSCRIPCIONES POR VENCER</b> (próximos {DIAS_ANTICIPACION} días)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    for idx, s in enumerate(subs, start=1):
        dias = (s.end_date - today).days
        cliente = s.client.name if s.client else "Sin cliente"
        servicio = s.account.service if s.account else "Servicio"
        fecha_fin = s.end_date.strftime("%d/%m/%Y")
        estado_pago = s.payment_status.upper() if s.payment_status else "N/A"

        # Mensaje tipo "recordatorio"
        mensaje = render_message("recordatorio", s)
        wa_link = build_wa_link(s.client, mensaje) if s.platform == "whatsapp" else None

        lines.append(
            f"\n{idx}️⃣ <b>{cliente}</b> – {servicio}\n"
            f"   🗓 Vence: {fecha_fin} (en {dias} días)\n"
            f"   💰 Pago: {estado_pago}\n"
            f"   📲 Recordatorio: {wa_link or 'Sin WhatsApp'}"
        )

    return "\n".join(lines)


def build_unpaid_section(subs, today: date):
    """Construye texto para pagos pendientes."""
    if not subs:
        return None

    lines = []
    lines.append(
        "💰 <b>PAGOS PENDIENTES</b> (más de 1 día sin pagar)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    for idx, s in enumerate(subs, start=1):
        dias_transcurridos = (today - s.start_date).days
        cliente = s.client.name if s.client else "Sin cliente"
        servicio = s.account.service if s.account else "Servicio"
        fecha_inicio = s.start_date.strftime("%d/%m/%Y")
        fecha_fin = s.end_date.strftime("%d/%m/%Y")
        estado_pago = s.payment_status.upper() if s.payment_status else "N/A"

        # Mensaje tipo "pago"
        mensaje = render_message("pago", s)
        wa_link = build_wa_link(s.client, mensaje) if s.platform == "whatsapp" else None

        lines.append(
            f"\n{idx}️⃣ <b>{cliente}</b> – {servicio}\n"
            f"   📅 Inicio: {fecha_inicio} (hace {dias_transcurridos} días)\n"
            f"   🗓 Vence: {fecha_fin}\n"
            f"   💸 Estado pago: {estado_pago}\n"
            f"   📲 Cobro: {wa_link or 'Sin WhatsApp'}"
        )

    return "\n".join(lines)


def check_and_notify():
    """Revisa la base y envía notificaciones a Telegram."""
    today = date.today()
    limite = today + timedelta(days=DIAS_ANTICIPACION)

    with app.app_context():
        # Suscripciones por vencer
        expiring = (
            Subscription.query
            .filter(Subscription.end_date >= today,
                    Subscription.end_date <= limite)
            .order_by(Subscription.end_date.asc())
            .all()
        )

        # Pagos pendientes
        unpaid = (
            Subscription.query
            .filter(
                Subscription.payment_status != "pagado",
                Subscription.start_date <= (today - timedelta(days=1))
            )
            .order_by(Subscription.start_date.asc())
            .all()
        )

        parts = []

        expiring_text = build_expiring_section(expiring, today)
        if expiring_text:
            parts.append(expiring_text)

        unpaid_text = build_unpaid_section(unpaid, today)
        if unpaid_text:
            if parts:
                parts.append("")  # separación
            parts.append(unpaid_text)

        if not parts:
            print("No hay avisos para hoy.")
            return

        full_message = "\n".join(parts)
        ok = send_telegram_message(full_message)

        if ok:
            print("Notificación enviada correctamente.")
        else:
            print("ERROR al enviar la notificación.")


if __name__ == "__main__":
    check_and_notify()

