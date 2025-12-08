from datetime import date, timedelta
import requests

# Importamos cosas desde tu app principal
from app import app, Subscription, render_message, build_wa_link

# === CONFIGURA AQUÍ TU BOT ===
# Usa el MISMO token y chat_id que te funcionan en el notifier viejo.
TELEGRAM_TOKEN = "7636575849:AAGp-5XQuIev5OtcbFLrJzzipu3iuq0YFZs"      # ej: "123456789:AA...."
TELEGRAM_CHAT_ID = -1003331904641             # tu chat_id (número, sin comillas o con, da igual)


# Cuántos días antes avisar vencimientos
DIAS_ANTICIPACION = 3


def send_telegram_message(text: str) -> bool:
    """Envía un mensaje simple al chat configurado. Devuelve True si salió bien."""
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("Falta configurar TOKEN o CHAT_ID de Telegram")
        return False

    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    params = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text
    }
    try:
        r = requests.get(url, params=params, timeout=10)
        if not r.ok:
            print("Error al enviar mensaje Telegram:", r.text)
            return False
        return True
    except Exception as e:
        print("Excepción enviando mensaje Telegram:", e)
        return False


def build_expiring_section(subs, today: date):
    """
    Texto para suscripciones por vencer con link de recordatorio.
    Usa la plantilla 'recordatorio' y, si es WhatsApp, genera link wa.me.
    """
    if not subs:
        return None

    lines = []
    lines.append(
        f"⚠️ SUSCRIPCIONES POR VENCER (próximos {DIAS_ANTICIPACION} días)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    for idx, s in enumerate(subs, start=1):
        dias = (s.end_date - today).days
        cliente = s.client.name if s.client else "Sin cliente"
        servicio = s.account.service if s.account else "Servicio"
        fecha_fin = s.end_date.strftime("%d/%m/%Y")
        estado_pago = s.payment_status.upper() if s.payment_status else "N/A"

        # Mensaje tipo "recordatorio" usando la plantilla del sistema
        mensaje = render_message("recordatorio", s)

        wa_link = None
        if s.platform == "whatsapp":
            wa_link = build_wa_link(s.client, mensaje)

        lines.append(
            f"\n{idx}️⃣ {cliente} – {servicio}\n"
            f"   🗓 Vence: {fecha_fin} (en {dias} días)\n"
            f"   💰 Estado pago: {estado_pago}\n"
            f"   📲 Recordatorio: {wa_link or '📵 Sin link de WhatsApp (no hay número o no es WhatsApp)'}"
        )

    return "\n".join(lines)


def build_unpaid_section(subs, today: date):
    """
    Texto para pagos pendientes (más de 1 día sin pagar) con link de pago.
    Usa la plantilla 'pago' y, si es WhatsApp, genera link wa.me.
    """
    if not subs:
        return None

    lines = []
    lines.append(
        "💰 PAGOS PENDIENTES (más de 1 día sin pagar)\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    )

    for idx, s in enumerate(subs, start=1):
        dias_transcurridos = (today - s.start_date).days
        cliente = s.client.name if s.client else "Sin cliente"
        servicio = s.account.service if s.account else "Servicio"
        fecha_inicio = s.start_date.strftime("%d/%m/%Y")
        fecha_fin = s.end_date.strftime("%d/%m/%Y")
        estado_pago = s.payment_status.upper() if s.payment_status else "N/A"

        # Mensaje tipo "pago" usando la plantilla del sistema
        mensaje = render_message("pago", s)

        wa_link = None
        if s.platform == "whatsapp":
            wa_link = build_wa_link(s.client, mensaje)

        lines.append(
            f"\n{idx}️⃣ {cliente} – {servicio}\n"
            f"   📅 Inicio: {fecha_inicio} (hace {dias_transcurridos} días)\n"
            f"   🗓 Vence: {fecha_fin}\n"
            f"   💸 Estado pago: {estado_pago}\n"
            f"   📲 Cobro: {wa_link or '📵 Sin link de WhatsApp (no hay número o no es WhatsApp)'}"
        )

    return "\n".join(lines)


def check_and_notify():
    """Revisa la base y manda un Telegram si hay cosas por avisar."""
    today = date.today()
    limite = today + timedelta(days=DIAS_ANTICIPACION)

    with app.app_context():
        # 1) Suscripciones que vencen pronto (entre hoy y hoy+N días)
        expiring = (
            Subscription.query
            .filter(Subscription.end_date >= today,
                    Subscription.end_date <= limite)
            .order_by(Subscription.end_date.asc())
            .all()
        )

        # 2) Pagos pendientes: payment_status != 'pagado' y ya pasó 1 día desde el inicio
        unpaid = (
            Subscription.query
            .filter(Subscription.payment_status != "pagado",
                    Subscription.start_date <= (today - timedelta(days=1)))
            .order_by(Subscription.start_date.asc())
            .all()
        )

        parts = []

        expiring_text = build_expiring_section(expiring, today)
        if expiring_text:
            parts.append(expiring_text)

        unpaid_text = build_unpaid_section(unpaid, today)
        if unpaid_text:
            parts.append("")   # línea en blanco entre secciones
            parts.append(unpaid_text)

        if not parts:
            print("No hay suscripciones por vencer ni pagos pendientes.")
            return

        full_message = "\n".join(parts)
        ok = send_telegram_message(full_message)
        if ok:
            print("Aviso enviado por Telegram.")
        else:
            print("No se pudo enviar el aviso por Telegram.")


if __name__ == "__main__":
    check_and_notify()
