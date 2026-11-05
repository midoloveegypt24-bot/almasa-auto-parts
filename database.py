import sqlite3
import os
import json
import logging
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash

DB_PATH = os.path.join(os.path.dirname(__file__), 'data', 'almasa.db')

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()

    cursor.executescript("""
    -- 1. Admin Users
    CREATE TABLE IF NOT EXISTS admin_users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        email TEXT,
        role TEXT DEFAULT 'admin',
        is_active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        last_login DATETIME
    );

    -- 2. Vehicle Brands
    CREATE TABLE IF NOT EXISTS vehicle_brands (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        name_en TEXT,
        code TEXT UNIQUE,
        description TEXT,
        icon TEXT,
        display_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    -- 3. Vehicle Models
    CREATE TABLE IF NOT EXISTS vehicle_models (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        brand_id INTEGER NOT NULL,
        name TEXT NOT NULL,
        name_en TEXT,
        years TEXT,
        is_active INTEGER DEFAULT 1,
        FOREIGN KEY (brand_id) REFERENCES vehicle_brands (id) ON DELETE CASCADE
    );

    -- 4. Product Categories
    CREATE TABLE IF NOT EXISTS product_categories (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT UNIQUE NOT NULL,
        name_en TEXT,
        icon TEXT,
        display_order INTEGER DEFAULT 0,
        is_active INTEGER DEFAULT 1,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    -- 5. Products
    CREATE TABLE IF NOT EXISTS products (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        original_id INTEGER UNIQUE,
        name TEXT NOT NULL,
        name_en TEXT,
        barcode TEXT,
        part_code TEXT,
        brand_id INTEGER,
        category_id INTEGER,
        model_name TEXT,
        sale_price REAL NOT NULL,
        purch_price REAL DEFAULT 0,
        stock_quantity REAL NOT NULL DEFAULT 0,
        image_url TEXT,
        description TEXT,
        is_active INTEGER DEFAULT 1,
        is_featured INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (brand_id) REFERENCES vehicle_brands (id),
        FOREIGN KEY (category_id) REFERENCES product_categories (id)
    );

    CREATE INDEX IF NOT EXISTS idx_products_name ON products(name);
    CREATE INDEX IF NOT EXISTS idx_products_barcode ON products(barcode);
    CREATE INDEX IF NOT EXISTS idx_products_part_code ON products(part_code);
    CREATE INDEX IF NOT EXISTS idx_products_brand ON products(brand_id);
    CREATE INDEX IF NOT EXISTS idx_products_category ON products(category_id);
    CREATE INDEX IF NOT EXISTS idx_products_stock ON products(stock_quantity);

    -- 6. Customers
    CREATE TABLE IF NOT EXISTS customers (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        name TEXT NOT NULL,
        phone TEXT NOT NULL,
        email TEXT,
        address TEXT,
        city TEXT DEFAULT 'أسيوط',
        total_orders INTEGER DEFAULT 0,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );

    CREATE INDEX IF NOT EXISTS idx_customers_phone ON customers(phone);

    -- 7. Orders
    CREATE TABLE IF NOT EXISTS orders (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_number TEXT UNIQUE NOT NULL,
        customer_id INTEGER,
        customer_name TEXT NOT NULL,
        customer_phone TEXT NOT NULL,
        vehicle_brand TEXT,
        vehicle_model TEXT,
        delivery_address TEXT NOT NULL,
        notes TEXT,
        subtotal REAL NOT NULL,
        delivery_fee REAL DEFAULT 0,
        total_amount REAL NOT NULL,
        payment_method TEXT DEFAULT 'cash',
        payment_status TEXT DEFAULT 'pending', -- pending, paid, rejected
        order_status TEXT DEFAULT 'new', -- new, processing, shipped, delivered, cancelled
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (customer_id) REFERENCES customers (id)
    );

    CREATE INDEX IF NOT EXISTS idx_orders_number ON orders(order_number);
    CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(order_status);
    CREATE INDEX IF NOT EXISTS idx_orders_created ON orders(created_at);

    -- 8. Order Items
    CREATE TABLE IF NOT EXISTS order_items (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        product_id INTEGER NOT NULL,
        product_name TEXT NOT NULL,
        part_code TEXT,
        unit_price REAL NOT NULL,
        quantity INTEGER NOT NULL,
        total_price REAL NOT NULL,
        FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE,
        FOREIGN KEY (product_id) REFERENCES products (id)
    );

    -- 9. Payments
    CREATE TABLE IF NOT EXISTS payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        order_id INTEGER NOT NULL,
        order_number TEXT NOT NULL,
        payment_method TEXT NOT NULL, -- wallet, instapay
        destination_number TEXT DEFAULT '01212429139',
        amount REAL NOT NULL,
        sender_phone TEXT,
        transaction_reference TEXT,
        receipt_image TEXT,
        status TEXT DEFAULT 'pending', -- pending, approved, rejected
        admin_notes TEXT,
        confirmed_by INTEGER,
        confirmed_at DATETIME,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (order_id) REFERENCES orders (id) ON DELETE CASCADE,
        FOREIGN KEY (confirmed_by) REFERENCES admin_users (id)
    );

    -- 10. Inventory Change Logs
    CREATE TABLE IF NOT EXISTS inventory_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        change_type TEXT NOT NULL, -- initial_import, backup_sync, order_sale, manual_adjustment
        quantity_change REAL NOT NULL,
        old_stock REAL NOT NULL,
        new_stock REAL NOT NULL,
        reason TEXT,
        reference_id TEXT,
        user_id INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products (id)
    );

    -- 11. Price Audit Logs
    CREATE TABLE IF NOT EXISTS price_audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        product_id INTEGER NOT NULL,
        old_price REAL NOT NULL,
        new_price REAL NOT NULL,
        reason TEXT,
        user_id INTEGER,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (product_id) REFERENCES products (id)
    );

    -- 12. Activity Logs
    CREATE TABLE IF NOT EXISTS activity_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        action TEXT NOT NULL,
        details TEXT,
        user_id INTEGER,
        ip_address TEXT,
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP
    );
    """)

    # Seed Default Administrator
    cursor.execute("SELECT id FROM admin_users WHERE username = 'admin'")
    if not cursor.fetchone():
        hashed = generate_password_hash("almasa2026@admin")
        cursor.execute("""
        INSERT INTO admin_users (username, password_hash, full_name, email, role)
        VALUES ('admin', ?, 'إدارة الماسة لقطع الغيار', 'admin@almasa-auto.com', 'superadmin')
        """, (hashed,))

    conn.commit()
    conn.close()
    print("Database tables initialized successfully.")

if __name__ == '__main__':
    init_db()
