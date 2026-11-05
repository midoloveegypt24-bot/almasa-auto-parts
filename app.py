import os
import sys
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
import re
import uuid
import json
import sqlite3
import urllib.parse
from datetime import datetime
from functools import wraps

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, session, send_from_directory, abort, send_file
)
from werkzeug.utils import secure_filename
from werkzeug.security import check_password_hash, generate_password_hash

from config import Config
from database import get_db, init_db
from sync_service import sync_from_product_list, create_db_backup

app = Flask(__name__)
app.config.from_object(Config)

# Ensure folders exist
for folder in [Config.UPLOAD_FOLDER, Config.PRODUCT_IMAGES_FOLDER, Config.RECEIPT_IMAGES_FOLDER, Config.BACKUPS_FOLDER]:
    os.makedirs(folder, exist_ok=True)

# -------------------------------------------------------------
# Template Context Processors & Filters
# -------------------------------------------------------------
@app.context_processor
def inject_global_data():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, name, code, icon, image_url, description FROM vehicle_brands WHERE is_active = 1 ORDER BY display_order ASC")
    brands = [dict(row) for row in cursor.fetchall()]

    cursor.execute("SELECT id, name, icon, image_url FROM product_categories WHERE is_active = 1 ORDER BY display_order ASC")
    categories = [dict(row) for row in cursor.fetchall()]

    # Fetch site settings
    cursor.execute("SELECT key, value FROM site_settings")
    settings = {r['key']: r['value'] for r in cursor.fetchall()}

    # Fetch all active vehicle models with their product counts
    cursor.execute("""
    SELECT m.id, m.brand_id, m.name, m.name_en, m.code, m.years, m.image_url, COUNT(pm.product_id) as product_count
    FROM vehicle_models m
    LEFT JOIN product_models pm ON m.id = pm.model_id
    GROUP BY m.id
    ORDER BY m.display_order ASC, product_count DESC
    """)
    all_models = [dict(row) for row in cursor.fetchall()]

    conn.close()

    return {
        'site_settings': settings,
        'BUSINESS_NAME_AR': settings.get('hero_title') or Config.BUSINESS_NAME_AR,
        'BUSINESS_NAME_EN': Config.BUSINESS_NAME_EN,
        'BRAND_SLOGAN': settings.get('hero_slogan') or Config.BRAND_SLOGAN,
        'BUSINESS_LOCATION': settings.get('business_location') or Config.BUSINESS_LOCATION,
        'BUSINESS_PHONE': settings.get('business_phone') or Config.BUSINESS_PHONE,
        'WHATSAPP_NUMBER': settings.get('whatsapp_number') or Config.WHATSAPP_NUMBER,
        'WALLET_NUMBER': settings.get('wallet_number') or Config.WALLET_NUMBER,
        'INSTAPAY_ACCOUNT': settings.get('instapay_account') or Config.INSTAPAY_ACCOUNT,
        'all_brands': brands,
        'all_categories': categories,
        'all_models': all_models,
        'now_year': datetime.now().year
    }

@app.template_filter('format_currency')
def format_currency_filter(value):
    try:
        val = float(value or 0)
        return f"{val:,.2f}".rstrip('0').rstrip('.') + " ج.م"
    except (ValueError, TypeError):
        return "0 ج.م"

# -------------------------------------------------------------
# Helper Functions
# -------------------------------------------------------------
def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get('admin_logged_in'):
            flash('يرجى تسجيل الدخول للوصول إلى لوحة التحكم', 'warning')
            return redirect(url_for('admin_login', next=request.url))
        return f(*args, **kwargs)
    return decorated_function

def validate_egyptian_phone(phone):
    """Validate Egyptian mobile phone numbers (010, 011, 012, 015 - 11 digits)."""
    cleaned = re.sub(r'[\s\-\+]', '', phone or '')
    if cleaned.startswith('20'):
        cleaned = '0' + cleaned[2:]
    elif cleaned.startswith('0020'):
        cleaned = '0' + cleaned[4:]
    pattern = r'^0(10|11|12|15)[0-9]{8}$'
    return bool(re.match(pattern, cleaned)), cleaned

def generate_order_number():
    date_part = datetime.now().strftime("%y%m%d")
    random_part = uuid.uuid4().hex[:4].upper()
    return f"ALM-{date_part}-{random_part}"

def build_whatsapp_order_url(product_name, part_code, price, model_name=None, quantity=1, customer_name=None):
    greeting = "السلام عليكم ورحمة الله، أود الاستفسار وطلب قطعة الغيار التالية من الماسة:"
    msg = f"{greeting}\n"
    msg += f"🚗 اسم القطعة: {product_name}\n"
    if part_code:
        msg += f"🔢 كود الصنف / الباركود: {part_code}\n"
    if model_name:
        msg += f"🚙 موديل السيارة المتوافقة: {model_name}\n"
    msg += f"💰 السعر الأصلي: {price:,.2f} ج.م\n"
    msg += f"📦 الكمية المطلوبة: {quantity}\n"
    msg += f"💵 الإجمالي: {(price * quantity):,.2f} ج.م\n"
    if customer_name:
        msg += f"👤 اسم العميل: {customer_name}\n"
    msg += f"\nالمصدر: متجر الماسة لقطع غيار السيارات"
    
    encoded = urllib.parse.quote(msg)
    return f"https://wa.me/{Config.WHATSAPP_NUMBER}?text={encoded}"

# -------------------------------------------------------------
# Public Storefront Routes
# -------------------------------------------------------------
@app.route('/')
def index():
    conn = get_db()
    cursor = conn.cursor()

    # Get featured products (stock > 0 and marked featured or top stock)
    cursor.execute("""
    SELECT p.*, b.name as brand_name, c.name as category_name
    FROM products p
    LEFT JOIN vehicle_brands b ON p.brand_id = b.id
    LEFT JOIN product_categories c ON p.category_id = c.id
    WHERE p.is_active = 1 AND p.stock_quantity > 0
    ORDER BY p.is_featured DESC, p.stock_quantity DESC
    LIMIT 12
    """)
    featured_products = [dict(r) for r in cursor.fetchall()]

    # Brand stats with available product counts
    cursor.execute("""
    SELECT b.id, b.name, b.code, b.icon, b.description, COUNT(p.id) as product_count
    FROM vehicle_brands b
    LEFT JOIN products p ON b.id = p.brand_id AND p.is_active = 1 AND p.stock_quantity > 0
    WHERE b.is_active = 1
    GROUP BY b.id
    ORDER BY b.display_order ASC
    """)
    brand_cards = [dict(r) for r in cursor.fetchall()]

    # Category stats with available product counts
    cursor.execute("""
    SELECT c.id, c.name, c.icon, COUNT(p.id) as product_count
    FROM product_categories c
    LEFT JOIN products p ON c.id = p.category_id AND p.is_active = 1 AND p.stock_quantity > 0
    WHERE c.is_active = 1
    GROUP BY c.id
    ORDER BY c.display_order ASC
    """)
    category_cards = [dict(r) for r in cursor.fetchall()]

    # Total active products counter
    cursor.execute("SELECT COUNT(*), SUM(stock_quantity) FROM products WHERE is_active = 1 AND stock_quantity > 0")
    tot_row = cursor.fetchone()
    total_active_products = tot_row[0] or 0
    total_active_stock = tot_row[1] or 0

    conn.close()

    return render_template(
        'index.html',
        featured_products=featured_products,
        brand_cards=brand_cards,
        category_cards=category_cards,
        total_active_products=total_active_products,
        total_active_stock=total_active_stock
    )

