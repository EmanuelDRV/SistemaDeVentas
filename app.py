from flask import Flask, render_template, request, redirect, url_for, flash
from flask_sqlalchemy import SQLAlchemy
from datetime import datetime, timedelta, date
from urllib.parse import quote_plus
import os
from sqlalchemy import or_

app = Flask(__name__)

# --- CONFIG ---
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///streaming.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = 'cambia-esto-por-algo-mas-seguro'

db = SQLAlchemy(app)

# Monedas soportadas
CURRENCIES = [
    ('BOB', 'Peso boliviano'),
    ('ARS', 'Peso argentino'),
    ('CLP', 'Peso chileno'),
]

PLATFORMS = [
    ('whatsapp', 'WhatsApp'),
    ('messenger', 'Messenger'),
]

PAY_STATUSES = [
    ('pagado', 'Pagado'),
    ('pendiente', 'Pendiente'),
    ('renovado', 'Renovado'),
]

COUNTRY_CODES = [
    ('591', '+591 Bolivia'),
    ('54', '+54 Argentina'),
    ('56', '+56 Chile'),
]


# --- MODELOS ---

class Client(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    country_code = db.Column(db.String(5))  # 591, 54, 56
    phone = db.Column(db.String(50))
    email = db.Column(db.String(120))
    notes = db.Column(db.Text)


class Seller(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    phone = db.Column(db.String(50))
    notes = db.Column(db.Text)


class Account(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    service = db.Column(db.String(80), nullable=False)   # Netflix, Disney+
    user = db.Column(db.String(120), nullable=False)     # correo/usuario
    password = db.Column(db.String(120), nullable=False)
    profile = db.Column(db.String(120))                  # notas sobre tipo de cuenta
    notes = db.Column(db.Text)
    total_slots = db.Column(db.Integer, default=1)       # perfiles totales
    used_slots = db.Column(db.Integer, default=0)        # perfiles usados


class Subscription(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    client_id = db.Column(db.Integer, db.ForeignKey('client.id'), nullable=False)
    account_id = db.Column(db.Integer, db.ForeignKey('account.id'), nullable=False)
    seller_id = db.Column(db.Integer, db.ForeignKey('seller.id'), nullable=False)
    start_date = db.Column(db.Date, nullable=False)
    end_date = db.Column(db.Date, nullable=False)
    price = db.Column(db.Float, nullable=False)
    currency = db.Column(db.String(3), nullable=False, default='BOB')  # BOB, ARS, CLP
    platform = db.Column(db.String(20), nullable=False, default='whatsapp')  # whatsapp/messenger
    payment_status = db.Column(db.String(20), nullable=False, default='pagado')  # pagado/pendiente/renovado
    status = db.Column(db.String(20), default='activa')  # activa, vencida, pausada
    slot = db.Column(db.String(50))  # nombre del perfil/slot asignado

    client = db.relationship('Client', backref=db.backref('subscriptions', lazy=True))
    account = db.relationship('Account', backref=db.backref('subscriptions', lazy=True))
    seller = db.relationship('Seller', backref=db.backref('subscriptions', lazy=True))


class MessageTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(50), unique=True, nullable=False)  # 'entrega', 'recordatorio', 'pago'
    name = db.Column(db.String(120), nullable=False)
    content = db.Column(db.Text, nullable=False)
    description = db.Column(db.Text)


# --- MENSAJES POR DEFECTO (PLANTILLAS) ---

DEFAULT_MESSAGES = {
    'entrega': (
        "Hola {nombre}, gracias por tu compra de {servicio}.\n"
        "Usuario: {usuario}\n"
        "Contraseña: {password}\n"
        "Perfil/Slot: {slot}\n"
        "Tu membresía vence el {fecha_fin}."
    ),
    'recordatorio': (
        "Hola {nombre}, te recuerdo que tu membresía de {servicio} "
        "vence el {fecha_fin} (en {dias_restantes} días).\n"
        "Si deseas renovar, házmelo saber y te mantengo el espacio 😉."
    ),
    'pago': (
        "Hola {nombre}, te escribo por tu membresía de {servicio}.\n"
        "Estado de pago actual: {estado_pago}.\n"
        "Fecha de vencimiento: {fecha_fin}.\n"
        "Monto: {precio} {moneda}.\n"
        "Por favor, avísame si ya realizaste el pago o deseas renovar 😊."
    ),
}


# --- HELPERS WHATSAPP / PLANTILLAS ---

def build_wa_number(client: Client):
    """Devuelve el número en formato internacional para wa.me (solo dígitos)."""
    if not client or not client.phone:
        return None

    phone = client.phone.strip()
    code = (client.country_code or '').strip()

    # quitar todo lo que no sea dígito
    digits = ''.join(c for c in phone if c.isdigit())

    # si el usuario ya escribió +591..., usamos eso
    if phone.startswith('+'):
        return digits

    # si tenemos código de país, lo anteponemos
    if code:
        return code + digits

    # fallback: solo el número
    return digits if digits else None


def build_wa_link(client: Client, text: str):
    number = build_wa_number(client)
    if not number:
        return None
    return f"https://wa.me/{number}?text={quote_plus(text)}"


def render_message(key: str, sub: Subscription) -> str:
    """Rellena una plantilla (DB o por defecto) con datos de la suscripción."""
    tmpl = MessageTemplate.query.filter_by(key=key).first()
    base = tmpl.content if tmpl else DEFAULT_MESSAGES.get(key, '')

    today = datetime.today().date()
    dias_restantes = (sub.end_date - today).days

    data = {
        'nombre': sub.client.name if sub.client else '',
        'servicio': sub.account.service if sub.account else '',
        'fecha_inicio': sub.start_date.strftime('%d/%m/%Y') if sub.start_date else '',
        'fecha_fin': sub.end_date.strftime('%d/%m/%Y') if sub.end_date else '',
        'dias_restantes': dias_restantes,
        'precio': f"{sub.price:.2f}",
        'moneda': sub.currency or '',
        'vendedor': sub.seller.name if sub.seller else '',
        'plataforma': 'WhatsApp' if sub.platform == 'whatsapp' else (
            'Messenger' if sub.platform == 'messenger' else (sub.platform or '')
        ),
        'slot': sub.slot or '',
        'estado_pago': sub.payment_status.upper() if sub.payment_status else '',
        'usuario': sub.account.user if sub.account else '',
        'password': sub.account.password if sub.account else '',
    }

    text = base
    for k, v in data.items():
        text = text.replace('{' + k + '}', str(v))
    return text


# --- RUTAS BÁSICAS / PANEL ---

@app.route('/test')
def test():
    return "<h1>Ruta /test funcionando ✅</h1>"


@app.route('/')
def index():
    today = datetime.today().date()
    soon = today + timedelta(days=3)

    # Suscripciones activas y por vencer
    active_subs = Subscription.query.filter(
        Subscription.end_date >= today
    ).order_by(Subscription.end_date.asc()).all()

    expiring_subs = Subscription.query.filter(
        Subscription.end_date >= today,
        Subscription.end_date <= soon
    ).order_by(Subscription.end_date.asc()).all()

    # Ventas del mes actual (filtrado en Python para evitar líos de fechas)
    all_subs = Subscription.query.all()
    month_subs = [
        s for s in all_subs
        if s.start_date
        and s.start_date.year == today.year
        and s.start_date.month == today.month
    ]

    # Totales globales por moneda
    total_por_moneda = {}
    # Totales por vendedor y moneda
    totales_vendedor = {}

    for s in month_subs:
        cur = s.currency or 'BOB'
        total_por_moneda[cur] = total_por_moneda.get(cur, 0) + s.price

        seller_name = s.seller.name if getattr(s, "seller", None) else 'Sin vendedor'
        if seller_name not in totales_vendedor:
            totales_vendedor[seller_name] = {}
        totales_vendedor[seller_name][cur] = (
            totales_vendedor[seller_name].get(cur, 0) + s.price
        )

    activas_count = len(active_subs)
    por_vencer_count = len(expiring_subs)

    return render_template(
        'index.html',
        active_subs=active_subs,
        expiring_subs=expiring_subs,
        today=today,
        activas_count=activas_count,
        por_vencer_count=por_vencer_count,
        total_por_moneda=total_por_moneda,
        totales_vendedor=totales_vendedor,
        currencies=CURRENCIES,
    )


# ---- CLIENTES ----

@app.route('/clientes')
def clientes():
    q = request.args.get('q', '', type=str)
    query = Client.query

    if q:
        like = f"%{q}%"
        query = query.filter(
            db.or_(
                Client.name.ilike(like),
                Client.phone.ilike(like)
            )
        )

    clients = query.order_by(Client.name.asc()).all()
    return render_template('clientes.html', clients=clients)



@app.route('/clientes/nuevo', methods=['GET', 'POST'])
def nuevo_cliente():
    if request.method == 'POST':
        name = request.form['name']
        country_code = request.form.get('country_code') or None
        phone = request.form['phone']
        email = request.form['email']
        notes = request.form['notes']

        nuevo = Client(
            name=name,
            country_code=country_code,
            phone=phone,
            email=email,
            notes=notes
        )
        db.session.add(nuevo)
        db.session.commit()
        flash('Cliente creado correctamente', 'success')
        return redirect(url_for('clientes'))

    return render_template('nuevo_cliente.html', country_codes=COUNTRY_CODES)


@app.route('/clientes/editar/<int:client_id>', methods=['GET', 'POST'])
def editar_cliente(client_id):
    client = Client.query.get_or_404(client_id)

    if request.method == 'POST':
        client.name = request.form['name']
        client.country_code = request.form.get('country_code') or None
        client.phone = request.form['phone']
        client.email = request.form['email']
        client.notes = request.form['notes']
        db.session.commit()
        flash('Cliente actualizado correctamente.', 'success')
        return redirect(url_for('clientes'))

    return render_template('editar_cliente.html', client=client, country_codes=COUNTRY_CODES)

from datetime import date  # Asegúrate de tener esto arriba (ya lo tienes casi seguro)

@app.route('/clientes/<int:client_id>')
def detalle_cliente(client_id):
    client = Client.query.get_or_404(client_id)
    subs = (
        Subscription.query
        .filter_by(client_id=client.id)
        .order_by(Subscription.end_date.desc())
        .all()
    )
    today = date.today()
    return render_template('cliente_detalle.html', client=client, subs=subs, today=today)



@app.route('/clientes/eliminar/<int:client_id>', methods=['POST'])
def eliminar_cliente(client_id):
    client = Client.query.get_or_404(client_id)

    tiene_ventas = Subscription.query.filter_by(client_id=client.id).count() > 0
    if tiene_ventas:
        flash('No puedes eliminar este cliente porque tiene suscripciones registradas.', 'danger')
        return redirect(url_for('clientes'))

    db.session.delete(client)
    db.session.commit()
    flash('Cliente eliminado correctamente.', 'success')
    return redirect(url_for('clientes'))


# ---- VENDEDORES ----

@app.route('/vendedores')
def vendedores():
    sellers = Seller.query.order_by(Seller.name.asc()).all()
    return render_template('vendedores.html', sellers=sellers)


@app.route('/vendedores/nuevo', methods=['GET', 'POST'])
def nuevo_vendedor():
    if request.method == 'POST':
        name = request.form['name']
        phone = request.form['phone']
        notes = request.form['notes']

        nuevo = Seller(name=name, phone=phone, notes=notes)
        db.session.add(nuevo)
        db.session.commit()
        flash('Vendedor creado correctamente', 'success')
        return redirect(url_for('vendedores'))

    return render_template('nuevo_vendedor.html')


@app.route('/vendedores/eliminar/<int:seller_id>', methods=['POST'])
def eliminar_vendedor(seller_id):
    seller = Seller.query.get_or_404(seller_id)

    tiene_ventas = Subscription.query.filter_by(seller_id=seller.id).count() > 0
    if tiene_ventas:
        flash('No puedes eliminar este vendedor porque tiene ventas asociadas.', 'danger')
        return redirect(url_for('vendedores'))

    db.session.delete(seller)
    db.session.commit()
    flash('Vendedor eliminado correctamente.', 'success')
    return redirect(url_for('vendedores'))


# ---- CUENTAS ----

@app.route('/cuentas')
def cuentas():
    accounts = Account.query.order_by(Account.service.asc(), Account.user.asc()).all()
    return render_template('cuentas.html', accounts=accounts)


@app.route('/cuentas/nueva', methods=['GET', 'POST'])
def nueva_cuenta():
    if request.method == 'POST':
        service = request.form['service']
        user = request.form['user']
        password = request.form['password']
        profile = request.form['profile']
        notes = request.form['notes']
        total_slots_str = request.form.get('total_slots', '1')

        try:
            total_slots = int(total_slots_str)
        except ValueError:
            total_slots = 1

        if total_slots < 1:
            total_slots = 1

        nueva = Account(
            service=service,
            user=user,
            password=password,
            profile=profile,
            notes=notes,
            total_slots=total_slots,
            used_slots=0
        )
        db.session.add(nueva)
        db.session.commit()
        flash('Cuenta creada correctamente', 'success')
        return redirect(url_for('cuentas'))

    return render_template('nueva_cuenta.html')


@app.route('/cuentas/editar/<int:account_id>', methods=['GET', 'POST'])
def editar_cuenta(account_id):
    account = Account.query.get_or_404(account_id)

    if request.method == 'POST':
        account.service = request.form['service']
        account.user = request.form['user']
        account.password = request.form['password']
        account.profile = request.form['profile']
        account.notes = request.form['notes']
        total_slots_str = request.form.get('total_slots', '1')
        try:
            total_slots = int(total_slots_str)
        except ValueError:
            total_slots = 1
        if total_slots < 1:
            total_slots = 1
        account.total_slots = total_slots
        db.session.commit()
        flash('Cuenta actualizada correctamente.', 'success')
        return redirect(url_for('cuentas'))

    return render_template('editar_cuenta.html', account=account)


@app.route('/cuentas/eliminar/<int:account_id>', methods=['POST'])
def eliminar_cuenta(account_id):
    account = Account.query.get_or_404(account_id)

    tiene_ventas = Subscription.query.filter_by(account_id=account.id).count() > 0
    if tiene_ventas:
        flash('No puedes eliminar esta cuenta porque está asociada a suscripciones.', 'danger')
        return redirect(url_for('cuentas'))

    db.session.delete(account)
    db.session.commit()
    flash('Cuenta eliminada correctamente.', 'success')
    return redirect(url_for('cuentas'))


# ---- PLANTILLAS MENSAJES ----

@app.route('/plantillas')
def plantillas():
    templates = MessageTemplate.query.order_by(MessageTemplate.key.asc()).all()
    # Si no hay, creamos las 3 por defecto
    if not templates:
        defaults = [
            ('entrega', 'Mensaje de entrega',
             'Se envía cuando entregas usuario y contraseña al cliente.',
             DEFAULT_MESSAGES['entrega']),
            ('recordatorio', 'Mensaje de recordatorio',
             'Se envía pocos días antes del vencimiento.',
             DEFAULT_MESSAGES['recordatorio']),
            ('pago', 'Mensaje de pago',
             'Se usa para cobrar y recordar el estado de pago.',
             DEFAULT_MESSAGES['pago']),
        ]
        for key, name, desc, content in defaults:
            db.session.add(MessageTemplate(
                key=key,
                name=name,
                description=desc,
                content=content
            ))
        db.session.commit()
        templates = MessageTemplate.query.order_by(MessageTemplate.key.asc()).all()

    return render_template('plantillas.html', templates=templates)


@app.route('/plantillas/editar/<key>', methods=['GET', 'POST'])
def editar_plantilla(key):
    tmpl = MessageTemplate.query.filter_by(key=key).first()
    if not tmpl:
        flash('Plantilla no encontrada.', 'danger')
        return redirect(url_for('plantillas'))

    if request.method == 'POST':
        tmpl.name = request.form['name']
        tmpl.content = request.form['content']
        db.session.commit()
        flash('Plantilla actualizada correctamente.', 'success')
        return redirect(url_for('plantillas'))

    return render_template('editar_plantilla.html', tmpl=tmpl)


# ---- VENTAS / SUSCRIPCIONES ----


@app.route('/ventas')
def ventas():
    today = datetime.today().date()

    seller_id = request.args.get('seller_id', type=int)
    platform = request.args.get('platform', default='', type=str)
    payment_status = request.args.get('payment_status', default='', type=str)
    q = request.args.get('q', '', type=str)

    # Hacemos join para poder buscar por cliente y servicio
    query = Subscription.query.join(Client).join(Account)

    if seller_id:
        query = query.filter(Subscription.seller_id == seller_id)
    if platform:
        query = query.filter(Subscription.platform == platform)
    if payment_status:
        query = query.filter(Subscription.payment_status == payment_status)
    if q:
        like = f"%{q}%"
        query = query.filter(
            or_(
                Client.name.ilike(like),
                Account.service.ilike(like),
                Client.phone.ilike(like)
            )
        )

    subs = query.order_by(Subscription.start_date.desc()).all()
    sellers = Seller.query.order_by(Seller.name.asc()).all()

    return render_template(
        'ventas.html',
        subs=subs,
        today=today,
        sellers=sellers,
        platforms=PLATFORMS,
        pay_statuses=PAY_STATUSES,
        selected_seller_id=seller_id or '',
        selected_platform=platform,
        selected_payment_status=payment_status,
        q=q,
    )



@app.route('/ventas/pendientes')
def ventas_pendientes():
    today = datetime.today().date()
    subs = Subscription.query.filter_by(payment_status='pendiente') \
                             .order_by(Subscription.end_date.asc()).all()
    return render_template('ventas_pendientes.html', subs=subs, today=today)


@app.route('/ventas/nueva', methods=['GET', 'POST'])
def nueva_venta():
    # solo cuentas con slots libres
    accounts = Account.query.filter(Account.used_slots < Account.total_slots) \
                            .order_by(Account.service.asc(), Account.user.asc()).all()
    clients = Client.query.order_by(Client.name.asc()).all()
    sellers = Seller.query.order_by(Seller.name.asc()).all()
    today = datetime.today().date()

    if request.method == 'POST':
        client_type = request.form.get('client_type', 'existente')
        client_id = None

        # ---- CLIENTE EXISTENTE ----
        if client_type == 'existente':
            client_id = request.form.get('client_id')
            if not client_id:
                flash('Selecciona un cliente existente o llena los datos de uno nuevo.', 'danger')
                return render_template(
                    'nueva_venta.html',
                    clients=clients,
                    accounts=accounts,
                    sellers=sellers,
                    client_type=client_type,
                    currencies=CURRENCIES,
                    platforms=PLATFORMS,
                    pay_statuses=PAY_STATUSES,
                    country_codes=COUNTRY_CODES,
                    today=today,
                )

        # ---- CLIENTE NUEVO ----
        else:
            name = request.form.get('new_name', '').strip()
            country_code = request.form.get('new_country_code') or None
            phone = request.form.get('new_phone', '').strip()
            email = request.form.get('new_email', '').strip() or None
            notes = request.form.get('new_notes', '').strip()

            if not name:
                flash('El nombre del nuevo cliente es obligatorio.', 'danger')
                return render_template(
                    'nueva_venta.html',
                    clients=clients,
                    accounts=accounts,
                    sellers=sellers,
                    client_type=client_type,
                    currencies=CURRENCIES,
                    platforms=PLATFORMS,
                    pay_statuses=PAY_STATUSES,
                    country_codes=COUNTRY_CODES,
                    today=today,
                )

            new_client = Client(
                name=name,
                country_code=country_code,
                phone=phone,
                email=email,
                notes=notes
            )
            db.session.add(new_client)
            db.session.flush()
            client_id = new_client.id

        # ---- DATOS GENERALES DE LA VENTA (COMPARTIDOS) ----
        seller_id = request.form.get('seller_id')
        platform = request.form.get('platform', 'whatsapp')
        payment_status = request.form.get('payment_status', 'pagado')

        if not seller_id:
            flash('Selecciona un vendedor.', 'danger')
            return render_template(
                'nueva_venta.html',
                clients=clients,
                accounts=accounts,
                sellers=sellers,
                client_type=client_type,
                currencies=CURRENCIES,
                platforms=PLATFORMS,
                pay_statuses=PAY_STATUSES,
                country_codes=COUNTRY_CODES,
                today=today,
            )

        start_date_str = request.form['start_date']
        days_str = request.form.get('days', '30')

        try:
            days = int(days_str)
        except ValueError:
            days = 30

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        except ValueError:
            flash('La fecha de inicio no es válida.', 'danger')
            return render_template(
                'nueva_venta.html',
                clients=clients,
                accounts=accounts,
                sellers=sellers,
                client_type=client_type,
                currencies=CURRENCIES,
                platforms=PLATFORMS,
                pay_statuses=PAY_STATUSES,
                country_codes=COUNTRY_CODES,
                today=today,
            )

        end_date = start_date + timedelta(days=days)

        # ---- LÍNEAS DE SERVICIO (VARIAS PLATAFORMAS) ----
        account_ids = request.form.getlist('account_id[]')
        prices = request.form.getlist('price[]')
        currencies_list = request.form.getlist('currency[]')
        slots = request.form.getlist('slot[]')

        lineas = []
        for idx, acc_id in enumerate(account_ids):
            acc_id = (acc_id or '').strip()
            if not acc_id:
                continue  # fila vacía, la ignoramos

            price_str = (prices[idx] if idx < len(prices) else '').strip()
            currency = (currencies_list[idx] if idx < len(currencies_list) else 'BOB') or 'BOB'
            slot = (slots[idx] if idx < len(slots) else '').strip()

            try:
                price = float(price_str)
            except ValueError:
                price = 0.0

            lineas.append({
                'account_id': acc_id,
                'price': price,
                'currency': currency,
                'slot': slot,
            })

        if not lineas:
            flash('Debes añadir al menos una plataforma/servicio en la venta.', 'danger')
            return render_template(
                'nueva_venta.html',
                clients=clients,
                accounts=accounts,
                sellers=sellers,
                client_type=client_type,
                currencies=CURRENCIES,
                platforms=PLATFORMS,
                pay_statuses=PAY_STATUSES,
                country_codes=COUNTRY_CODES,
                today=today,
            )

        # ---- CREAMOS UNA SUSCRIPCIÓN POR CADA LÍNEA ----
        creadas = 0
        for linea in lineas:
            account = Account.query.get(linea['account_id'])
            if not account:
                continue

            if account.used_slots >= account.total_slots:
                flash(
                    f'La cuenta {account.service} ({account.user}) ya no tiene perfiles disponibles.',
                    'danger'
                )
                continue

            sub = Subscription(
                client_id=client_id,
                account_id=account.id,
                seller_id=seller_id,
                start_date=start_date,
                end_date=end_date,
                price=linea['price'],
                currency=linea['currency'],
                platform=platform,
                payment_status=payment_status,
                status='activa',
                slot=linea['slot']
            )
            db.session.add(sub)
            account.used_slots += 1
            creadas += 1

        if creadas == 0:
            flash('No se pudo registrar ninguna suscripción (verifica los perfiles disponibles).', 'danger')
            db.session.rollback()
            return redirect(url_for('nueva_venta'))

        db.session.commit()
        flash(f'Se registraron {creadas} suscripción(es) para el cliente.', 'success')
        return redirect(url_for('ventas'))

    # GET
    return render_template(
        'nueva_venta.html',
        clients=clients,
        accounts=accounts,
        sellers=sellers,
        client_type='existente',
        currencies=CURRENCIES,
        platforms=PLATFORMS,
        pay_statuses=PAY_STATUSES,
        country_codes=COUNTRY_CODES,
        today=today,
    )


@app.route('/ventas/editar/<int:sub_id>', methods=['GET', 'POST'])
def editar_venta(sub_id):
    sub = Subscription.query.get_or_404(sub_id)
    sellers = Seller.query.order_by(Seller.name.asc()).all()

    if request.method == 'POST':
        start_date_str = request.form['start_date']
        end_date_str = request.form['end_date']
        sub.start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        sub.end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        sub.price = float(request.form['price'])
        sub.currency = request.form['currency']
        sub.platform = request.form['platform']
        sub.payment_status = request.form['payment_status']
        sub.slot = request.form['slot']
        seller_id = request.form.get('seller_id')
        if seller_id:
            sub.seller_id = int(seller_id)
        db.session.commit()
        flash('Venta / suscripción actualizada correctamente.', 'success')
        return redirect(url_for('ventas'))

    return render_template(
        'editar_venta.html',
        sub=sub,
        sellers=sellers,
        currencies=CURRENCIES,
        platforms=PLATFORMS,
        pay_statuses=PAY_STATUSES,
    )


@app.route('/ventas/renovar/<int:sub_id>', methods=['GET', 'POST'])
def renovar_venta(sub_id):
    sub = Subscription.query.get_or_404(sub_id)

    if request.method == 'POST':
        start_date_str = request.form['start_date']
        days = int(request.form['days'])
        price = float(request.form['price'])
        payment_status = request.form.get('payment_status', 'pagado')

        start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        end_date = start_date + timedelta(days=days)

        nueva = Subscription(
            client_id=sub.client_id,
            account_id=sub.account_id,
            seller_id=sub.seller_id,
            start_date=start_date,
            end_date=end_date,
            price=price,
            currency=sub.currency,
            platform=sub.platform,
            payment_status=payment_status,
            status='activa',
            slot=sub.slot
        )
        db.session.add(nueva)
        # NO tocamos used_slots porque es el mismo slot/cliente
        db.session.commit()

        flash('Renovación registrada correctamente.', 'success')
        return redirect(url_for('ventas'))

    # valores por defecto: nueva fecha desde el día siguiente al fin o desde hoy
    today = datetime.today().date()
    suggested_start = max(sub.end_date + timedelta(days=1), today)
    default_days = (sub.end_date - sub.start_date).days or 30

    return render_template(
        'renovar_venta.html',
        sub=sub,
        suggested_start=suggested_start,
        default_days=default_days,
        pay_statuses=PAY_STATUSES,
    )


@app.route('/ventas/eliminar/<int:sub_id>', methods=['POST'])
def eliminar_venta(sub_id):
    sub = Subscription.query.get_or_404(sub_id)
    account = sub.account

    # liberar 1 slot
    if account and account.used_slots > 0:
        account.used_slots -= 1

    db.session.delete(sub)
    db.session.commit()
    flash('Suscripción / venta eliminada correctamente.', 'success')
    return redirect(url_for('ventas'))


# ---- MENSAJES (USANDO PLANTILLAS) ----

@app.route('/mensaje_entrega/<int:sub_id>')
def mensaje_entrega(sub_id):
    sub = Subscription.query.get_or_404(sub_id)
    msg = render_message('entrega', sub)

    wa_link = None
    if sub.platform == 'whatsapp':
        wa_link = build_wa_link(sub.client, msg)

    return render_template('mensaje.html', sub=sub, msg=msg, tipo='Entrega', wa_link=wa_link)


@app.route('/mensaje_recordatorio/<int:sub_id>')
def mensaje_recordatorio(sub_id):
    sub = Subscription.query.get_or_404(sub_id)
    msg = render_message('recordatorio', sub)

    wa_link = None
    if sub.platform == 'whatsapp':
        wa_link = build_wa_link(sub.client, msg)

    return render_template('mensaje.html', sub=sub, msg=msg, tipo='Recordatorio', wa_link=wa_link)


@app.route('/mensaje_pago/<int:sub_id>')
def mensaje_pago(sub_id):
    sub = Subscription.query.get_or_404(sub_id)
    msg = render_message('pago', sub)

    wa_link = None
    if sub.platform == 'whatsapp':
        wa_link = build_wa_link(sub.client, msg)

    return render_template('mensaje.html', sub=sub, msg=msg, tipo='Pago', wa_link=wa_link)


# --- INICIO APP ---

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
    app.run(debug=True, port=5006)
