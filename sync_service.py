import os
import shutil
import sqlite3
import json
from datetime import datetime
from config import Config
from database import get_db

def create_db_backup():
    """Create a timestamped backup of the current database before any major update."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(Config.BACKUPS_FOLDER, f"almasa_db_backup_{timestamp}.db")
    shutil.copy2(Config.DATABASE_PATH, backup_file)
    return backup_file

def sync_from_product_list(products_data, source_name="Uploaded Backup"):
    """
    Synchronize products data from a list of products extracted from backup.
    Preserves historical orders, preserves custom images, updates prices and stock,
    adds new items, and records price changes in price_audit_logs.
    """
    backup_file = create_db_backup()
    conn = get_db()
    cursor = conn.cursor()

    report = {
        "sync_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "source": source_name,
        "backup_created": os.path.basename(backup_file),
        "total_incoming": len(products_data),
        "new_products_added": 0,
        "stock_updated": 0,
        "prices_updated": 0,
        "images_preserved": 0,
        "zero_stock_hidden": 0,
        "price_changes": []
    }

    # Fetch existing products
    cursor.execute("SELECT id, original_id, sale_price, stock_quantity, image_url, is_active FROM products")
    existing_prods = {row['original_id']: dict(row) for row in cursor.fetchall() if row['original_id'] is not None}

    # Fetch brands and categories maps
    cursor.execute("SELECT id, name FROM vehicle_brands")
    brands = {row['name']: row['id'] for row in cursor.fetchall()}
    default_brand_id = list(brands.values())[0] if brands else 1

    cursor.execute("SELECT id, name FROM product_categories")
    categories = {row['name']: row['id'] for row in cursor.fetchall()}
    default_cat_id = list(categories.values())[0] if categories else 1

    for p in products_data:
        orig_id = p.get('id') or p.get('original_id')
        name = p.get('name') or p.get('symbol', '').strip()
        barcode = p.get('barcode', '').strip()
        part_code = p.get('part_code') or p.get('no', '').strip()
        sale_price = float(p.get('sale_price', 0))
        purch_price = float(p.get('purch_price', 0))
        stock = float(p.get('stock') or p.get('calculated_stock', 0))
        group_name = p.get('group_name', '')
        cat_name = p.get('category', '')

        # Determine brand
        brand_id = default_brand_id
        for bname, bid in brands.items():
            if bname.split()[0] in group_name:
                brand_id = bid
                break

        category_id = categories.get(cat_name, default_cat_id)

        if orig_id in existing_prods:
            curr = existing_prods[orig_id]
            pid = curr['id']
            old_price = curr['sale_price']
            old_stock = curr['stock_quantity']
            existing_image = curr['image_url']

            if existing_image:
                report['images_preserved'] += 1

            # Check price update
            if abs(old_price - sale_price) > 0.01:
                cursor.execute("""
                INSERT INTO price_audit_logs (product_id, old_price, new_price, reason)
                VALUES (?, ?, ?, 'تحديث تلقائي للأسعار من مزامنة النسخة الاحتياطية')
                """, (pid, old_price, sale_price))
                report['prices_updated'] += 1
                report['price_changes'].append({
                    "product_id": pid,
                    "name": name,
                    "old_price": old_price,
                    "new_price": sale_price
                })

            # Check stock update
            if abs(old_stock - stock) > 0.01:
                cursor.execute("""
                INSERT INTO inventory_logs (product_id, change_type, quantity_change, old_stock, new_stock, reason)
                VALUES (?, 'backup_sync', ?, ?, ?, 'تحديث رصيد المخزون من النسخة الاحتياطية')
                """, (pid, stock - old_stock, old_stock, stock))
                report['stock_updated'] += 1

            # Public catalog visibility: hide if stock <= 0
            is_active = 1 if stock > 0 else 0
            if stock <= 0 and curr['is_active'] == 1:
                report['zero_stock_hidden'] += 1

            cursor.execute("""
            UPDATE products
            SET name=?, barcode=?, part_code=?, sale_price=?, purch_price=?,
                stock_quantity=?, is_active=?, updated_at=CURRENT_TIMESTAMP
            WHERE id=?
            """, (name, barcode, part_code, sale_price, purch_price, stock, is_active, pid))

        else:
            # New product
            is_active = 1 if stock > 0 else 0
            cursor.execute("""
            INSERT INTO products (
                original_id, name, barcode, part_code, brand_id, category_id,
                sale_price, purch_price, stock_quantity, is_active, is_featured
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
            """, (orig_id, name, barcode, part_code, brand_id, category_id,
                  sale_price, purch_price, stock, is_active))
            new_id = cursor.lastrowid
            report['new_products_added'] += 1

            cursor.execute("""
            INSERT INTO inventory_logs (product_id, change_type, quantity_change, old_stock, new_stock, reason)
            VALUES (?, 'initial_import', ?, 0, ?, 'إضافة صنف جديد من مزامنة النسخة الاحتياطية')
            """, (new_id, stock, stock))

    # Log sync activity
    cursor.execute("""
    INSERT INTO activity_logs (action, details)
    VALUES ('backup_sync', ?)
    """, (json.dumps(report, ensure_ascii=False),))

    conn.commit()
    conn.close()

    # Save sync report
    report_path = os.path.join(Config.BACKUPS_FOLDER, f"sync_report_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(report_path, 'w', encoding='utf-8') as f:
        json.dump(report, f, ensure_ascii=False, indent=2)

    return report