@app.route('/catalog')
def catalog():
    brand_id = request.args.get('brand', type=int)
    model_id = request.args.get('model', type=int)
    category_id = request.args.get('category', type=int)
    query = request.args.get('q', '').strip()
    sort_by = request.args.get('sort', 'default')
    page = request.args.get('page', 1, type=int)
    per_page = 24

    conn = get_db()
    cursor = conn.cursor()

    # If model is provided without brand, resolve brand
    if model_id and not brand_id:
        cursor.execute("SELECT brand_id FROM vehicle_models WHERE id = ?", (model_id,))
        bm_row = cursor.fetchone()
        if bm_row:
            brand_id = bm_row[0]

    conditions = ["p.is_active = 1", "p.stock_quantity > 0"]
    params = []

    if brand_id:
        conditions.append("p.brand_id = ?")
        params.append(brand_id)

    if model_id:
        conditions.append("EXISTS (SELECT 1 FROM product_models pm WHERE pm.product_id = p.id AND pm.model_id = ?)")
        params.append(model_id)

    if category_id:
        conditions.append("p.category_id = ?")
        params.append(category_id)

    if query:
        conditions.append("(p.name LIKE ? OR p.barcode LIKE ? OR p.part_code LIKE ? OR p.model_name LIKE ?)")
        like_term = f"%{query}%"
        params.extend([like_term, like_term, like_term, like_term])

    where_clause = " WHERE " + " AND ".join(conditions)

    # Count total
    cursor.execute(f"SELECT COUNT(*) FROM products p {where_clause}", params)
    total_items = cursor.fetchone()[0]
    total_pages = max(1, (total_items + per_page - 1) // per_page)

    # Sort clause
    order_clause = "ORDER BY p.id ASC"
    if sort_by == 'price_asc':
        order_clause = "ORDER BY p.sale_price ASC"
    elif sort_by == 'price_desc':
        order_clause = "ORDER BY p.sale_price DESC"
    elif sort_by == 'name_asc':
        order_clause = "ORDER BY p.name ASC"
    elif sort_by == 'stock_desc':
        order_clause = "ORDER BY p.stock_quantity DESC"

    # Query items
    offset = (page - 1) * per_page
    query_sql = f"""
    SELECT p.*, b.name as brand_name, c.name as category_name
    FROM products p
    LEFT JOIN vehicle_brands b ON p.brand_id = b.id
    LEFT JOIN product_categories c ON p.category_id = c.id
    {where_clause}
    {order_clause}
    LIMIT ? OFFSET ?
    """
    cursor.execute(query_sql, params + [per_page, offset])
    products = [dict(r) for r in cursor.fetchall()]

    # Fetch models for selected brand if any
    brand_models = []
    selected_brand = None
    selected_model = None
    selected_category = None

    if brand_id:
        cursor.execute("SELECT * FROM vehicle_brands WHERE id = ?", (brand_id,))
        b_row = cursor.fetchone()
        if b_row:
            selected_brand = dict(b_row)

        cursor.execute("""
        SELECT m.id, m.name, m.code, m.years, m.image_url, COUNT(pm.product_id) as product_count
        FROM vehicle_models m
        LEFT JOIN product_models pm ON m.id = pm.model_id
        LEFT JOIN products p ON pm.product_id = p.id AND p.is_active = 1 AND p.stock_quantity > 0
        WHERE m.brand_id = ?
        GROUP BY m.id
        ORDER BY m.display_order ASC, product_count DESC
        """, (brand_id,))
        brand_models = [dict(r) for r in cursor.fetchall()]

    if model_id:
        cursor.execute("SELECT * FROM vehicle_models WHERE id = ?", (model_id,))
        m_row = cursor.fetchone()
        if m_row:
            selected_model = dict(m_row)

    if category_id:
        cursor.execute("SELECT * FROM product_categories WHERE id = ?", (category_id,))
        c_row = cursor.fetchone()
        if c_row:
            selected_category = dict(c_row)

    conn.close()

    return render_template(
        'catalog.html',
        products=products,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        current_brand=brand_id,
        current_model=model_id,
        brand_models=brand_models,
        selected_brand=selected_brand,
        selected_model=selected_model,
        selected_category=selected_category,
        current_category=category_id,
        current_query=query,
        current_sort=sort_by
    )

@app.route('/product/<int:product_id>')
def product_detail(product_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT p.*, b.name as brand_name, b.code as brand_code, c.name as category_name
    FROM products p
    LEFT JOIN vehicle_brands b ON p.brand_id = b.id
    LEFT JOIN product_categories c ON p.category_id = c.id
    WHERE p.id = ?
    """, (product_id,))
    prod = cursor.fetchone()

    if not prod:
        conn.close()
        abort(404)

    product = dict(prod)

    # Check stock rule: If product has zero stock and is not admin viewing, inform availability
    if product['stock_quantity'] <= 0 and not session.get('admin_logged_in'):
        conn.close()
        return render_template('out_of_stock.html', product=product), 404

    # Related products from same brand or category
    cursor.execute("""
    SELECT p.*, b.name as brand_name, c.name as category_name
    FROM products p
    LEFT JOIN vehicle_brands b ON p.brand_id = b.id
    LEFT JOIN product_categories c ON p.category_id = c.id
    WHERE p.id != ? AND p.is_active = 1 AND p.stock_quantity > 0 AND (p.brand_id = ? OR p.category_id = ?)
    LIMIT 4
    """, (product_id, product['brand_id'], product['category_id']))
    related = [dict(r) for r in cursor.fetchall()]

    conn.close()

    # Pre-generate encoded WhatsApp URL
    whatsapp_url = build_whatsapp_order_url(
        product_name=product['name'],
        part_code=product['part_code'] or product['barcode'],
        price=product['sale_price'],
        model_name=product['model_name'] or product['brand_name'],
        quantity=1
    )

    return render_template('product_detail.html', product=product, related=related, whatsapp_url=whatsapp_url)

# -------------------------------------------------------------
# REST API Endpoints (For fast Alpine.js instant search & filtering)
# -------------------------------------------------------------
@app.route('/api/products')
def api_products():
    brand_id = request.args.get('brand', type=int)
    model_id = request.args.get('model', type=int)
    category_id = request.args.get('category', type=int)
    query = request.args.get('q', '').strip()
    sort_by = request.args.get('sort', 'default')
    page = request.args.get('page', 1, type=int)
    limit = request.args.get('limit', 24, type=int)

    conn = get_db()
    cursor = conn.cursor()

    # If model is provided without brand, resolve brand
    if model_id and not brand_id:
        cursor.execute("SELECT brand_id FROM vehicle_models WHERE id = ?", (model_id,))
        bm_row = cursor.fetchone()
        if bm_row:
            brand_id = bm_row[0]

    conditions = ["p.is_active = 1", "p.stock_quantity > 0"]
    params = []

    if brand_id:
        conditions.append("p.brand_id = ?")
        params.append(brand_id)

    if model_id:
        conditions.append("EXISTS (SELECT 1 FROM product_models pm WHERE pm.product_id = p.id AND pm.model_id = ?)")
        params.append(model_id)

    if category_id:
        conditions.append("p.category_id = ?")
        params.append(category_id)

    if query:
        conditions.append("(p.name LIKE ? OR p.barcode LIKE ? OR p.part_code LIKE ? OR p.model_name LIKE ?)")
        like_term = f"%{query}%"
        params.extend([like_term, like_term, like_term, like_term])

    where_clause = " WHERE " + " AND ".join(conditions)

    # Count
    cursor.execute(f"SELECT COUNT(*) FROM products p {where_clause}", params)
    total_items = cursor.fetchone()[0]

    # Order
    order_clause = "ORDER BY p.id ASC"
    if sort_by == 'price_asc':
        order_clause = "ORDER BY p.sale_price ASC"
    elif sort_by == 'price_desc':
        order_clause = "ORDER BY p.sale_price DESC"
    elif sort_by == 'name_asc':
        order_clause = "ORDER BY p.name ASC"
    elif sort_by == 'stock_desc':
        order_clause = "ORDER BY p.stock_quantity DESC"

    offset = (page - 1) * limit
    cursor.execute(f"""
    SELECT p.id, p.name, p.barcode, p.part_code, p.sale_price, p.stock_quantity,
           p.image_url, p.model_name, b.name as brand_name, c.name as category_name
    FROM products p
    LEFT JOIN vehicle_brands b ON p.brand_id = b.id
    LEFT JOIN product_categories c ON p.category_id = c.id
    {where_clause}
    {order_clause}
    LIMIT ? OFFSET ?
    """, params + [limit, offset])

    items = []
    for r in cursor.fetchall():
        d = dict(r)
        d['whatsapp_url'] = build_whatsapp_order_url(
            d['name'], d['part_code'] or d['barcode'], d['sale_price'], d['model_name'] or d['brand_name']
        )
        items.append(d)

    conn.close()

    return jsonify({
        "status": "success",
        "total": total_items,
        "page": page,
        "total_pages": max(1, (total_items + limit - 1) // limit),
        "products": items
    })

# -------------------------------------------------------------
# Customer Order Creation & Checkout
# -------------------------------------------------------------
@app.route('/api/order/create', methods=['POST'])
def api_create_order():
    """
    Submits customer order with strict validation:
    1. Validates Egyptian phone number.
    2. Validates stock availability atomically inside a database transaction.
    3. Calculates subtotal and keeps delivery fee distinct.
    4. Generates unique order number.
    5. Deducts stock and logs inventory change.
    """
    data = request.get_json(silent=True) or request.form

    full_name = (data.get('customer_name') or '').strip()
    phone_raw = (data.get('customer_phone') or '').strip()
    vehicle_brand = (data.get('vehicle_brand') or '').strip()
    vehicle_model = (data.get('vehicle_model') or '').strip()
    delivery_address = (data.get('delivery_address') or '').strip()
    notes = (data.get('notes') or '').strip()
    payment_method = (data.get('payment_method') or 'wallet').strip()
    items = data.get('items', [])

    # Validation
    if not full_name:
        return jsonify({"status": "error", "message": "يرجى كتابة الاسم بالكامل"}), 400

    is_valid_phone, phone = validate_egyptian_phone(phone_raw)
    if not is_valid_phone:
        return jsonify({"status": "error", "message": "رقم الهاتف غير صحيح. يرجى إدخال رقم مصري صحيح (11 رقم يبدأ بـ 010 أو 011 أو 012 أو 015)"}), 400

    if not delivery_address:
        return jsonify({"status": "error", "message": "يرجى إدخال عنوان التوصيل بالتفصيل"}), 400

    if not items or len(items) == 0:
        return jsonify({"status": "error", "message": "سلة الطلبات فارغة، يرجى إضافة قطع الغيار المطلوبة"}), 400

    order_number = generate_order_number()

    conn = get_db()
    cursor = conn.cursor()

    try:
        # Atomic transaction
        cursor.execute("BEGIN TRANSACTION")

        # Create or update customer
        cursor.execute("SELECT id, total_orders FROM customers WHERE phone = ?", (phone,))
        cust = cursor.fetchone()
        if cust:
            customer_id = cust['id']
            cursor.execute("UPDATE customers SET name = ?, address = ?, total_orders = total_orders + 1 WHERE id = ?",
                           (full_name, delivery_address, customer_id))
        else:
            cursor.execute("INSERT INTO customers (name, phone, address, total_orders) VALUES (?, ?, ?, 1)",
                           (full_name, phone, delivery_address))
            customer_id = cursor.lastrowid

        subtotal = 0.0
        verified_items = []

        # Validate each product stock atomically
        for item in items:
            product_id = int(item.get('product_id'))
            qty = int(item.get('quantity', 1))

            if qty <= 0:
                conn.rollback()
                conn.close()
                return jsonify({"status": "error", "message": "الكمية المطلوبة يجب أن تكون 1 على الأقل"}), 400

            cursor.execute("SELECT id, name, part_code, barcode, sale_price, stock_quantity, is_active FROM products WHERE id = ?", (product_id,))
            prod = cursor.fetchone()

            if not prod:
                conn.rollback()
                conn.close()
                return jsonify({"status": "error", "message": f"المنتج رقم {product_id} غير موجود"}), 400

            if prod['stock_quantity'] < qty:
                conn.rollback()
                conn.close()
                return jsonify({
                    "status": "error",
                    "message": f"الكمية المطلوبة من '{prod['name']}' غير متوفرة حالياً في المخزن (المتاح: {int(prod['stock_quantity'])} قطعة فقط)"
                }), 400

            unit_price = float(prod['sale_price'])
            item_total = unit_price * qty
            subtotal += item_total

            verified_items.append({
                "product_id": prod['id'],
                "name": prod['name'],
                "part_code": prod['part_code'] or prod['barcode'],
                "unit_price": unit_price,
                "quantity": qty,
                "total_price": item_total,
                "current_stock": prod['stock_quantity']
            })

        # Calculate delivery fee: Do not invent fee, default is 0 or to be confirmed on location
        delivery_fee = 0.0
        total_amount = subtotal + delivery_fee

        # Insert Order
        cursor.execute("""
        INSERT INTO orders (
            order_number, customer_id, customer_name, customer_phone, vehicle_brand, vehicle_model,
            delivery_address, notes, subtotal, delivery_fee, total_amount, payment_method,
            payment_status, order_status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 'new')
        """, (order_number, customer_id, full_name, phone, vehicle_brand, vehicle_model,
              delivery_address, notes, subtotal, delivery_fee, total_amount, payment_method))
        order_id = cursor.lastrowid

        # Insert Order Items & Deduct Stock Atomically
        for v in verified_items:
            cursor.execute("""
            INSERT INTO order_items (order_id, product_id, product_name, part_code, unit_price, quantity, total_price)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (order_id, v['product_id'], v['name'], v['part_code'], v['unit_price'], v['quantity'], v['total_price']))

            new_stock = v['current_stock'] - v['quantity']
            # If stock drops to 0, automatically hide product from public catalog
            is_active = 0 if new_stock <= 0 else 1

            cursor.execute("""
            UPDATE products
            SET stock_quantity = ?, is_active = ?, updated_at = CURRENT_TIMESTAMP
            WHERE id = ?
            """, (new_stock, is_active, v['product_id']))

            # Log inventory deduction
            cursor.execute("""
            INSERT INTO inventory_logs (product_id, change_type, quantity_change, old_stock, new_stock, reason, reference_id)
            VALUES (?, 'order_sale', ?, ?, ?, 'طلب عميل جديد من المتجر الإلكتروني', ?)
            """, (v['product_id'], -v['quantity'], v['current_stock'], new_stock, order_number))

        conn.commit()
        conn.close()

        # Build WhatsApp Confirmation Message for Customer
        whatsapp_msg = (
            f"مرحباً الماسة لقطع غيار السيارات ✔️\n"
            f"تم تأكيد طلب جديد عبر المتجر الإلكتروني:\n"
            f"📌 رقم الطلب: {order_number}\n"
            f"👤 اسم العميل: {full_name}\n"
            f"📱 رقم الهاتف: {phone}\n"
            f"🚗 نوع وموديل السيارة: {vehicle_brand} - {vehicle_model}\n"
            f"📍 عنوان التوصيل: {delivery_address}\n"
            f"📦 المنتجات المطلوبة:\n"
        )
        for idx, vi in enumerate(verified_items, 1):
            whatsapp_msg += f"  {idx}. {vi['name']} (كود: {vi['part_code']}) - عدد {vi['quantity']} × {vi['unit_price']:,.2f} ج.م\n"

        whatsapp_msg += f"💰 إجمالي قيمة المنتجات: {subtotal:,.2f} ج.م\n"
        whatsapp_msg += f"💳 طريقة الدفع المختارة: {payment_method}\n"
        if notes:
            whatsapp_msg += f"📝 ملاحظات العميل: {notes}\n"

        whatsapp_url = f"https://wa.me/{Config.WHATSAPP_NUMBER}?text={urllib.parse.quote(whatsapp_msg)}"

        return jsonify({
            "status": "success",
            "message": "تم استلام طلبك بنجاح وسنقوم بالتجهيز والشحن فورا",
            "order_number": order_number,
            "order_id": order_id,
            "total_amount": total_amount,
            "whatsapp_url": whatsapp_url,
            "payment_url": url_for('payment_page', order_number=order_number)
        })

    except Exception as e:
        conn.rollback()
        conn.close()
        app.logger.error(f"Error creating order: {e}")
        return jsonify({"status": "error", "message": f"حدث خطأ أثناء معالجة الطلب: {str(e)}"}), 500

@app.route('/order/<order_number>')
def order_success(order_number):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM orders WHERE order_number = ?", (order_number,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        abort(404)

    cursor.execute("SELECT * FROM order_items WHERE order_id = ?", (order['id'],))
    items = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM payments WHERE order_id = ? ORDER BY id DESC LIMIT 1", (order['id'],))
    payment = cursor.fetchone()

    conn.close()

    order_dict = dict(order)
    payment_dict = dict(payment) if payment else None

    # Prepare WhatsApp Message
    wa_text = f"السلام عليكم، أود متابعة طلبي رقم {order_number} بإجمالي {order_dict['total_amount']:,.2f} ج.م باسم {order_dict['customer_name']}."
    whatsapp_url = f"https://wa.me/{Config.WHATSAPP_NUMBER}?text={urllib.parse.quote(wa_text)}"

    return render_template(
        'order_success.html',
        order=order_dict,
        items=items,
        payment=payment_dict,
        whatsapp_url=whatsapp_url
    )

# -------------------------------------------------------------
# Electronic Payment Workflow (Wallet & InstaPay)
# -------------------------------------------------------------
@app.route('/payment/<order_number>', methods=['GET', 'POST'])
def payment_page(order_number):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM orders WHERE order_number = ?", (order_number,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        abort(404)

    order_dict = dict(order)

    if request.method == 'POST':
        payment_method = request.form.get('payment_method', 'wallet')
        sender_phone = (request.form.get('sender_phone') or '').strip()
        transaction_ref = (request.form.get('transaction_reference') or '').strip()
        receipt_file = request.files.get('receipt_image')

        receipt_filename = None
        if receipt_file and receipt_file.filename:
            filename = secure_filename(receipt_file.filename)
            ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
            if ext in Config.ALLOWED_EXTENSIONS:
                unique_name = f"receipt_{order_number}_{uuid.uuid4().hex[:6]}.{ext}"
                save_path = os.path.join(Config.RECEIPT_IMAGES_FOLDER, unique_name)
                receipt_file.save(save_path)
                receipt_filename = unique_name

        # Insert or update payment record (Strictly manual verification: status = 'pending')
        cursor.execute("""
        INSERT INTO payments (
            order_id, order_number, payment_method, destination_number, amount,
            sender_phone, transaction_reference, receipt_image, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending')
        """, (order_dict['id'], order_number, payment_method, Config.WALLET_NUMBER,
              order_dict['total_amount'], sender_phone, transaction_ref, receipt_filename))

        # Update order payment method
        cursor.execute("UPDATE orders SET payment_method = ?, payment_status = 'pending' WHERE id = ?",
                       (payment_method, order_dict['id']))

        conn.commit()
        conn.close()

        flash('تم استلام بيانات التحويل بنجاح! سيقوم فريق المراجعة بالتحقق من الإيصال وتأكيد الدفع فوراً.', 'success')
        return redirect(url_for('order_success', order_number=order_number))

    # Check existing payment submission
    cursor.execute("SELECT * FROM payments WHERE order_id = ? ORDER BY id DESC LIMIT 1", (order_dict['id'],))
    existing_payment = cursor.fetchone()
    conn.close()

    return render_template(
        'payment.html',
        order=order_dict,
        payment=dict(existing_payment) if existing_payment else None
    )

# -------------------------------------------------------------
# Administration Dashboard Authentication & Routes
# -------------------------------------------------------------
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if session.get('admin_logged_in'):
        return redirect(url_for('admin_dashboard'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM admin_users WHERE username = ? AND is_active = 1", (username,))
        user = cursor.fetchone()

        if user and check_password_hash(user['password_hash'], password):
            session['admin_logged_in'] = True
            session['admin_id'] = user['id']
            session['admin_username'] = user['username']
            session['admin_name'] = user['full_name']
            session['admin_role'] = user['role']

            cursor.execute("UPDATE admin_users SET last_login = CURRENT_TIMESTAMP WHERE id = ?", (user['id'],))
            cursor.execute("INSERT INTO activity_logs (action, details, user_id, ip_address) VALUES ('admin_login', 'تسجيل دخول ناجح', ?, ?)",
                           (user['id'], request.remote_addr))
            conn.commit()
            conn.close()

            flash(f"أهلاً بك يا {user['full_name']} في لوحة تحكم الماسة لقطع الغيار", 'success')
            next_url = request.args.get('next') or url_for('admin_dashboard')
            return redirect(next_url)
        else:
            conn.close()
            flash('اسم المستخدم أو كلمة المرور غير صحيحة!', 'danger')

    return render_template('admin/login.html')

@app.route('/admin/logout')
def admin_logout():
    if session.get('admin_logged_in'):
        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("INSERT INTO activity_logs (action, details, user_id) VALUES ('admin_logout', 'تسجيل خروج', ?)",
                       (session.get('admin_id'),))
        conn.commit()
        conn.close()

    session.clear()
    flash('تم تسجيل الخروج بنجاح.', 'info')
    return redirect(url_for('admin_login'))

@app.route('/admin')
@app.route('/admin/dashboard')
@admin_required
def admin_dashboard():
    conn = get_db()
    cursor = conn.cursor()

    # KPI Statistics
    cursor.execute("SELECT COUNT(*) FROM products")
    total_products = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*), SUM(stock_quantity) FROM products WHERE stock_quantity > 0 AND is_active = 1")
    in_stock_row = cursor.fetchone()
    in_stock_count = in_stock_row[0] or 0
    total_stock_units = in_stock_row[1] or 0

    cursor.execute("SELECT COUNT(*) FROM products WHERE stock_quantity <= 0 OR is_active = 0")
    out_of_stock_count = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM vehicle_brands WHERE is_active = 1")
    total_brands = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM vehicle_models WHERE is_active = 1")
    total_models = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM orders")
    total_orders = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM orders WHERE order_status = 'new'")
    new_orders = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*) FROM payments WHERE status = 'pending'")
    pending_payments = cursor.fetchone()[0]

    cursor.execute("SELECT COUNT(*), SUM(amount) FROM payments WHERE status = 'approved'")
    confirmed_pay_row = cursor.fetchone()
    confirmed_payments = confirmed_pay_row[0] or 0
    total_revenue = confirmed_pay_row[1] or 0.0

    # Recent Orders (last 10)
    cursor.execute("""
    SELECT o.*, COUNT(oi.id) as item_count
    FROM orders o
    LEFT JOIN order_items oi ON o.id = oi.order_id
    GROUP BY o.id
    ORDER BY o.id DESC
    LIMIT 10
    """)
    recent_orders = [dict(r) for r in cursor.fetchall()]

    # Brand distribution for Chart.js
    cursor.execute("""
    SELECT b.name, COUNT(p.id) as count
    FROM products p
    JOIN vehicle_brands b ON p.brand_id = b.id
    WHERE p.is_active = 1 AND p.stock_quantity > 0
    GROUP BY b.id
    ORDER BY count DESC
    """)
    brand_stats = [dict(r) for r in cursor.fetchall()]

    # Category distribution for Chart.js
    cursor.execute("""
    SELECT c.name, COUNT(p.id) as count
    FROM products p
    JOIN product_categories c ON p.category_id = c.id
    WHERE p.is_active = 1 AND p.stock_quantity > 0
    GROUP BY c.id
    ORDER BY count DESC
    """)
    category_stats = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return render_template(
        'admin/dashboard.html',
        total_products=total_products,
        in_stock_count=in_stock_count,
        total_stock_units=total_stock_units,
        out_of_stock_count=out_of_stock_count,
        total_brands=total_brands,
        total_models=total_models,
        total_orders=total_orders,
        new_orders=new_orders,
        pending_payments=pending_payments,
        confirmed_payments=confirmed_payments,
        total_revenue=total_revenue,
        recent_orders=recent_orders,
        brand_stats=brand_stats,
        category_stats=category_stats
    )

@app.route('/admin/products')
@admin_required
def admin_products():
    brand_id = request.args.get('brand', type=int)
    category_id = request.args.get('category', type=int)
    query = request.args.get('q', '').strip()
    status_filter = request.args.get('status', 'all')
    page = request.args.get('page', 1, type=int)
    per_page = 30

    conn = get_db()
    cursor = conn.cursor()

    conditions = ["1=1"]
    params = []

    if brand_id:
        conditions.append("p.brand_id = ?")
        params.append(brand_id)

    if category_id:
        conditions.append("p.category_id = ?")
        params.append(category_id)

    if status_filter == 'in_stock':
        conditions.append("p.stock_quantity > 0 AND p.is_active = 1")
    elif status_filter == 'out_of_stock':
        conditions.append("(p.stock_quantity <= 0 OR p.is_active = 0)")

    if query:
        conditions.append("(p.name LIKE ? OR p.barcode LIKE ? OR p.part_code LIKE ? OR p.id = ?)")
        like_term = f"%{query}%"
        try:
            int_id = int(query)
        except ValueError:
            int_id = -1
        params.extend([like_term, like_term, like_term, int_id])

    where_clause = " WHERE " + " AND ".join(conditions)

    # Count
    cursor.execute(f"SELECT COUNT(*) FROM products p {where_clause}", params)
    total_items = cursor.fetchone()[0]
    total_pages = max(1, (total_items + per_page - 1) // per_page)

    offset = (page - 1) * per_page
    cursor.execute(f"""
    SELECT p.*, b.name as brand_name, c.name as category_name
    FROM products p
    LEFT JOIN vehicle_brands b ON p.brand_id = b.id
    LEFT JOIN product_categories c ON p.category_id = c.id
    {where_clause}
    ORDER BY p.id ASC
    LIMIT ? OFFSET ?
    """, params + [per_page, offset])
    products = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return render_template(
        'admin/products.html',
        products=products,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        current_brand=brand_id,
        current_category=category_id,
        current_query=query,
        current_status=status_filter
    )

@app.route('/admin/product/edit/<int:product_id>', methods=['POST'])
@admin_required
def admin_product_edit(product_id):
    name = request.form.get('name', '').strip()
    part_code = request.form.get('part_code', '').strip()
    barcode = request.form.get('barcode', '').strip()
    brand_id = request.form.get('brand_id', type=int)
    category_id = request.form.get('category_id', type=int)
    model_name = request.form.get('model_name', '').strip()
    new_price = request.form.get('sale_price', type=float)
    new_stock = request.form.get('stock_quantity', type=float)
    is_active = 1 if request.form.get('is_active') == '1' else 0
    price_change_reason = request.form.get('price_reason', 'تعديل يدوي من لوحة التحكم').strip()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT sale_price, stock_quantity FROM products WHERE id = ?", (product_id,))
    curr = cursor.fetchone()
    if not curr:
        conn.close()
        flash('المنتج غير موجود', 'danger')
        return redirect(url_for('admin_products'))

    old_price = curr['sale_price']
    old_stock = curr['stock_quantity']

    # Audit price changes
    if abs(old_price - new_price) > 0.01:
        cursor.execute("""
        INSERT INTO price_audit_logs (product_id, old_price, new_price, reason, user_id)
        VALUES (?, ?, ?, ?, ?)
        """, (product_id, old_price, new_price, price_change_reason, session.get('admin_id')))

    # Audit stock changes
    if abs(old_stock - new_stock) > 0.01:
        cursor.execute("""
        INSERT INTO inventory_logs (product_id, change_type, quantity_change, old_stock, new_stock, reason, user_id)
        VALUES (?, 'manual_adjustment', ?, ?, ?, 'تعديل رصيد يدوي من الإدارة', ?)
        """, (product_id, new_stock - old_stock, old_stock, new_stock, session.get('admin_id')))

    # Automatic zero stock rule: if stock is 0, auto-deactivate
    if new_stock <= 0:
        is_active = 0

    cursor.execute("""
    UPDATE products
    SET name=?, part_code=?, barcode=?, brand_id=?, category_id=?, model_name=?,
        sale_price=?, stock_quantity=?, is_active=?, updated_at=CURRENT_TIMESTAMP
    WHERE id=?
    """, (name, part_code, barcode, brand_id, category_id, model_name,
          new_price, new_stock, is_active, product_id))

    conn.commit()
    conn.close()

    flash(f"تم تحديث بيانات المنتج '{name}' بنجاح", 'success')
    return redirect(request.referrer or url_for('admin_products'))

@app.route('/admin/product/upload-image/<int:product_id>', methods=['POST'])
@admin_required
def admin_product_upload_image(product_id):
    file = request.files.get('image')
    if not file or not file.filename:
        flash('يرجى اختيار ملف صورة صالح', 'warning')
        return redirect(request.referrer or url_for('admin_products'))

    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    if ext not in Config.ALLOWED_EXTENSIONS:
        flash('امتداد الصورة غير مدعوم (المسموح: jpg, jpeg, png, webp)', 'danger')
        return redirect(request.referrer or url_for('admin_products'))

    unique_filename = f"prod_{product_id}_{uuid.uuid4().hex[:6]}.{ext}"
    file_path = os.path.join(Config.PRODUCT_IMAGES_FOLDER, unique_filename)
    file.save(file_path)

    image_rel_url = f"/static/uploads/products/{unique_filename}"

    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("UPDATE products SET image_url = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                   (image_rel_url, product_id))
    conn.commit()
    conn.close()

    flash('تم رفع وتعيين صورة المنتج بنجاح!', 'success')
    return redirect(request.referrer or url_for('admin_products'))

@app.route('/admin/orders')
@admin_required
def admin_orders():
    status_filter = request.args.get('status', 'all')
    page = request.args.get('page', 1, type=int)
    per_page = 20

    conn = get_db()
    cursor = conn.cursor()

    conditions = ["1=1"]
    params = []

    if status_filter != 'all':
        conditions.append("o.order_status = ?")
        params.append(status_filter)

    where_clause = " WHERE " + " AND ".join(conditions)

    cursor.execute(f"SELECT COUNT(*) FROM orders o {where_clause}", params)
    total_items = cursor.fetchone()[0]
    total_pages = max(1, (total_items + per_page - 1) // per_page)

    offset = (page - 1) * per_page
    cursor.execute(f"""
    SELECT o.*, COUNT(oi.id) as items_count, p.status as payment_verified_status, p.receipt_image
    FROM orders o
    LEFT JOIN order_items oi ON o.id = oi.order_id
    LEFT JOIN payments p ON o.id = p.order_id
    {where_clause}
    GROUP BY o.id
    ORDER BY o.id DESC
    LIMIT ? OFFSET ?
    """, params + [per_page, offset])
    orders = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return render_template(
        'admin/orders.html',
        orders=orders,
        page=page,
        total_pages=total_pages,
        total_items=total_items,
        current_status=status_filter
    )

@app.route('/admin/order/<int:order_id>')
@admin_required
def admin_order_detail(order_id):
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM orders WHERE id = ?", (order_id,))
    order = cursor.fetchone()
    if not order:
        conn.close()
        abort(404)

    cursor.execute("SELECT * FROM order_items WHERE order_id = ?", (order_id,))
    items = [dict(r) for r in cursor.fetchall()]

    cursor.execute("SELECT * FROM payments WHERE order_id = ? ORDER BY id DESC", (order_id,))
    payments = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return render_template('admin/order_detail.html', order=dict(order), items=items, payments=payments)

@app.route('/admin/order/update-status/<int:order_id>', methods=['POST'])
@admin_required
def admin_order_update_status(order_id):
    new_status = request.form.get('order_status')
    payment_status = request.form.get('payment_status')

    conn = get_db()
    cursor = conn.cursor()

    updates = []
    params = []

    if new_status:
        updates.append("order_status = ?")
        params.append(new_status)

    if payment_status:
        updates.append("payment_status = ?")
        params.append(payment_status)

    if updates:
        updates.append("updated_at = CURRENT_TIMESTAMP")
        params.append(order_id)
        cursor.execute(f"UPDATE orders SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()

    conn.close()
    flash(f"تم تحديث حالة الطلب #{order_id} بنجاح", 'success')
    return redirect(request.referrer or url_for('admin_orders'))

@app.route('/admin/payments')
@admin_required
def admin_payments():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT p.*, o.customer_name, o.customer_phone, o.total_amount as order_total, u.full_name as confirmed_by_name
    FROM payments p
    JOIN orders o ON p.order_id = o.id
    LEFT JOIN admin_users u ON p.confirmed_by = u.id
    ORDER BY CASE WHEN p.status = 'pending' THEN 1 ELSE 2 END, p.id DESC
    """)
    payments = [dict(r) for r in cursor.fetchall()]
    conn.close()

    return render_template('admin/payments.html', payments=payments)

@app.route('/admin/payment/verify/<int:payment_id>', methods=['POST'])
@admin_required
def admin_payment_verify(payment_id):
    action = request.form.get('action') # approve or reject
    admin_notes = request.form.get('admin_notes', '').strip()

    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM payments WHERE id = ?", (payment_id,))
    pay = cursor.fetchone()
    if not pay:
        conn.close()
        flash('بيانات الدفع غير موجودة', 'danger')
        return redirect(url_for('admin_payments'))

    new_status = 'approved' if action == 'approve' else 'rejected'
    order_payment_status = 'paid' if action == 'approve' else 'rejected'

    cursor.execute("""
    UPDATE payments
    SET status = ?, admin_notes = ?, confirmed_by = ?, confirmed_at = CURRENT_TIMESTAMP
    WHERE id = ?
    """, (new_status, admin_notes, session.get('admin_id'), payment_id))

    cursor.execute("UPDATE orders SET payment_status = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                   (order_payment_status, pay['order_id']))

    # Log activity
    cursor.execute("""
    INSERT INTO activity_logs (action, details, user_id)
    VALUES ('payment_verification', ?, ?)
    """, (f"تم { 'اعتماد' if action == 'approve' else 'رفض' } عملية الدفع للطلب {pay['order_number']}", session.get('admin_id')))

    conn.commit()
    conn.close()

    flash(f"تم {'اعتماد الدفع وتأكيد السداد' if action == 'approve' else 'رفض الدفع'} للطلب {pay['order_number']}", 'success')
    return redirect(url_for('admin_payments'))

@app.route('/admin/inventory')
@admin_required
def admin_inventory():
    conn = get_db()
    cursor = conn.cursor()

    # Low stock items (< 3 pieces)
    cursor.execute("""
    SELECT p.*, b.name as brand_name, c.name as category_name
    FROM products p
    LEFT JOIN vehicle_brands b ON p.brand_id = b.id
    LEFT JOIN product_categories c ON p.category_id = c.id
    WHERE p.is_active = 1 AND p.stock_quantity > 0 AND p.stock_quantity < 3
    ORDER BY p.stock_quantity ASC
    LIMIT 20
    """)
    low_stock_items = [dict(r) for r in cursor.fetchall()]

    # Out of stock items (stock = 0)
    cursor.execute("""
    SELECT p.*, b.name as brand_name, c.name as category_name
    FROM products p
    LEFT JOIN vehicle_brands b ON p.brand_id = b.id
    LEFT JOIN product_categories c ON p.category_id = c.id
    WHERE p.stock_quantity <= 0
    ORDER BY p.id ASC
    LIMIT 20
    """)
    out_of_stock_items = [dict(r) for r in cursor.fetchall()]

    # Recent inventory logs
    cursor.execute("""
    SELECT l.*, p.name as product_name, p.part_code, u.full_name as user_name
    FROM inventory_logs l
    JOIN products p ON l.product_id = p.id
    LEFT JOIN admin_users u ON l.user_id = u.id
    ORDER BY l.id DESC
    LIMIT 25
    """)
    inventory_logs = [dict(r) for r in cursor.fetchall()]

    # Price audit logs
    cursor.execute("""
    SELECT pal.*, p.name as product_name, p.part_code, u.full_name as user_name
    FROM price_audit_logs pal
    JOIN products p ON pal.product_id = p.id
    LEFT JOIN admin_users u ON pal.user_id = u.id
    ORDER BY pal.id DESC
    LIMIT 25
    """)
    price_logs = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return render_template(
        'admin/inventory.html',
        low_stock_items=low_stock_items,
        out_of_stock_items=out_of_stock_items,
        inventory_logs=inventory_logs,
        price_logs=price_logs
    )

@app.route('/admin/inventory/sync-backup', methods=['POST'])
@admin_required
def admin_sync_backup():
    """Import updated backup file or re-sync with original database."""
    file = request.files.get('backup_file')

    # If file uploaded, handle json or back
    if file and file.filename:
        filename = secure_filename(file.filename)
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else ''
        if ext in ['json']:
            data = json.load(file)
            report = sync_from_product_list(data, source_name=filename)
            flash(f"تمت مزامنة {report['total_incoming']} صنف بنجاح! تم تحديث رصيد {report['stock_updated']} صنف وتحديث أسعار {report['prices_updated']} صنف.", 'success')
            return redirect(url_for('admin_inventory'))
        else:
            flash("يرجى رفع ملف بصيغة JSON مستخرج من قاعدة البيانات.", 'warning')
            return redirect(url_for('admin_inventory'))
    else:
        # Re-sync from verified extraction file
        extracted_file = r'C:\Users\windows10\.gemini\antigravity\brain\3012f5fd-1541-46c2-bf65-593ad6821de1\scratch\almasa_extracted_products.json'
        if os.path.exists(extracted_file):
            with open(extracted_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            report = sync_from_product_list(data, source_name="قاعدة بيانات النظام الأصلي AlmasaOriginalDB")
            flash(f"تمت مزامنة المخزون مع قاعدة البيانات الأصلية بنجاح! تم فحص {report['total_incoming']} صنف.", 'success')
        else:
            flash("ملف البيانات المصدر غير متوفر.", 'danger')

        return redirect(url_for('admin_inventory'))

@app.route('/admin/database/backup-download')
@admin_required
def admin_download_db_backup():
    """Create timestamped backup and download it."""
    backup_path = create_db_backup()
    return send_file(backup_path, as_attachment=True, download_name=os.path.basename(backup_path))

@app.route('/admin/brands')
@admin_required
def admin_brands():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("""
    SELECT b.*, COUNT(p.id) as product_count, SUM(p.stock_quantity) as total_stock
    FROM vehicle_brands b
    LEFT JOIN products p ON b.id = p.brand_id AND p.is_active = 1 AND p.stock_quantity > 0
    GROUP BY b.id
    ORDER BY b.display_order ASC
    """)
    brands = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
    SELECT m.*, b.name as brand_name
    FROM vehicle_models m
    JOIN vehicle_brands b ON m.brand_id = b.id
    ORDER BY b.display_order ASC, m.name ASC
    """)
    models = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return render_template('admin/brands.html', brands=brands, models=models)

# -------------------------------------------------------------
# Site Design Management Routes (إدارة تصميم الموقع)
# -------------------------------------------------------------
@app.route('/admin/design')
@admin_required
def admin_design():
    conn = get_db()
    cursor = conn.cursor()

    cursor.execute("SELECT key, value FROM site_settings")
    settings = {r['key']: r['value'] for r in cursor.fetchall()}

    cursor.execute("""
    SELECT b.*, COUNT(p.id) as product_count
    FROM vehicle_brands b
    LEFT JOIN products p ON b.id = p.brand_id AND p.is_active = 1 AND p.stock_quantity > 0
    GROUP BY b.id
    ORDER BY b.display_order ASC
    """)
    brands = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
    SELECT m.*, b.name as brand_name, COUNT(pm.product_id) as product_count
    FROM vehicle_models m
    JOIN vehicle_brands b ON m.brand_id = b.id
    LEFT JOIN product_models pm ON m.id = pm.model_id
    GROUP BY m.id
    ORDER BY b.display_order ASC, m.display_order ASC
    """)
    models = [dict(r) for r in cursor.fetchall()]

    cursor.execute("""
    SELECT c.*, COUNT(p.id) as product_count
    FROM product_categories c
    LEFT JOIN products p ON c.id = p.category_id AND p.is_active = 1 AND p.stock_quantity > 0
    GROUP BY c.id
    ORDER BY c.display_order ASC
    """)
    categories = [dict(r) for r in cursor.fetchall()]

    conn.close()

    return render_template(
        'admin/design.html',
        settings=settings,
        brands=brands,
        models=models,
        categories=categories
    )

@app.route('/admin/design/update-general', methods=['POST'])
@admin_required
def admin_design_update_general():
    hero_title = request.form.get('hero_title', '').strip()
    hero_slogan = request.form.get('hero_slogan', '').strip()
    hero_subtitle = request.form.get('hero_subtitle', '').strip()
    announcement_text = request.form.get('announcement_text', '').strip()
    primary_color = request.form.get('primary_color', '').strip()

    conn = get_db()
    cursor = conn.cursor()

    updates = [
        ('hero_title', hero_title),
        ('hero_slogan', hero_slogan),
        ('hero_subtitle', hero_subtitle),
        ('announcement_text', announcement_text),
        ('primary_color', primary_color or '#DC2626')
    ]
    for k, v in updates:
        if v:
            cursor.execute("INSERT INTO site_settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=?", (k, v, v))

    # Handle Logo Upload
    logo_file = request.files.get('logo_file')
    if logo_file and logo_file.filename:
        filename = secure_filename(logo_file.filename)
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'png'
        if ext in Config.ALLOWED_EXTENSIONS:
            unique_name = f"almasa_logo_{uuid.uuid4().hex[:6]}.{ext}"
            file_path = os.path.join(Config.DESIGN_IMAGES_FOLDER, unique_name)
            logo_file.save(file_path)
            rel_url = f"/static/uploads/design/{unique_name}"
            cursor.execute("INSERT INTO site_settings (key, value) VALUES ('logo_url', ?) ON CONFLICT(key) DO UPDATE SET value=?", (rel_url, rel_url))

    # Handle Hero Banner Upload
    banner_file = request.files.get('hero_banner_file')
    if banner_file and banner_file.filename:
        filename = secure_filename(banner_file.filename)
        ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
        if ext in Config.ALLOWED_EXTENSIONS:
            unique_name = f"hero_banner_{uuid.uuid4().hex[:6]}.{ext}"
            file_path = os.path.join(Config.DESIGN_IMAGES_FOLDER, unique_name)
            banner_file.save(file_path)
            rel_url = f"/static/uploads/design/{unique_name}"
            cursor.execute("INSERT INTO site_settings (key, value) VALUES ('hero_banner_url', ?) ON CONFLICT(key) DO UPDATE SET value=?", (rel_url, rel_url))

    conn.commit()
    conn.close()

    flash('تم حفظ وتحديث إعدادات التصميم والهوية البصرية بنجاح!', 'success')
    return redirect(url_for('admin_design'))

@app.route('/admin/design/upload-brand-image/<int:brand_id>', methods=['POST'])
@admin_required
def admin_design_upload_brand_image(brand_id):
    file = request.files.get('image')
    if not file or not file.filename:
        flash('يرجى اختيار ملف صورة صالح', 'warning')
        return redirect(url_for('admin_design'))

    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    if ext in Config.ALLOWED_EXTENSIONS:
        unique_name = f"brand_{brand_id}_{uuid.uuid4().hex[:6]}.{ext}"
        save_path = os.path.join(Config.BRAND_IMAGES_FOLDER, unique_name)
        file.save(save_path)
        rel_url = f"/static/uploads/brands/{unique_name}"

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE vehicle_brands SET image_url = ? WHERE id = ?", (rel_url, brand_id))
        conn.commit()
        conn.close()

        flash('تم تحديث صورة ماركة السيارة بنجاح!', 'success')
    else:
        flash('امتداد الصورة غير مدعوم', 'danger')

    return redirect(url_for('admin_design') + '#tab-brands')

@app.route('/admin/design/upload-model-image/<int:model_id>', methods=['POST'])
@admin_required
def admin_design_upload_model_image(model_id):
    file = request.files.get('image')
    if not file or not file.filename:
        flash('يرجى اختيار ملف صورة صالح', 'warning')
        return redirect(url_for('admin_design'))

    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    if ext in Config.ALLOWED_EXTENSIONS:
        unique_name = f"model_{model_id}_{uuid.uuid4().hex[:6]}.{ext}"
        save_path = os.path.join(Config.MODEL_IMAGES_FOLDER, unique_name)
        file.save(save_path)
        rel_url = f"/static/uploads/models/{unique_name}"

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE vehicle_models SET image_url = ? WHERE id = ?", (rel_url, model_id))
        conn.commit()
        conn.close()

        flash('تم تحديث صورة موديل السيارة بنجاح!', 'success')
    else:
        flash('امتداد الصورة غير مدعوم', 'danger')

    return redirect(url_for('admin_design') + '#tab-models')

@app.route('/admin/design/upload-category-image/<int:category_id>', methods=['POST'])
@admin_required
def admin_design_upload_category_image(category_id):
    file = request.files.get('image')
    if not file or not file.filename:
        flash('يرجى اختيار ملف صورة صالح', 'warning')
        return redirect(url_for('admin_design'))

    filename = secure_filename(file.filename)
    ext = filename.rsplit('.', 1)[-1].lower() if '.' in filename else 'jpg'
    if ext in Config.ALLOWED_EXTENSIONS:
        unique_name = f"category_{category_id}_{uuid.uuid4().hex[:6]}.{ext}"
        save_path = os.path.join(Config.CATEGORY_IMAGES_FOLDER, unique_name)
        file.save(save_path)
        rel_url = f"/static/uploads/categories/{unique_name}"

        conn = get_db()
        cursor = conn.cursor()
        cursor.execute("UPDATE product_categories SET image_url = ? WHERE id = ?", (rel_url, category_id))
        conn.commit()
        conn.close()

        flash('تم تحديث صورة القسم الفني بنجاح!', 'success')
    else:
        flash('امتداد الصورة غير مدعوم', 'danger')

    return redirect(url_for('admin_design') + '#tab-categories')

@app.route('/admin/design/reset-image', methods=['POST'])
@admin_required
def admin_design_reset_image():
    target = request.form.get('target')
    target_id = request.form.get('id', type=int)

    conn = get_db()
    cursor = conn.cursor()

    if target == 'logo':
        cursor.execute("UPDATE site_settings SET value = '' WHERE key = 'logo_url'")
        flash('تمت إعادة الشعار إلى الشعار الافتراضي للمنظومة', 'info')
    elif target == 'banner':
        cursor.execute("UPDATE site_settings SET value = '' WHERE key = 'hero_banner_url'")
        flash('تمت إعادة البانر الرئيسي إلى الخلفية الرياضية الافتراضية', 'info')
    elif target == 'brand' and target_id:
        cursor.execute("UPDATE vehicle_brands SET image_url = NULL WHERE id = ?", (target_id,))
        flash('تمت إزالة الصورة المخصصة للماركة', 'info')
    elif target == 'model' and target_id:
        cursor.execute("UPDATE vehicle_models SET image_url = NULL WHERE id = ?", (target_id,))
        flash('تمت إزالة الصورة المخصصة للموديل', 'info')
    elif target == 'category' and target_id:
        cursor.execute("UPDATE product_categories SET image_url = NULL WHERE id = ?", (target_id,))
        flash('تمت إزالة الصورة المخصصة للقسم الفني', 'info')

    conn.commit()
    conn.close()
    return redirect(url_for('admin_design'))

# -------------------------------------------------------------
# Static File Handlers (Secure)
# -------------------------------------------------------------
@app.route('/static/uploads/<path:filename>')
def uploaded_file(filename):
    return send_from_directory(Config.UPLOAD_FOLDER, filename)

if __name__ == '__main__':
    init_db()
    print("================================================================")
    print(" Almasa Auto Spare Parts E-Commerce Platform")
    print(" الماسة لقطع غيار السيارات — الماسة اختيارك المضمون في قطع الغيار ✔️")
    print(" Starting server on http://127.0.0.1:5000 ...")
    print("================================================================")
    app.run(host='0.0.0.0', port=5000, debug=False)
