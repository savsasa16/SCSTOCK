import sqlite3
from datetime import datetime, timedelta
import pytz
import re
from collections import defaultdict
from werkzeug.security import generate_password_hash, check_password_hash
import os
from urllib.parse import urlparse
import json

BKK_TZ = pytz.timezone('Asia/Bangkok')

# Import psycopg2 (ต้องติดตั้ง pip install psycopg2-binary)
try:
    import psycopg2
    # Optional: for fetching rows as dictionaries, similar to sqlite3.Row
    from psycopg2.extras import DictCursor
except ImportError:
    psycopg2 = None
    DictCursor = None
    print("psycopg2 not found. Running in SQLite mode only.")


def get_bkk_time():
    return datetime.now(BKK_TZ)
    
def convert_to_bkk_time(timestamp_obj):
    if timestamp_obj is None:
        return None
    
    # If the timestamp is a string, parse it first
    if isinstance(timestamp_obj, str):
        try:
            # datetime.fromisoformat can handle timezone info if present
            dt_obj = datetime.fromisoformat(timestamp_obj)
        except ValueError:
            # Fallback for non-isoformat strings (if applicable), or return None
            # For consistency, it's better to ensure all timestamps are ISO format.
            return None
    elif isinstance(timestamp_obj, datetime):
        dt_obj = timestamp_obj
    else:
        return None # Not a datetime object or string

    # If datetime object is naive (no timezone info), assume it's UTC and localize
    if dt_obj.tzinfo is None:
        dt_obj = pytz.utc.localize(dt_obj)
    
    # Convert to BKK timezone
    return dt_obj.astimezone(BKK_TZ)    

def get_db_connection():
    # ตรวจสอบว่ามี DATABASE_URL Environment Variable หรือไม่ (สำหรับ Production บน Render)
    DATABASE_URL = os.environ.get('DATABASE_URL')
    
    if DATABASE_URL and psycopg2:
        # Connect to PostgreSQL
        try:
            url = urlparse(DATABASE_URL)
            conn = psycopg2.connect(
                database=url.path[1:],
                user=url.username,
                password=url.password,
                host=url.hostname,
                port=url.port,
                sslmode='require', # For Render, usually requires SSL
                cursor_factory=DictCursor # <--- เพิ่มบรรทัดนี้เข้ามา
            )
            print("Connected to PostgreSQL database!")
            return conn
        except Exception as e:
            print(f"Error connecting to PostgreSQL: {e}")
            raise # Re-raise error if PostgreSQL is expected
    else:
        # Connect to SQLite (for Local Development)
        print("Connected to SQLite database (local development)!")
        conn = sqlite3.connect('inventory.db')
        conn.row_factory = sqlite3.Row # This allows accessing columns by name (e.g., row['column_name'])
        return conn

# Helper function to get date format for SQL query based on DB type
def get_sql_date_format_for_query(column_name):
    if os.environ.get('DATABASE_URL'): # If running on Render with PostgreSQL
        return f"TO_CHAR({column_name}, 'YYYY-MM-DD')"
    else: # If running locally with SQLite
        return f"STRFTIME('%Y-%m-%d', {column_name})"

def init_db(conn):
    cursor = conn.cursor()
    
    is_postgres = "psycopg2" in str(type(conn)) # จะคืนค่า True หาก conn เป็น psycopg2 connection

    # Commission Programs Table (เปลี่ยนชื่อจาก daily_commissions)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS commission_programs (
                id SERIAL PRIMARY KEY,
                start_date DATE NOT NULL,
                end_date DATE NULL, -- NULL หมายถึงไม่มีวันสิ้นสุด
                item_type VARCHAR(50) NOT NULL,
                item_id INTEGER NOT NULL,
                commission_amount_per_item REAL NOT NULL,
                user_id INTEGER NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                UNIQUE(item_type, item_id, start_date), -- ป้องกันการสร้างซ้ำในวันเริ่มต้นเดียวกัน
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS commission_programs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                start_date TEXT NOT NULL,
                end_date TEXT NULL, -- NULL หมายถึงไม่มีวันสิ้นสุด
                item_type TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                commission_amount_per_item REAL NOT NULL,
                user_id INTEGER NULL,
                created_at TEXT NOT NULL,
                UNIQUE(item_type, item_id, start_date)
            );
        """)

    # NEW: Commission Summary Log Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS commission_summary_log (
                id SERIAL PRIMARY KEY,
                summary_date DATE NOT NULL UNIQUE,
                details_json TEXT NOT NULL, -- เก็บข้อมูลสรุปเป็น JSON
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS commission_summary_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                summary_date TEXT NOT NULL UNIQUE,
                details_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)

    # Movements Deletion
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deleted_movements (
                id SERIAL PRIMARY KEY,
                original_table VARCHAR(255) NOT NULL,
                original_movement_id INTEGER NOT NULL,
                item_details TEXT NOT NULL,
                movement_type VARCHAR(50) NOT NULL,
                quantity_change INTEGER NOT NULL,
                deleted_by_user_id INTEGER NULL,
                deleted_at TIMESTAMP WITH TIME ZONE NOT NULL,
                original_data_json TEXT NULL,
                FOREIGN KEY (deleted_by_user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS deleted_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                original_table TEXT NOT NULL,
                original_movement_id INTEGER NOT NULL,
                item_details TEXT NOT NULL,
                movement_type TEXT NOT NULL,
                quantity_change INTEGER NOT NULL,
                deleted_by_user_id INTEGER NULL,
                deleted_at TEXT NOT NULL,
                original_data_json TEXT NULL,
                FOREIGN KEY (deleted_by_user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)

    if is_postgres:
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id SERIAL PRIMARY KEY,
            user_id INTEGER NULL,
            timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
            endpoint VARCHAR(255) NOT NULL,
            method VARCHAR(10) NOT NULL,
            url VARCHAR(2048) NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS activity_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER NULL,
            timestamp TEXT NOT NULL,
            endpoint TEXT NOT NULL,
            method TEXT NOT NULL,
            url TEXT NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)

    # NEW: Tire Cost History Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_cost_history (
                id SERIAL PRIMARY KEY,
                tire_id INTEGER NOT NULL,
                changed_at TIMESTAMP WITH TIME ZONE NOT NULL,
                old_cost_sc REAL NULL,
                new_cost_sc REAL NULL,
                user_id INTEGER NULL,
                notes TEXT NULL, -- เผื่อต้องการใส่หมายเหตุ
                FOREIGN KEY (tire_id) REFERENCES tires(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_cost_history (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tire_id INTEGER NOT NULL,
                changed_at TEXT NOT NULL,
                old_cost_sc REAL NULL,
                new_cost_sc REAL NULL,
                user_id INTEGER NULL,
                notes TEXT NULL,
                FOREIGN KEY (tire_id) REFERENCES tires(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)

    # Promotions Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promotions (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                type VARCHAR(255) NOT NULL,
                value1 FLOAT NOT NULL,
                value2 FLOAT NULL,
                is_active BOOLEAN DEFAULT TRUE,
                is_deleted BOOLEAN DEFAULT FALSE, -- Corrected default for PostgreSQL
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS promotions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                type TEXT NOT NULL,
                value1 REAL NOT NULL,
                value2 REAL NULL,
                is_active BOOLEAN DEFAULT 1,
                is_deleted BOOLEAN DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)

    # Users Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                username VARCHAR(255) UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role VARCHAR(50) NOT NULL DEFAULT 'viewer'
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL DEFAULT 'viewer'
            );
        """)

    # เพิ่มตารางประกาศ Announcment     
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id SERIAL PRIMARY KEY,
                title VARCHAR(255) NOT NULL,
                content TEXT NOT NULL,
                is_active BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS announcements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                content TEXT NOT NULL,
                is_active BOOLEAN DEFAULT 0,
                created_at TEXT NOT NULL
            );
        """)

    # Sales Channels Table (ใหม่)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sales_channels (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE
            );
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sales_channels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
        """)
    
    # Online Platforms Table (ใหม่)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS online_platforms (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE
            );
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS online_platforms (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
        """)

    # Wholesale Customers Table (ใหม่)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wholesale_customers (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE
            );
        """)
    else:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wholesale_customers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE
            );
        """)

    # Tires Table (เพิ่ม is_deleted)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tires (
                id SERIAL PRIMARY KEY,
                brand VARCHAR(255) NOT NULL,
                model VARCHAR(255) NOT NULL,
                size VARCHAR(255) NOT NULL,
                quantity INTEGER DEFAULT 0,
                cost_sc FLOAT NULL, 
                cost_dunlop FLOAT NULL,
                cost_online FLOAT NULL,
                wholesale_price1 FLOAT NULL,
                wholesale_price2 FLOAT NULL,
                price_per_item FLOAT NOT NULL,
                promotion_id INTEGER NULL,
                year_of_manufacture VARCHAR(255) NULL,
                is_deleted BOOLEAN DEFAULT FALSE, -- ADDED FOR SOFT DELETE
                UNIQUE(brand, model, size),
                FOREIGN KEY (promotion_id) REFERENCES promotions(id) ON DELETE SET NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tires (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                size TEXT NOT NULL,
                quantity INTEGER DEFAULT 0,
                cost_sc REAL NULL, 
                cost_dunlop REAL NULL,
                cost_online REAL NULL,
                wholesale_price1 REAL NULL,
                wholesale_price2 REAL NULL,
                price_per_item REAL NOT NULL,
                promotion_id INTEGER NULL,
                year_of_manufacture INTEGER NULL,
                is_deleted BOOLEAN DEFAULT 0, -- ADDED FOR SOFT DELETE
                UNIQUE(brand, model, size),
                FOREIGN KEY (promotion_id) REFERENCES promotions(id) ON DELETE SET NULL
            );
        """)
        
    # Notifications Table (NEW)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id SERIAL PRIMARY KEY,
                message TEXT NOT NULL,
                user_id INTEGER NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                is_read BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                user_id INTEGER NULL,
                created_at TEXT NOT NULL,
                is_read BOOLEAN DEFAULT 0,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)

    # Wheels Table (เพิ่ม image_filename ให้ยาวขึ้น และ is_deleted)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheels (
                id SERIAL PRIMARY KEY,
                brand VARCHAR(255) NOT NULL,
                model VARCHAR(255) NOT NULL,
                diameter FLOAT NOT NULL,
                pcd VARCHAR(255) NOT NULL,
                width FLOAT NOT NULL,
                et INTEGER NULL,
                color VARCHAR(255) NULL,
                quantity INTEGER DEFAULT 0,
                cost FLOAT NULL, 
                cost_online FLOAT NULL,
                wholesale_price1 FLOAT NULL,
                wholesale_price2 FLOAT NULL,
                retail_price FLOAT NOT NULL,
                image_filename VARCHAR(500) NULL,
                is_deleted BOOLEAN DEFAULT FALSE, -- ADDED FOR SOFT DELETE
                UNIQUE(brand, model, diameter, pcd, width, et, color)
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheels (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                diameter REAL NOT NULL,
                pcd TEXT NOT NULL,
                width REAL NOT NULL,
                et INTEGER NULL,
                color TEXT NULL,
                quantity INTEGER DEFAULT 0,
                cost REAL NULL, 
                cost_online REAL NULL,
                wholesale_price1 REAL NULL,
                wholesale_price2 REAL NULL,
                retail_price REAL NOT NULL,
                image_filename TEXT NULL,
                is_deleted BOOLEAN DEFAULT 0, -- ADDED FOR SOFT DELETE
                UNIQUE(brand, model, diameter, pcd, width, et, color)
            );
        """)

    # Tire Movements Table (เพิ่มคอลัมน์ใหม่สำหรับ Tracking)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_movements (
                id SERIAL PRIMARY KEY,
                tire_id INTEGER NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                type VARCHAR(50) NOT NULL, -- IN, OUT, RETURN
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                image_filename VARCHAR(500) NULL,
                user_id INTEGER NULL,
                -- NEW COLUMNS FOR DETAILED TRACKING
                channel_id INTEGER NULL, -- หน้าร้าน, ออนไลน์, ค้าส่ง, ซื้อเข้า, รับคืน
                online_platform_id INTEGER NULL, -- Shopee, Lazada, etc. (สำหรับ OUT/RETURN จากออนไลน์)
                wholesale_customer_id INTEGER NULL, -- ร้าน 1, ร้าน 2 (สำหรับ OUT ค้าส่ง)
                return_customer_type VARCHAR(50) NULL, -- 'หน้าร้านลูกค้า', 'หน้าร้านร้านยาง' (สำหรับ RETURN หน้าร้าน)
                commission_amount REAL NULL,
                FOREIGN KEY (tire_id) REFERENCES tires(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (channel_id) REFERENCES sales_channels(id),
                FOREIGN KEY (online_platform_id) REFERENCES online_platforms(id),
                FOREIGN KEY (wholesale_customer_id) REFERENCES wholesale_customers(id)
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tire_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL, -- IN, OUT, RETURN
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                image_filename TEXT NULL,
                user_id INTEGER NULL,
                commission_amount REAL NULL,
                -- NEW COLUMNS FOR DETAILED TRACKING
                channel_id INTEGER NULL, 
                online_platform_id INTEGER NULL,
                wholesale_customer_id INTEGER NULL,
                return_customer_type TEXT NULL,

                FOREIGN KEY (tire_id) REFERENCES tires(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (channel_id) REFERENCES sales_channels(id),
                FOREIGN KEY (online_platform_id) REFERENCES online_platforms(id),
                FOREIGN KEY (wholesale_customer_id) REFERENCES wholesale_customers(id)
            );
        """)

    # Wheel Movements Table (เพิ่มคอลัมน์ใหม่สำหรับ Tracking)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_movements (
                id SERIAL PRIMARY KEY,
                wheel_id INTEGER NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                type VARCHAR(50) NOT NULL, -- IN, OUT, RETURN
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                image_filename VARCHAR(500) NULL,
                user_id INTEGER NULL,
                commission_amount REAL NULL,
                -- NEW COLUMNS FOR DETAILED TRACKING
                channel_id INTEGER NULL, 
                online_platform_id INTEGER NULL,
                wholesale_customer_id INTEGER NULL,
                return_customer_type VARCHAR(50) NULL,
                FOREIGN KEY (wheel_id) REFERENCES wheels(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (channel_id) REFERENCES sales_channels(id),
                FOREIGN KEY (online_platform_id) REFERENCES online_platforms(id),
                FOREIGN KEY (wholesale_customer_id) REFERENCES wholesale_customers(id)
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wheel_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL, -- IN, OUT, RETURN
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                image_filename TEXT NULL,
                user_id INTEGER NULL,
                commission_amount REAL NULL,
                -- NEW COLUMNS FOR DETAILED TRACKING
                channel_id INTEGER NULL, 
                online_platform_id INTEGER NULL,
                wholesale_customer_id INTEGER NULL,
                return_customer_type TEXT NULL,

                FOREIGN KEY (wheel_id) REFERENCES wheels(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (channel_id) REFERENCES sales_channels(id),
                FOREIGN KEY (online_platform_id) REFERENCES online_platforms(id),
                FOREIGN KEY (wholesale_customer_id) REFERENCES wholesale_customers(id)
            );
        """)

    # Wheel Fitments Table
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_fitments (
                id SERIAL PRIMARY KEY,
                wheel_id INTEGER NOT NULL,
                brand VARCHAR(255) NOT NULL,
                model VARCHAR(255) NOT NULL,
                year_start INTEGER NOT NULL,
                year_end INTEGER NULL,
                UNIQUE(wheel_id, brand, model, year_start, year_end),
                FOREIGN KEY (wheel_id) REFERENCES wheels(id) ON DELETE CASCADE
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_fitments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wheel_id INTEGER NOT NULL,
                brand TEXT NOT NULL,
                model TEXT NOT NULL,
                year_start INTEGER NOT NULL,
                year_end INTEGER NULL,
                UNIQUE(wheel_id, brand, model, year_start, year_end),
                FOREIGN KEY (wheel_id) REFERENCES wheels(id) ON DELETE CASCADE
            );
        """)

    # Feedback Table Add HERE
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id SERIAL PRIMARY KEY,
                user_id INTEGER NULL,
                feedback_type VARCHAR(50) NOT NULL, -- e.g., 'Bug', 'Suggestion', 'Other'
                message TEXT NOT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'ใหม่', -- e.g., 'New', 'In Progress', 'Done'
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NULL,
                feedback_type TEXT NOT NULL,
                message TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'ใหม่',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
            );
        """)    

    # Barcodes Table for Tires
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_barcodes (
                id SERIAL PRIMARY KEY,
                tire_id INTEGER NOT NULL,
                barcode_string VARCHAR(255) NOT NULL UNIQUE,
                is_primary_barcode BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (tire_id) REFERENCES tires(id) ON DELETE CASCADE
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_barcodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tire_id INTEGER NOT NULL,
                barcode_string TEXT NOT NULL UNIQUE,
                is_primary_barcode BOOLEAN DEFAULT 0,
                FOREIGN KEY (tire_id) REFERENCES tires(id) ON DELETE CASCADE
            );
        """)

    # Barcodes Table for Wheels
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_barcodes (
                id SERIAL PRIMARY KEY,
                wheel_id INTEGER NOT NULL,
                barcode_string VARCHAR(255) NOT NULL UNIQUE,
                is_primary_barcode BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (wheel_id) REFERENCES wheels(id) ON DELETE CASCADE
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_barcodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wheel_id INTEGER NOT NULL,
                barcode_string TEXT NOT NULL UNIQUE,
                is_primary_barcode BOOLEAN DEFAULT 0,
                FOREIGN KEY (wheel_id) REFERENCES wheels(id) ON DELETE CASCADE
            );
        """)

    # Automatic deleted Activity LOGS
    if is_postgres:
            cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key VARCHAR(255) PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)
    else: # SQLite
            cursor.execute("""
        CREATE TABLE IF NOT EXISTS app_settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
    """)

     # Daily Reconciliations Table (NEW)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_reconciliations (
                id SERIAL PRIMARY KEY,
                reconciliation_date DATE NOT NULL UNIQUE,
                manager_id INTEGER NOT NULL,
                status VARCHAR(50) NOT NULL DEFAULT 'pending', -- e.g., 'pending', 'completed'
                manager_ledger_json TEXT NULL,
                system_snapshot_json TEXT NULL,
                created_at TIMESTAMP WITH TIME ZONE NOT NULL,
                completed_at TIMESTAMP WITH TIME ZONE NULL,
                FOREIGN KEY (manager_id) REFERENCES users(id)
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS daily_reconciliations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                reconciliation_date TEXT NOT NULL UNIQUE,
                manager_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                manager_ledger_json TEXT NULL,
                system_snapshot_json TEXT NULL,
                created_at TEXT NOT NULL,
                completed_at TEXT NULL,
                FOREIGN KEY (manager_id) REFERENCES users(id)
            );
        """)

    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spare_part_categories (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL UNIQUE,
                parent_id INTEGER NULL, -- สำหรับหมวดหมู่ย่อย (self-referencing)
                FOREIGN KEY (parent_id) REFERENCES spare_part_categories(id) ON DELETE CASCADE
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spare_part_categories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                parent_id INTEGER NULL,
                FOREIGN KEY (parent_id) REFERENCES spare_part_categories(id) ON DELETE CASCADE
            );
        """)

    # ตารางอะไหล่ (Spare Parts)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spare_parts (
                id SERIAL PRIMARY KEY,
                name VARCHAR(255) NOT NULL,
                part_number VARCHAR(255) UNIQUE NULL, -- รหัสอะไหล่ (ถ้ามี)
                brand VARCHAR(255) NULL,
                description TEXT NULL,
                quantity INTEGER DEFAULT 0,
                cost REAL NULL,
                retail_price REAL NOT NULL,
                wholesale_price1 REAL NULL,
                wholesale_price2 REAL NULL,
                cost_online REAL NULL,
                image_filename VARCHAR(500) NULL,
                is_deleted BOOLEAN DEFAULT FALSE,
                category_id INTEGER NULL, -- Foreign Key ไปที่ spare_part_categories
                FOREIGN KEY (category_id) REFERENCES spare_part_categories(id) ON DELETE SET NULL
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spare_parts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                part_number TEXT UNIQUE NULL,
                brand TEXT NULL,
                description TEXT NULL,
                quantity INTEGER DEFAULT 0,
                cost REAL NULL,
                retail_price REAL NOT NULL,
                wholesale_price1 REAL NULL,
                wholesale_price2 REAL NULL,
                cost_online REAL NULL,
                image_filename TEXT NULL,
                is_deleted BOOLEAN DEFAULT 0,
                category_id INTEGER NULL,
                FOREIGN KEY (category_id) REFERENCES spare_part_categories(id) ON DELETE SET NULL
            );
        """)

    # ตารางบันทึกการเคลื่อนไหวอะไหล่ (Spare Part Movements)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spare_part_movements (
                id SERIAL PRIMARY KEY,
                spare_part_id INTEGER NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                type VARCHAR(50) NOT NULL, -- IN, OUT, RETURN
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                image_filename VARCHAR(500) NULL,
                user_id INTEGER NULL,
                channel_id INTEGER NULL,
                online_platform_id INTEGER NULL,
                wholesale_customer_id INTEGER NULL,
                commission_amount REAL NULL,
                return_customer_type VARCHAR(50) NULL,
                FOREIGN KEY (spare_part_id) REFERENCES spare_parts(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (channel_id) REFERENCES sales_channels(id),
                FOREIGN KEY (online_platform_id) REFERENCES online_platforms(id),
                FOREIGN KEY (wholesale_customer_id) REFERENCES wholesale_customers(id)
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spare_part_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spare_part_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL, -- IN, OUT, RETURN
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                image_filename TEXT NULL,
                user_id INTEGER NULL,
                channel_id INTEGER NULL,
                online_platform_id INTEGER NULL,
                commission_amount REAL NULL,
                wholesale_customer_id INTEGER NULL,
                return_customer_type TEXT NULL,
                FOREIGN KEY (spare_part_id) REFERENCES spare_parts(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (channel_id) REFERENCES sales_channels(id),
                FOREIGN KEY (online_platform_id) REFERENCES online_platforms(id),
                FOREIGN KEY (wholesale_customer_id) REFERENCES wholesale_customers(id)
            );
        """)

    # ตาราง Barcode สำหรับอะไหล่ (Spare Part Barcodes)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spare_part_barcodes (
                id SERIAL PRIMARY KEY,
                spare_part_id INTEGER NOT NULL,
                barcode_string VARCHAR(255) NOT NULL UNIQUE,
                is_primary_barcode BOOLEAN DEFAULT FALSE,
                FOREIGN KEY (spare_part_id) REFERENCES spare_parts(id) ON DELETE CASCADE
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS spare_part_barcodes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spare_part_id INTEGER NOT NULL,
                barcode_string TEXT NOT NULL UNIQUE,
                is_primary_barcode BOOLEAN DEFAULT 0,
                FOREIGN KEY (spare_part_id) REFERENCES spare_parts(id) ON DELETE CASCADE
            );
        """)

    # --- START: NEW INDEX CREATION CODE TO BE ADDED ---
    print("Creating necessary indexes for performance...")

    # activity_logs
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_timestamp ON activity_logs(timestamp);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_activity_logs_timestamp ON activity_logs(timestamp);")

    # promotions
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_promotions_is_active_is_deleted ON promotions(is_active, is_deleted);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_promotions_is_active_is_deleted ON promotions(is_active, is_deleted);")

    # tires
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tires_brand_model_size ON tires(brand, model, size);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tires_is_deleted ON tires(is_deleted);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tires_brand_model_size ON tires(brand, model, size);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tires_is_deleted ON tires(is_deleted);")

    # tire_movements
    # idx_tire_movements_tire_id is already in the original file
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tire_movements_timestamp ON tire_movements(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tire_movements_wholesale_customer_id ON tire_movements(wholesale_customer_id);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tire_movements_timestamp ON tire_movements(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tire_movements_wholesale_customer_id ON tire_movements(wholesale_customer_id);")

    # wheels
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheels_brand_model_diameter_pcd_width_et_color ON wheels(brand, model, diameter, pcd, width, et, color);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheels_is_deleted ON wheels(is_deleted);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheels_brand_model_diameter_pcd_width_et_color ON wheels(brand, model, diameter, pcd, width, et, color);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheels_is_deleted ON wheels(is_deleted);")

    # wheel_movements
    # idx_wheel_movements_wheel_id is already in the original file
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheel_movements_timestamp ON wheel_movements(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheel_movements_wholesale_customer_id ON wheel_movements(wholesale_customer_id);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheel_movements_timestamp ON wheel_movements(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheel_movements_wholesale_customer_id ON wheel_movements(wholesale_customer_id);")

    # wheel_fitments
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheel_fitments_wheel_id ON wheel_fitments(wheel_id);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheel_fitments_wheel_id ON wheel_fitments(wheel_id);")

    # notifications
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_created_at ON notifications(created_at DESC);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_notifications_is_read ON notifications(is_read);")

    # tire_barcodes
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tire_barcodes_barcode_string ON tire_barcodes(barcode_string);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_tire_barcodes_barcode_string ON tire_barcodes(barcode_string);")

    # wheel_barcodes
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheel_barcodes_barcode_string ON wheel_barcodes(barcode_string);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wheel_barcodes_barcode_string ON wheel_barcodes(barcode_string);")

    # spare_part_categories
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_part_categories_parent_id ON spare_part_categories(parent_id);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_part_categories_parent_id ON spare_part_categories(parent_id);")

    # spare_parts
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_parts_name_part_number_brand ON spare_parts(name, part_number, brand);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_parts_category_id ON spare_parts(category_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_parts_is_deleted ON spare_parts(is_deleted);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_parts_name_part_number_brand ON spare_parts(name, part_number, brand);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_parts_category_id ON spare_parts(category_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_parts_is_deleted ON spare_parts(is_deleted);")

    # spare_part_movements
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_part_movements_spare_part_id ON spare_part_movements(spare_part_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_part_movements_timestamp ON spare_part_movements(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_part_movements_wholesale_customer_id ON spare_part_movements(wholesale_customer_id);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_part_movements_spare_part_id ON spare_part_movements(spare_part_id);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_part_movements_timestamp ON spare_part_movements(timestamp);")
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_part_movements_wholesale_customer_id ON spare_part_movements(wholesale_customer_id);")

    # spare_part_barcodes
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_part_barcodes_barcode_string ON spare_part_barcodes(barcode_string);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_spare_part_barcodes_barcode_string ON spare_part_barcodes(barcode_string);")

    # feedback
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at DESC);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_feedback_created_at ON feedback(created_at DESC);")

    # announcements
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_announcements_is_active_created_at ON announcements(is_active, created_at DESC);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_announcements_is_active_created_at ON announcements(is_active, created_at DESC);")

    # sales_channels
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_channels_name ON sales_channels(name);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_sales_channels_name ON sales_channels(name);")

    # online_platforms
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_online_platforms_name ON online_platforms(name);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_online_platforms_name ON online_platforms(name);")

    # wholesale_customers
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wholesale_customers_name ON wholesale_customers(name);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_wholesale_customers_name ON wholesale_customers(name);")

    # daily_reconciliations
    if is_postgres:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_reconciliations_date ON daily_reconciliations(reconciliation_date);")
    else:
        cursor.execute("CREATE INDEX IF NOT EXISTS idx_daily_reconciliations_date ON daily_reconciliations(reconciliation_date);")

    # --- END NEW INDEX CREATION CODE ---
    
    # --- INSERT DEFAULT DATA (MOVED HERE TO ENSURE COMMIT) ---
    # เพิ่มข้อมูลเริ่มต้นสำหรับ sales_channels (ถ้ายังไม่มี)
    try:
        if is_postgres:
            cursor.execute("INSERT INTO sales_channels (name) VALUES ('หน้าร้าน') ON CONFLICT (name) DO NOTHING;")
            cursor.execute("INSERT INTO sales_channels (name) VALUES ('ออนไลน์') ON CONFLICT (name) DO NOTHING;")
            cursor.execute("INSERT INTO sales_channels (name) VALUES ('ค้าส่ง') ON CONFLICT (name) DO NOTHING;")
            cursor.execute("INSERT INTO sales_channels (name) VALUES ('ซื้อเข้า') ON CONFLICT (name) DO NOTHING;")
            cursor.execute("INSERT INTO sales_channels (name) VALUES ('รับคืน') ON CONFLICT (name) DO NOTHING;")
        else:
            cursor.execute("INSERT OR IGNORE INTO sales_channels (name) VALUES ('หน้าร้าน');")
            cursor.execute("INSERT OR IGNORE INTO sales_channels (name) VALUES ('ออนไลน์');")
            cursor.execute("INSERT OR IGNORE INTO sales_channels (name) VALUES ('ค้าส่ง');")
            cursor.execute("INSERT OR IGNORE INTO sales_channels (name) VALUES ('ซื้อเข้า');")
            cursor.execute("INSERT OR IGNORE INTO sales_channels (name) VALUES ('รับคืน');")
    except Exception as e:
        print(f"Error inserting default sales channels: {e}")
        conn.rollback() # Rollback if default channels insertion fails
        # It's better to just log and continue, as failure here shouldn't stop table creation
    
    # เพิ่มข้อมูลเริ่มต้นสำหรับ online_platforms (ถ้ายังไม่มี)
    try:
        if is_postgres:
            cursor.execute("INSERT INTO online_platforms (name) VALUES ('Shopee') ON CONFLICT (name) DO NOTHING;")
            cursor.execute("INSERT INTO online_platforms (name) VALUES ('Lazada') ON CONFLICT (name) DO NOTHING;")
            cursor.execute("INSERT INTO online_platforms (name) VALUES ('TikTok') ON CONFLICT (name) DO NOTHING;")
            cursor.execute("INSERT INTO online_platforms (name) VALUES ('Facebook') ON CONFLICT (name) DO NOTHING;")
            cursor.execute("INSERT INTO online_platforms (name) VALUES ('Line@') ON CONFLICT (name) DO NOTHING;")
        else:
            cursor.execute("INSERT OR IGNORE INTO online_platforms (name) VALUES ('Shopee');")
            cursor.execute("INSERT OR IGNORE INTO online_platforms (name) VALUES ('Lazada');")
            cursor.execute("INSERT OR IGNORE INTO online_platforms (name) VALUES ('TikTok');")
            cursor.execute("INSERT OR IGNORE INTO online_platforms (name) VALUES ('Facebook');")
            cursor.execute("INSERT OR IGNORE INTO online_platforms (name) VALUES ('Line@');")
    except Exception as e:
        print(f"Error inserting default online platforms: {e}")
        conn.rollback() # Rollback if default platforms insertion fails
        
    # เพิ่มข้อมูลเริ่มต้นสำหรับ wholesale_customers (หากต้องการมีลูกค้าตัวอย่าง)
    try:
        if is_postgres:
            cursor.execute("INSERT INTO wholesale_customers (name) VALUES ('ร้านตัวอย่าง 1') ON CONFLICT (name) DO NOTHING;")
            cursor.execute("INSERT INTO wholesale_customers (name) VALUES ('ร้านตัวอย่าง 2') ON CONFLICT (name) DO NOTHING;")
        else:
            cursor.execute("INSERT OR IGNORE INTO wholesale_customers (name) VALUES ('ร้านตัวอย่าง 1');")
            cursor.execute("INSERT OR IGNORE INTO wholesale_customers (name) VALUES ('ร้านตัวอย่าง 2');")
    except Exception as e:
        print(f"Error inserting default wholesale customers: {e}")
        conn.rollback() # Rollback if default customers insertion fails



    conn.commit() # <--- IMPORTANT: COMMIT ALL CHANGES AFTER CREATING TABLES AND INSERTING DEFAULTS
    print("Database schema and default data initialized successfully.")

# --- User Model ---
class User:
    def __init__(self, id, username, password, role):
        self.id = id
        self.username = username
        self.password = password
        self.role = role

    @staticmethod
    def get(conn, user_id):
        cursor = conn.cursor()
        if "psycopg2" in str(type(conn)):
            cursor.execute("SELECT id, username, password, role FROM users WHERE id = %s", (user_id,))
        else:
            cursor.execute("SELECT id, username, password, role FROM users WHERE id = ?", (user_id,))
        user_data = cursor.fetchone()
        if user_data:
            if isinstance(user_data, sqlite3.Row):
                user_data = dict(user_data)
            return User(user_data['id'], user_data['username'], user_data['password'], user_data['role'])
        return None

    @staticmethod
    def get_by_username(conn, username):
        cursor = conn.cursor()
        if "psycopg2" in str(type(conn)):
            cursor.execute("SELECT id, username, password, role FROM users WHERE username = %s", (username,))
        else:
            cursor.execute("SELECT id, username, password, role FROM users WHERE username = ?", (username,))
        user_data = cursor.fetchone()
        if user_data:
            if isinstance(user_data, sqlite3.Row):
                user_data = dict(user_data)
            return User(user_data['id'], user_data['username'], user_data['password'], user_data['role'])
        return None
    
    def is_active(self):
        return True

    def is_authenticated(self):
        return True

    def is_anonymous(self):
        return False

    def get_id(self):
        return str(self.id)

    def is_admin(self):
        return self.role == 'admin'

    def can_edit(self):
        return self.role in ['admin', 'editor']

    def can_view(self):
        return self.role in ['admin', 'editor', 'viewer']

# --- User Management Functions ---
def add_user(conn, username, password, role='viewer'):
    hashed_password = generate_password_hash(password)
    cursor = conn.cursor() 
    try:
        if "psycopg2" in str(type(conn)):
            cursor.execute("INSERT INTO users (username, password, role) VALUES (%s, %s, %s) RETURNING id", (username, hashed_password, role))
            user_id = cursor.fetchone()['id']
        else: # สำหรับ SQLite
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, hashed_password, role))
            user_id = cursor.lastrowid
        conn.commit()
        return user_id
    except (sqlite3.IntegrityError, Exception) as e:
        if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
            return None
        else:
            raise

def get_all_users(conn):
    if "psycopg2" in str(type(conn)):
        cursor = conn.cursor() 
        cursor.execute("SELECT id, username, role FROM users")
        users = cursor.fetchall()
    else: # สำหรับ SQLite
        users = conn.execute("SELECT id, username, role FROM users").fetchall()
    return users

def update_user_role(conn, user_id, new_role):
    try:
        if "psycopg2" in str(type(conn)):
            cursor = conn.cursor() 
            cursor.execute("UPDATE users SET role = %s WHERE id = %s", (new_role, user_id))
        else: # สำหรับ SQLite
            conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        conn.commit()
        return True
    except Exception as e:
        conn.rollback()
        print(f"Error updating user role: {e}")
        return False

def delete_user(conn, user_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    else:
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()

# --- Sales Channel, Online Platform, Wholesale Customer Functions (ใหม่) ---
def get_sales_channel_id(conn, name):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT id FROM sales_channels WHERE name = %s", (name,))
    else:
        cursor.execute("SELECT id FROM sales_channels WHERE name = ?", (name,))
    result = cursor.fetchone()
    # Handle DictRow for psycopg2
    if result and isinstance(result, dict):
        return result['id']
    elif result and hasattr(result, '__getitem__'): # For SQLite Row
        return result['id']
    return None

def get_sales_channel_name(conn, channel_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT name FROM sales_channels WHERE id = %s", (channel_id,))
    else:
        cursor.execute("SELECT name FROM sales_channels WHERE id = ?", (channel_id,))
    result = cursor.fetchone()
    if result and isinstance(result, dict):
        return result['name']
    elif result and hasattr(result, '__getitem__'):
        return result['name']
    return None

def get_all_sales_channels(conn):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT id, name FROM sales_channels ORDER BY name")
    else:
        cursor.execute("SELECT id, name FROM sales_channels ORDER BY name")
    # Ensure all rows are converted to dict for consistency
    return [dict(row) if not isinstance(row, dict) else row for row in cursor.fetchall()]

def add_online_platform(conn, name):
    cursor = conn.cursor()
    try:
        if "psycopg2" in str(type(conn)):
            cursor.execute("INSERT INTO online_platforms (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id;", (name,))
            platform_id = cursor.fetchone()
            conn.commit() # Commit here for RETURNING clause and changes
            return platform_id['id'] if platform_id else get_online_platform_id(conn, name)
        else:
            cursor.execute("INSERT OR IGNORE INTO online_platforms (name) VALUES (?)", (name,))
            conn.commit() # Commit here for SQLite's IGNORE
            return cursor.lastrowid if cursor.lastrowid else get_online_platform_id(conn, name)
    except Exception as e:
        conn.rollback()
        print(f"Error adding online platform: {e}")
        return None

def get_online_platform_id(conn, name):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT id FROM online_platforms WHERE name = %s", (name,))
    else:
        cursor.execute("SELECT id FROM online_platforms WHERE name = ?", (name,))
    result = cursor.fetchone()
    if result and isinstance(result, dict):
        return result['id']
    elif result and hasattr(result, '__getitem__'):
        return result['id']
    return None

def get_online_platform_name(conn, platform_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT name FROM online_platforms WHERE id = %s", (platform_id,))
    else:
        cursor.execute("SELECT name FROM online_platforms WHERE id = ?", (platform_id,))
    result = cursor.fetchone()
    if result and isinstance(result, dict):
        return result['name']
    elif result and hasattr(result, '__getitem__'):
        return result['name']
    return None

def get_all_online_platforms(conn):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT id, name FROM online_platforms ORDER BY name")
    else:
        cursor.execute("SELECT id, name FROM online_platforms ORDER BY name")
    return [dict(row) if not isinstance(row, dict) else row for row in cursor.fetchall()]

def add_wholesale_customer(conn, name):
    cursor = conn.cursor()
    try:
        if "psycopg2" in str(type(conn)):
            cursor.execute("INSERT INTO wholesale_customers (name) VALUES (%s) ON CONFLICT (name) DO NOTHING RETURNING id;", (name,))
            customer_id = cursor.fetchone()
            conn.commit() # Commit here for RETURNING clause and changes
            return customer_id['id'] if customer_id else get_wholesale_customer_id(conn, name)
        else:
            cursor.execute("INSERT OR IGNORE INTO wholesale_customers (name) VALUES (?)", (name,))
            conn.commit() # Commit here for SQLite's IGNORE
            return cursor.lastrowid if cursor.lastrowid else get_wholesale_customer_id(conn, name)
    except Exception as e:
        conn.rollback()
        print(f"Error adding wholesale customer: {e}")
        return None

def get_wholesale_customer_id(conn, name):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT id FROM wholesale_customers WHERE name = %s", (name,))
    else:
        cursor.execute("SELECT id FROM wholesale_customers WHERE name = ?", (name,))
    result = cursor.fetchone()
    if result and isinstance(result, dict):
        return result['id']
    elif result and hasattr(result, '__getitem__'):
        return result['id']
    return None

def get_wholesale_customer_name(conn, customer_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT name FROM wholesale_customers WHERE id = %s", (customer_id,))
    else:
        cursor.execute("SELECT name FROM wholesale_customers WHERE id = ?", (customer_id,))
    result = cursor.fetchone()
    if result and isinstance(result, dict):
        return result['name']
    elif result and hasattr(result, '__getitem__'):
        return result['name']
    return None

def get_all_wholesale_customers(conn):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT id, name FROM wholesale_customers ORDER BY name")
    else:
        cursor.execute("SELECT id, name FROM wholesale_customers ORDER BY name")
    return [dict(row) if not isinstance(row, dict) else row for row in cursor.fetchall()]

def add_spare_part_category(conn, name, parent_id=None):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    try:
        if is_postgres:
            cursor.execute("INSERT INTO spare_part_categories (name, parent_id) VALUES (%s, %s) RETURNING id", (name, parent_id))
            category_id = cursor.fetchone()['id']
        else:
            cursor.execute("INSERT INTO spare_part_categories (name, parent_id) VALUES (?, ?)", (name, parent_id))
            category_id = cursor.lastrowid
        conn.commit()
        return category_id
    except (sqlite3.IntegrityError, Exception) as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
            raise ValueError(f"ชื่อหมวดหมู่ '{name}' มีอยู่ในระบบแล้ว")
        else:
            raise ValueError(f"เกิดข้อผิดพลาดในการเพิ่มหมวดหมู่: {e}")

def get_spare_part_category(conn, category_id):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("SELECT id, name, parent_id FROM spare_part_categories WHERE id = %s", (category_id,))
    else:
        cursor.execute("SELECT id, name, parent_id FROM spare_part_categories WHERE id = ?", (category_id,))
    category_data = cursor.fetchone()
    return dict(category_data) if category_data else None

def get_all_spare_part_categories(conn):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("SELECT id, name, parent_id FROM spare_part_categories ORDER BY name")
    else:
        cursor.execute("SELECT id, name, parent_id FROM spare_part_categories ORDER BY name")
    return [dict(row) for row in cursor.fetchall()]

def get_all_spare_part_categories_hierarchical(conn, include_id=False):
    """
    ดึงหมวดหมู่ทั้งหมดและจัดโครงสร้างให้เป็นลำดับชั้น (สำหรับ Dropdown ที่แสดง Indent)
    คืนค่าเป็น list ของ dictionaries ที่แต่ละ dict มี 'id', 'name_display', 'parent_id'
    โดยที่ 'name_display' จะเป็นชื่อที่มีการเยื้องตามระดับชั้น
    """
    categories = get_all_spare_part_categories(conn)

    # สร้าง dict เพื่อเก็บ children ของแต่ละ parent
    children_map = defaultdict(list)
    for cat in categories:
        children_map[cat['parent_id']].append(cat)

    # ฟังก์ชัน recursive เพื่อดึงและจัดเรียงหมวดหมู่
    final_list = []
    def traverse_categories(parent_id, level):
        # เรียง children ตามชื่อ (หรือตามลำดับที่คุณต้องการ)
        current_level_categories = sorted(children_map[parent_id], key=lambda x: x['name'])

        for cat in current_level_categories:
            prefix = "— " * level # "— " (em dash + space)
            display_name = f"{prefix}{cat['name']}"

            item = {'id': cat['id'], 'name_display': display_name, 'parent_id': cat['parent_id']}
            if include_id: # ถ้าต้องการ id จริงๆ ก็ใส่เพิ่ม
                item['actual_id'] = cat['id']

            final_list.append(item)

            # เรียกตัวเองซ้ำสำหรับ children
            traverse_categories(cat['id'], level + 1)

    traverse_categories(None, 0) # เริ่มจากหมวดหมู่หลัก (parent_id = None), level 0

    return final_list


def update_spare_part_category(conn, category_id, new_name, new_parent_id=None):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    # ตรวจสอบว่าพยายามตั้งให้ตัวเองเป็น parent_id หรือไม่
    if new_parent_id is not None and category_id == new_parent_id:
        raise ValueError("ไม่สามารถกำหนดหมวดหมู่แม่เป็นตัวหมวดหมู่เองได้")

    # ตรวจสอบการวนลูป (ถ้า A -> B -> A) - ซับซ้อนขึ้นอยู่กับการออกแบบ UI
    # สำหรับตอนนี้ เราจะไม่ตรวจสอบการวนซ้ำแบบหลายชั้นลึกๆ แต่จะป้องกันแค่ self-parenting

    try:
        if is_postgres:
            cursor.execute("""
                UPDATE spare_part_categories SET name = %s, parent_id = %s WHERE id = %s
            """, (new_name, new_parent_id, category_id))
        else:
            cursor.execute("""
                UPDATE spare_part_categories SET name = ?, parent_id = ? WHERE id = ?
            """, (new_name, new_parent_id, category_id))
        conn.commit()
    except (sqlite3.IntegrityError, Exception) as e:
        conn.rollback()
        if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
            raise ValueError(f"ชื่อหมวดหมู่ '{new_name}' มีอยู่ในระบบแล้ว")
        else:
            raise ValueError(f"เกิดข้อผิดพลาดในการอัปเดตหมวดหมู่: {e}")

def delete_spare_part_category(conn, category_id):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    # ตรวจสอบว่ามีอะไหล่ใดๆ ใช้หมวดหมู่นี้อยู่หรือไม่
    if is_postgres:
        cursor.execute("SELECT COUNT(*) FROM spare_parts WHERE category_id = %s", (category_id,))
    else:
        cursor.execute("SELECT COUNT(*) FROM spare_parts WHERE category_id = ?", (category_id,))
    spare_parts_count = cursor.fetchone()[0]
    if spare_parts_count > 0:
        raise ValueError(f"ไม่สามารถลบหมวดหมู่นี้ได้ มีอะไหล่ {spare_parts_count} รายการที่ใช้หมวดหมู่นี้อยู่")

    # ตรวจสอบว่ามีหมวดหมู่ย่อยอื่นผูกอยู่หรือไม่
    if is_postgres:
        cursor.execute("SELECT COUNT(*) FROM spare_part_categories WHERE parent_id = %s", (category_id,))
    else:
        cursor.execute("SELECT COUNT(*) FROM spare_part_categories WHERE parent_id = ?", (category_id,))
    subcategories_count = cursor.fetchone()[0]
    if subcategories_count > 0:
        raise ValueError(f"ไม่สามารถลบหมวดหมู่นี้ได้ มีหมวดหมู่ย่อย {subcategories_count} รายการที่ผูกอยู่")

    if is_postgres:
        cursor.execute("DELETE FROM spare_part_categories WHERE id = %s", (category_id,))
    else:
        cursor.execute("DELETE FROM spare_part_categories WHERE id = ?", (category_id,))
    conn.commit()

# --- Spare Part Functions (CRUD) ---
def add_spare_part(conn, name, part_number, brand, description, quantity, cost, retail_price,
                   wholesale_price1=None, wholesale_price2=None, cost_online=None,
                   image_filename=None, category_id=None, user_id=None):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    if is_postgres:
        cursor.execute("""
            INSERT INTO spare_parts (name, part_number, brand, description, quantity, cost, retail_price,
                                     wholesale_price1, wholesale_price2, cost_online, image_filename,
                                     is_deleted, category_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s) RETURNING id
        """, (name, part_number, brand, description, quantity, cost, retail_price,
              wholesale_price1, wholesale_price2, cost_online, image_filename, category_id))
        spare_part_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO spare_parts (name, part_number, brand, description, quantity, cost, retail_price,
                                     wholesale_price1, wholesale_price2, cost_online, image_filename,
                                     is_deleted, category_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, (name, part_number, brand, description, quantity, cost, retail_price,
              wholesale_price1, wholesale_price2, cost_online, image_filename, category_id))
        spare_part_id = cursor.lastrowid

    # บันทึกการเคลื่อนไหวเป็น "ซื้อเข้า"
    buy_in_channel_id = get_sales_channel_id(conn, 'ซื้อเข้า')
    add_spare_part_movement(conn, spare_part_id, 'IN', quantity, quantity, 'เพิ่มอะไหล่ใหม่เข้าสต็อก (ซื้อเข้า)',
                            None, user_id=user_id, channel_id=buy_in_channel_id)

    conn.commit()
    return spare_part_id

def get_spare_part(conn, spare_part_id):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("""
            SELECT sp.*, spc.name AS category_name, spc.parent_id AS category_parent_id
            FROM spare_parts sp
            LEFT JOIN spare_part_categories spc ON sp.category_id = spc.id
            WHERE sp.id = %s
        """, (spare_part_id,))
    else:
        cursor.execute("""
            SELECT sp.*, spc.name AS category_name, spc.parent_id AS category_parent_id
            FROM spare_parts sp
            LEFT JOIN spare_part_categories spc ON sp.category_id = spc.id
            WHERE sp.id = ?
        """, (spare_part_id,))
    spare_part_data = cursor.fetchone()
    return dict(spare_part_data) if spare_part_data else None

def update_spare_part(conn, spare_part_id, name, part_number, brand, description, cost, retail_price,
                      wholesale_price1, wholesale_price2, cost_online, image_filename, category_id):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    if is_postgres:
        cursor.execute("""
            UPDATE spare_parts SET
                name = %s, part_number = %s, brand = %s, description = %s, cost = %s, retail_price = %s,
                wholesale_price1 = %s, wholesale_price2 = %s, cost_online = %s, image_filename = %s,
                category_id = %s
            WHERE id = %s
        """, (name, part_number, brand, description, cost, retail_price,
              wholesale_price1, wholesale_price2, cost_online, image_filename,
              category_id, spare_part_id))
    else:
        cursor.execute("""
            UPDATE spare_parts SET
                name = ?, part_number = ?, brand = ?, description = ?, cost = ?, retail_price = ?,
                wholesale_price1 = ?, wholesale_price2 = ?, cost_online = ?, image_filename = ?,
                category_id = ?
            WHERE id = ?
        """, (name, part_number, brand, description, cost, retail_price,
              wholesale_price1, wholesale_price2, cost_online, image_filename,
              category_id, spare_part_id))
    conn.commit()

# --- Spare Part Functions (สำหรับ Import/Export) ---
def add_spare_part_import(conn, name, part_number, brand, description, quantity, cost, retail_price,
                          wholesale_price1, wholesale_price2, cost_online, image_filename, category_id):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    if is_postgres:
        cursor.execute("""
            INSERT INTO spare_parts (name, part_number, brand, description, quantity, cost, retail_price,
                                     wholesale_price1, wholesale_price2, cost_online, image_filename,
                                     is_deleted, category_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE, %s) RETURNING id
        """, (name, part_number, brand, description, quantity, cost, retail_price,
              wholesale_price1, wholesale_price2, cost_online, image_filename, category_id))
        spare_part_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO spare_parts (name, part_number, brand, description, quantity, cost, retail_price,
                                     wholesale_price1, wholesale_price2, cost_online, image_filename,
                                     is_deleted, category_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)
        """, (name, part_number, brand, description, quantity, cost, retail_price,
              wholesale_price1, wholesale_price2, cost_online, image_filename, category_id))
        spare_part_id = cursor.lastrowid
    conn.commit()
    return spare_part_id

def update_spare_part_import(conn, spare_part_id, name, part_number, brand, description, quantity, cost, retail_price,
                             wholesale_price1, wholesale_price2, cost_online, image_filename, category_id):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    if is_postgres:
        cursor.execute("""
            UPDATE spare_parts SET
                name = %s, part_number = %s, brand = %s, description = %s, quantity = %s, cost = %s, retail_price = %s,
                wholesale_price1 = %s, wholesale_price2 = %s, cost_online = %s, image_filename = %s,
                category_id = %s
            WHERE id = %s
        """, (name, part_number, brand, description, quantity, cost, retail_price,
              wholesale_price1, wholesale_price2, cost_online, image_filename,
              category_id, spare_part_id))
    else:
        cursor.execute("""
            UPDATE spare_parts SET
                name = ?, part_number = ?, brand = ?, description = ?, quantity = ?, cost = ?, retail_price = ?,
                wholesale_price1 = ?, wholesale_price2 = ?, cost_online = ?, image_filename = ?,
                category_id = ?
            WHERE id = ?
        """, (name, part_number, brand, description, quantity, cost, retail_price,
              wholesale_price1, wholesale_price2, cost_online, image_filename,
              category_id, spare_part_id))
    conn.commit()


def get_all_spare_parts(conn, query=None, brand_filter='all', category_filter='all', include_deleted=False):
    cursor = conn.cursor()
    sql_query = """
        SELECT sp.*, spc.name AS category_name, spc.parent_id AS category_parent_id
        FROM spare_parts sp
        LEFT JOIN spare_part_categories spc ON sp.category_id = spc.id
    """
    params = []
    conditions = []
    is_postgres = "psycopg2" in str(type(conn))

    if not include_deleted:
        conditions.append("sp.is_deleted = FALSE" if is_postgres else "sp.is_deleted = 0")

    if query:
        search_term = f"%{query}%"
        like_op = "ILIKE" if is_postgres else "LIKE"
        placeholder = "%s" if is_postgres else "?"
        
        # --- START: นี่คือส่วนที่แก้ไข ---
        # ใช้ COALESCE เพื่อจัดการกับ spc.name ที่อาจเป็น NULL (สำหรับสินค้าที่ไม่มีหมวดหมู่)
        conditions.append(f"""
            (sp.name {like_op} {placeholder} OR 
             sp.part_number {like_op} {placeholder} OR 
             sp.brand {like_op} {placeholder} OR 
             COALESCE(spc.name, '') {like_op} {placeholder})
        """)
        # --- END: นี่คือส่วนที่แก้ไข ---
        params.extend([search_term, search_term, search_term, search_term])

    if brand_filter != 'all':
        placeholder = "%s" if is_postgres else "?"
        conditions.append(f"sp.brand = {placeholder}")
        params.append(brand_filter)

    if category_filter and category_filter != 'all':
        try:
            category_id_int = int(category_filter)
            placeholder = "%s" if is_postgres else "?"
            conditions.append(f"sp.category_id = {placeholder}")
            params.append(category_id_int)
        except (ValueError, TypeError):
            print(f"Warning: Invalid category_filter value received: {category_filter}")
            pass

    if conditions:
        sql_query += " WHERE " + " AND ".join(conditions)

    sql_query += " ORDER BY sp.brand, spc.name, sp.name"

    if is_postgres:
        cursor.execute(sql_query, params)
    else:
        sql_query_sqlite = sql_query.replace('%s', '?').replace('ILIKE', 'LIKE')
        cursor.execute(sql_query_sqlite, params)

    spare_parts = cursor.fetchall()
    return [dict(row) for row in spare_parts]


def update_spare_part_movement(conn, movement_id, new_notes, new_image_filename, new_type, new_quantity_change,
                               new_channel_id, new_online_platform_id, new_wholesale_customer_id, new_return_customer_type):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    # 1. ดึงข้อมูลการเคลื่อนไหวเดิม
    if is_postgres:
        cursor.execute("SELECT spare_part_id, type, quantity_change FROM spare_part_movements WHERE id = %s", (movement_id,))
    else:
        cursor.execute("SELECT spare_part_id, type, quantity_change FROM spare_part_movements WHERE id = ?", (movement_id,))

    old_movement = cursor.fetchone()
    if not old_movement:
        raise ValueError("ไม่พบข้อมูลการเคลื่อนไหวอะไหล่ที่ระบุ")

    old_spare_part_id = old_movement['spare_part_id']
    old_type = old_movement['type']
    old_quantity_change = old_movement['quantity_change']

    # 2. ปรับยอดสต็อกของอะไหล่หลักกลับไปก่อนการเคลื่อนไหวเดิม
    current_spare_part = get_spare_part(conn, old_spare_part_id)
    if not current_spare_part:
        raise ValueError("ไม่พบอะไหล่หลักที่เกี่ยวข้องกับการเคลื่อนไหวนี้")

    current_quantity_in_stock = current_spare_part['quantity']

    # ย้อนกลับการเปลี่ยนแปลงเก่า
    if old_type == 'IN' or old_type == 'RETURN':
        current_quantity_in_stock -= old_quantity_change
    elif old_type == 'OUT':
        current_quantity_in_stock += old_quantity_change

    # 3. อัปเดตข้อมูลการเคลื่อนไหวในตาราง spare_part_movements
    if is_postgres:
        cursor.execute("""
            UPDATE spare_part_movements
            SET notes = %s, image_filename = %s, type = %s, quantity_change = %s,
                channel_id = %s, online_platform_id = %s, wholesale_customer_id = %s, return_customer_type = %s
            WHERE id = %s
        """, (new_notes, new_image_filename, new_type, new_quantity_change,
              new_channel_id, new_online_platform_id, new_wholesale_customer_id, new_return_customer_type,
              movement_id))
    else:
        cursor.execute("""
            UPDATE spare_part_movements
            SET notes = ?, image_filename = ?, type = ?, quantity_change = ?,
                channel_id = ?, online_platform_id = ?, wholesale_customer_id = ?, return_customer_type = ?
            WHERE id = ?
        """, (new_notes, new_image_filename, new_type, new_quantity_change,
              new_channel_id, new_online_platform_id, new_wholesale_customer_id, new_return_customer_type,
              movement_id))

    # 4. ปรับยอดสต็อกของอะไหล่หลักตามการเคลื่อนไหวใหม่
    if new_type == 'IN' or new_type == 'RETURN':
        current_quantity_in_stock += new_quantity_change
    elif new_type == 'OUT':
        current_quantity_in_stock -= new_quantity_change

    # 5. อัปเดตยอดคงเหลือในตาราง spare_parts
    update_spare_part_quantity(conn, old_spare_part_id, current_quantity_in_stock)

    # 6. อัปเดต remaining_quantity ในรายการ movement ที่แก้ไขและรายการหลังจากนั้น
    if is_postgres:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM spare_part_movements WHERE spare_part_id = %s AND timestamp >= (SELECT timestamp FROM spare_part_movements WHERE id = %s) ORDER BY timestamp ASC, id ASC", (old_spare_part_id, movement_id))
    else:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM spare_part_movements WHERE spare_part_id = ? AND timestamp >= (SELECT timestamp FROM spare_part_movements WHERE id = ?) ORDER BY timestamp ASC, id ASC", (old_spare_part_id, movement_id))

    subsequent_movements = cursor.fetchall()

    if is_postgres:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type IN ('IN', 'RETURN') THEN quantity_change ELSE -quantity_change END), 0) FROM spare_part_movements WHERE spare_part_id = %s AND timestamp < (SELECT timestamp FROM spare_part_movements WHERE id = %s)", (old_spare_part_id, movement_id))
    else:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type IN ('IN', 'RETURN') THEN quantity_change ELSE -quantity_change END), 0) FROM spare_part_movements WHERE spare_part_id = ? AND timestamp < (SELECT timestamp FROM spare_part_movements WHERE id = ?)", (old_spare_part_id, movement_id))

    initial_qty_before_edited_movement = cursor.fetchone()[0] or 0

    new_remaining_qty = initial_qty_before_edited_movement
    for sub_move in subsequent_movements:
        if sub_move['id'] == movement_id:
            if new_type == 'IN' or new_type == 'RETURN':
                new_remaining_qty += new_quantity_change
            else:
                new_remaining_qty -= new_quantity_change
        else:
            if sub_move['type'] == 'IN' or sub_move['type'] == 'RETURN':
                new_remaining_qty += sub_move['quantity_change']
            else:
                new_remaining_qty -= sub_move['quantity_change']

        if is_postgres:
            cursor.execute("UPDATE spare_part_movements SET remaining_quantity = %s WHERE id = %s", (new_remaining_qty, sub_move['id']))
        else:
            cursor.execute("UPDATE spare_part_movements SET remaining_quantity = ? WHERE id = ?", (new_remaining_qty, sub_move['id']))

    conn.commit()


def delete_spare_part_movement(conn, movement_id, deleted_by_user_id):
    """
    ลบข้อมูลการเคลื่อนไหวสต็อกอะไหล่, บันทึกประวัติการลบ, และปรับยอดคงเหลือ
    """
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    # 1. ดึงข้อมูลการเคลื่อนไหวที่จะลบ (รวมข้อมูล item)
    if is_postgres:
        cursor.execute("""
            SELECT spm.*, sp.name, sp.part_number, sp.brand
            FROM spare_part_movements spm
            JOIN spare_parts sp ON spm.spare_part_id = sp.id
            WHERE spm.id = %s
        """, (movement_id,))
    else:
        cursor.execute("""
            SELECT spm.*, sp.name, sp.part_number, sp.brand
            FROM spare_part_movements spm
            JOIN spare_parts sp ON spm.spare_part_id = sp.id
            WHERE spm.id = ?
        """, (movement_id,))

    movement_to_delete = cursor.fetchone()
    if not movement_to_delete:
        raise ValueError("ไม่พบข้อมูลการเคลื่อนไหวสต็อกอะไหล่ที่ระบุ")

    movement_to_delete_dict = dict(movement_to_delete)
    spare_part_id = movement_to_delete_dict['spare_part_id']
    move_type = movement_to_delete_dict['type']
    quantity_change = movement_to_delete_dict['quantity_change']
    movement_timestamp = movement_to_delete_dict['timestamp']

    # 2. บันทึกประวัติการลบลงตาราง deleted_movements
    item_details_str = f"อะไหล่: {movement_to_delete_dict['name']} ({movement_to_delete_dict.get('part_number', 'N/A')})"
    deleted_at_iso = get_bkk_time().isoformat()
    original_data_json = json.dumps({k: str(v) for k, v in movement_to_delete_dict.items()})

    if is_postgres:
        cursor.execute("""
            INSERT INTO deleted_movements (original_table, original_movement_id, item_details, movement_type, quantity_change, deleted_by_user_id, deleted_at, original_data_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, ('spare_part_movements', movement_id, item_details_str, move_type, quantity_change, deleted_by_user_id, deleted_at_iso, original_data_json))
    else:
        cursor.execute("""
            INSERT INTO deleted_movements (original_table, original_movement_id, item_details, movement_type, quantity_change, deleted_by_user_id, deleted_at, original_data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ('spare_part_movements', movement_id, item_details_str, move_type, quantity_change, deleted_by_user_id, deleted_at_iso, original_data_json))

    # 3. ปรับยอดสต็อกของอะไหล่หลัก
    current_spare_part = get_spare_part(conn, spare_part_id)
    if not current_spare_part:
        raise ValueError("ไม่พบอะไหล่หลักที่เกี่ยวข้องกับการเคลื่อนไหวนี้")

    new_quantity_for_main_item = current_spare_part['quantity']
    if move_type == 'IN' or move_type == 'RETURN':
        new_quantity_for_main_item -= quantity_change
    elif move_type == 'OUT':
        new_quantity_for_main_item += quantity_change
    update_spare_part_quantity(conn, spare_part_id, new_quantity_for_main_item)

    # 4. ลบรายการเคลื่อนไหว
    if is_postgres:
        cursor.execute("DELETE FROM spare_part_movements WHERE id = %s", (movement_id,))
    else:
        cursor.execute("DELETE FROM spare_part_movements WHERE id = ?", (movement_id,))

    # 5. อัปเดต remaining_quantity ของรายการที่ตามมา
    if is_postgres:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM spare_part_movements WHERE spare_part_id = %s AND timestamp >= %s ORDER BY timestamp ASC, id ASC", (spare_part_id, movement_timestamp))
    else:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM spare_part_movements WHERE spare_part_id = ? AND timestamp >= ? ORDER BY timestamp ASC, id ASC", (spare_part_id, movement_timestamp))

    subsequent_movements = cursor.fetchall()

    if is_postgres:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type IN ('IN', 'RETURN') THEN quantity_change ELSE -quantity_change END), 0) FROM spare_part_movements WHERE spare_part_id = %s AND timestamp < %s", (spare_part_id, movement_timestamp))
    else:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type IN ('IN', 'RETURN') THEN quantity_change ELSE -quantity_change END), 0) FROM spare_part_movements WHERE spare_part_id = ? AND timestamp < ?", (spare_part_id, movement_timestamp))

    current_remaining_qty = cursor.fetchone()[0] or 0

    for sub_move in subsequent_movements:
        if sub_move['type'] == 'IN' or sub_move['type'] == 'RETURN':
            current_remaining_qty += sub_move['quantity_change']
        else:
            current_remaining_qty -= sub_move['quantity_change']

        if is_postgres:
            cursor.execute("UPDATE spare_part_movements SET remaining_quantity = %s WHERE id = %s", (current_remaining_qty, sub_move['id']))
        else:
            cursor.execute("UPDATE spare_part_movements SET remaining_quantity = ? WHERE id = ?", (current_remaining_qty, sub_move['id']))

    return item_details_str, move_type, quantity_change


def update_spare_part_quantity(conn, spare_part_id, new_quantity):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("UPDATE spare_parts SET quantity = %s WHERE id = %s", (new_quantity, spare_part_id))
    else:
        cursor.execute("UPDATE spare_parts SET quantity = ? WHERE id = ?", (new_quantity, spare_part_id))
    conn.commit()

def add_spare_part_movement(conn, spare_part_id, move_type, quantity_change, remaining_quantity, notes, image_filename=None, user_id=None,
                      channel_id=None, online_platform_id=None, wholesale_customer_id=None, return_customer_type=None):
    timestamp = get_bkk_time()
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    commission_amount = 0.0

    if move_type == 'OUT' and channel_id:
        sales_channel_name = get_sales_channel_name(conn, channel_id)
        
        if sales_channel_name == 'หน้าร้าน':
            date_str = timestamp.strftime('%Y-%m-%d')
            # --- START: แก้ไขชื่อตารางตรงนี้ ---
            comm_query = "SELECT commission_amount_per_item FROM commission_programs WHERE item_type = 'spare_part' AND item_id = ? AND start_date <= ? AND (end_date IS NULL OR end_date >= ?)"
            # --- END: แก้ไขชื่อตารางตรงนี้ ---
            comm_params = (spare_part_id, date_str, date_str)
            
            if is_postgres:
                comm_query = comm_query.replace('?', '%s')
            
            cursor.execute(comm_query, comm_params)
            commission_program = cursor.fetchone()

            if commission_program:
                commission_per_item = commission_program['commission_amount_per_item']
                commission_amount = commission_per_item * quantity_change

    # ... (ส่วน INSERT INTO ไม่ต้องแก้ไข) ...
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO spare_part_movements (spare_part_id, timestamp, type, quantity_change, remaining_quantity, notes, image_filename, user_id,
                                        channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
                                        commission_amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (spare_part_id, timestamp.isoformat(), move_type, quantity_change, remaining_quantity, notes, image_filename, user_id,
              channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
              commission_amount))
    else:
        cursor.execute("""
            INSERT INTO spare_part_movements (spare_part_id, timestamp, type, quantity_change, remaining_quantity, notes, image_filename, user_id,
                                        channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
                                        commission_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (spare_part_id, timestamp.isoformat(), move_type, quantity_change, remaining_quantity, notes, image_filename, user_id,
              channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
              commission_amount))
    conn.commit()

def delete_spare_part(conn, spare_part_id):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("UPDATE spare_parts SET is_deleted = TRUE WHERE id = %s", (spare_part_id,))
    else:
        cursor.execute("UPDATE spare_parts SET is_deleted = 1 WHERE id = ?", (spare_part_id,))
    conn.commit()

def get_deleted_spare_parts(conn):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    sql_query = """
        SELECT sp.*, spc.name AS category_name
        FROM spare_parts sp
        LEFT JOIN spare_part_categories spc ON sp.category_id = spc.id
        WHERE sp.is_deleted = TRUE
        ORDER BY sp.brand, sp.name
    """
    if is_postgres:
        cursor.execute(sql_query)
    else:
        cursor.execute(sql_query.replace('TRUE', '1'))
    spare_parts = cursor.fetchall()
    return [dict(row) for row in spare_parts]

def restore_spare_part(conn, spare_part_id):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("UPDATE spare_parts SET is_deleted = FALSE WHERE id = %s", (spare_part_id,))
    else:
        cursor.execute("UPDATE spare_parts SET is_deleted = 0 WHERE id = ?", (spare_part_id,))
    conn.commit()

def get_all_spare_part_brands(conn):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("SELECT DISTINCT brand FROM spare_parts WHERE is_deleted = FALSE AND brand IS NOT NULL AND brand != '' ORDER BY brand")
    else:
        cursor.execute("SELECT DISTINCT brand FROM spare_parts WHERE is_deleted = 0 AND brand IS NOT NULL AND brand != '' ORDER BY brand")
    brands_data = cursor.fetchall()
    return [row['brand'] for row in brands_data]

# --- Spare Part Barcode Functions ---
def add_spare_part_barcode(conn, spare_part_id, barcode_string, is_primary=False):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("INSERT INTO spare_part_barcodes (spare_part_id, barcode_string, is_primary_barcode) VALUES (%s, %s, %s) ON CONFLICT (barcode_string) DO NOTHING",
                       (spare_part_id, barcode_string, is_primary))
    else:
        cursor.execute("INSERT OR IGNORE INTO spare_part_barcodes (spare_part_id, barcode_string, is_primary_barcode) VALUES (?, ?, ?)",
                       (spare_part_id, barcode_string, is_primary))

def get_spare_part_id_by_barcode(conn, barcode_string):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("SELECT spare_part_id FROM spare_part_barcodes WHERE barcode_string = %s", (barcode_string,))
    else:
        cursor.execute("SELECT spare_part_id FROM spare_part_barcodes WHERE barcode_string = ?", (barcode_string,))
    result = cursor.fetchone()
    return result['spare_part_id'] if result else None

def get_barcodes_for_spare_part(conn, spare_part_id):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("SELECT barcode_string, is_primary_barcode FROM spare_part_barcodes WHERE spare_part_id = %s ORDER BY is_primary_barcode DESC, barcode_string ASC", (spare_part_id,))
    else:
        cursor.execute("SELECT barcode_string, is_primary_barcode FROM spare_part_barcodes WHERE spare_part_id = ? ORDER BY is_primary_barcode DESC, barcode_string ASC", (spare_part_id,))
    return [dict(row) for row in cursor.fetchall()]

def delete_spare_part_barcode(conn, barcode_string):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("DELETE FROM spare_part_barcodes WHERE barcode_string = %s", (barcode_string,))
    else:
        cursor.execute("DELETE FROM spare_part_barcodes WHERE barcode_string = ?", (barcode_string,))

# --- Promotion Functions ---
def add_promotion(conn, name, promo_type, value1, value2, is_active):
    created_at = get_bkk_time().isoformat()
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO promotions (name, type, value1, value2, is_active, created_at)
            VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
        """, (name, promo_type, value1, value2, is_active, created_at))
        promo_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO promotions (name, type, value1, value2, is_active, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (name, promo_type, value1, value2, is_active, created_at))
        promo_id = cursor.lastrowid
    conn.commit()
    return promo_id

def get_spare_part_movement(conn, movement_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            SELECT spm.*, sp.name AS spare_part_name, sp.part_number, sp.brand AS spare_part_brand, u.username,
                   sc.name AS channel_name,
                   op.name AS online_platform_name,
                   wc.name AS wholesale_customer_name
            FROM spare_part_movements spm
            JOIN spare_parts sp ON spm.spare_part_id = sp.id
            LEFT JOIN users u ON spm.user_id = u.id
            LEFT JOIN sales_channels sc ON spm.channel_id = sc.id
            LEFT JOIN online_platforms op ON spm.online_platform_id = op.id
            LEFT JOIN wholesale_customers wc ON spm.wholesale_customer_id = wc.id
            WHERE spm.id = %s
        """, (movement_id,))
    else: # SQLite
        cursor.execute("""
            SELECT spm.*, sp.name AS spare_part_name, sp.part_number, sp.brand AS spare_part_brand, u.username,
                   sc.name AS channel_name,
                   op.name AS online_platform_name,
                   wc.name AS wholesale_customer_name
            FROM spare_part_movements spm
            JOIN spare_parts sp ON spm.spare_part_id = sp.id
            LEFT JOIN users u ON spm.user_id = u.id
            LEFT JOIN sales_channels sc ON spm.channel_id = sc.id
            LEFT JOIN online_platforms op ON spm.online_platform_id = op.id
            LEFT JOIN wholesale_customers wc ON spm.wholesale_customer_id = wc.id
            WHERE spm.id = ?
        """, (movement_id,))
    movement_data = cursor.fetchone()
    if movement_data:
        return dict(movement_data)
    return None

def get_promotion(conn, promo_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT * FROM promotions WHERE id = %s", (promo_id,))
    else:
        cursor.execute("SELECT * FROM promotions WHERE id = ?", (promo_id,))
    promo_data = cursor.fetchone()
    if isinstance(promo_data, sqlite3.Row):
        promo_data = dict(promo_data)
    return promo_data

def get_all_promotions(conn, include_inactive=False):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        query = "SELECT id, name, type, value1, value2, is_active, created_at FROM promotions"
        if not include_inactive:
            query += " WHERE is_active = TRUE AND is_deleted = FALSE"
        query += " ORDER BY created_at DESC"
        cursor.execute(query)
    else: # SQLite
        query = "SELECT id, name, type, value1, value2, is_active, created_at FROM promotions"
        if not include_inactive:
            query += " WHERE is_active = 1 AND is_deleted = 0"
        query += " ORDER BY created_at DESC"
        cursor.execute(query)

    promotions = cursor.fetchall()

    # แก้ไขส่วนนี้: Convert created_at to datetime objects for SQLite using fromisoformat
    if "sqlite3" in str(type(conn)):
        bkk_tz = pytz.timezone('Asia/Bangkok') # Ensure BKK_TZ is defined or imported
        converted_promotions = []
        for promo in promotions:
            promo_dict = dict(promo) # Convert sqlite3.Row to a dictionary
            if promo_dict['created_at']:
                try:
                    # Use fromisoformat for ISO 8601 strings (including timezone offset)
                    dt_obj = datetime.fromisoformat(promo_dict['created_at'])
                    # Ensure it's in BKK timezone (it might already be timezone-aware from fromisoformat)
                    # and convert if necessary
                    promo_dict['created_at'] = dt_obj.astimezone(bkk_tz)
                except ValueError:
                    print(f"Warning: Could not parse created_at string with fromisoformat: {promo_dict['created_at']}")
                    promo_dict['created_at'] = None # Set to None if parsing fails
            converted_promotions.append(promo_dict)
        return converted_promotions

    return promotions

def update_promotion(conn, promo_id, name, promo_type, value1, value2, is_active):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE promotions SET
                name = %s,
                type = %s,
                value1 = %s,
                value2 = %s,
                is_active = %s
            WHERE id = %s
        """, (name, promo_type, value1, value2, is_active, promo_id))
    else:
        cursor.execute("""
            UPDATE promotions SET
                name = ?,
                type = ?,
                value1 = ?,
                value2 = ?,
                is_active = ?
            WHERE id = ?
        """, (name, promo_type, value1, value2, is_active, promo_id))
    conn.commit()

def delete_promotion(conn, promo_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("UPDATE tires SET promotion_id = NULL WHERE promotion_id = %s", (promo_id,))
        cursor.execute("DELETE FROM promotions WHERE id = %s", (promo_id,))
    else:
        cursor.execute("UPDATE tires SET promotion_id = NULL WHERE promotion_id = ?", (promo_id,))
        cursor.execute("DELETE FROM promotions WHERE id = ?", (promo_id,))
    conn.commit()

# --- Tire Functions ---
def add_tire(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, user_id=None):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    if is_postgres:
        cursor.execute("""
            INSERT INTO tires (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, is_deleted)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE) RETURNING id
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture))
        tire_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO tires (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture))
        tire_id = cursor.lastrowid
    
    # เมื่อเพิ่มยางใหม่ ให้บันทึกการเคลื่อนไหวเป็น "ซื้อเข้า"
    buy_in_channel_id = get_sales_channel_id(conn, 'ซื้อเข้า')
    add_tire_movement(conn, tire_id, 'IN', quantity, quantity, 'เพิ่มยางใหม่เข้าสต็อก (ซื้อเข้า)', None, user_id=user_id, channel_id=buy_in_channel_id)
    
    conn.commit()
    return tire_id

def get_tire(conn, tire_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            SELECT t.*, 
                   p.name AS promo_name, 
                   p.type AS promo_type, 
                   p.value1 AS promo_value1, 
                   p.value2 AS promo_value2,
                   p.is_active AS promo_is_active
            FROM tires t
            LEFT JOIN promotions p ON t.promotion_id = p.id
            WHERE t.id = %s
        """, (tire_id,))
    else:
        cursor.execute("""
            SELECT t.*, 
                   p.name AS promo_name, 
                   p.type AS promo_type, 
                   p.value1 AS promo_value1, 
                   p.value2 AS promo_value2,
                   p.is_active AS promo_is_active
            FROM tires t
            LEFT JOIN promotions p ON t.promotion_id = p.id
            WHERE t.id = ?
        """, (tire_id,))
    tire = cursor.fetchone()
    
    if tire:
        tire_dict = dict(tire) 
        
        tire_dict['display_promo_price_per_item'] = None
        tire_dict['display_price_for_4'] = tire_dict['price_per_item'] * 4 if tire_dict['price_per_item'] is not None else None
        tire_dict['display_promo_description'] = None

        promo_active_check = tire_dict['promo_is_active']
        if "psycopg2" in str(type(conn)):
            promo_active_check = bool(promo_active_check)
        else:
            promo_active_check = (promo_active_check == 1)

        if tire_dict['promotion_id'] is not None and promo_active_check:
            promo_calc_result = calculate_tire_promo_prices(
                tire_dict['price_per_item'],
                tire_dict['promo_type'],
                tire_dict['promo_value1'],
                tire_dict['promo_value2']
            )
            tire_dict['display_promo_price_per_item'] = promo_calc_result['price_per_item_promo']
            tire_dict['display_price_for_4'] = promo_calc_result['price_for_4_promo']
            tire_dict['display_promo_description'] = promo_calc_result['promo_description_text']
        
        return tire_dict 
    return tire

def update_tire(conn, tire_id, brand, model, size, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE tires SET
                brand = %s,
                model = %s,
                size = %s,
                cost_sc = %s,
                cost_dunlop = %s,
                cost_online = %s,
                wholesale_price1 = %s,
                wholesale_price2 = %s,
                price_per_item = %s,
                promotion_id = %s,
                year_of_manufacture = %s
            WHERE id = %s
        """, (brand, model, size, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, tire_id))
    else:
        cursor.execute("""
            UPDATE tires SET
                brand = ?,
                model = ?,
                size = ?,
                cost_sc = ?,
                cost_dunlop = ?,
                cost_online = ?,
                wholesale_price1 = ?,
                wholesale_price2 = ?,
                price_per_item = ?,
                promotion_id = ?,
                year_of_manufacture = ?
            WHERE id = ?
        """, (brand, model, size, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, tire_id))
    conn.commit()

def add_tire_import(conn, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture): 
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO tires (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, is_deleted)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE) RETURNING id
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture))
        tire_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO tires (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture))
        tire_id = cursor.lastrowid
    conn.commit()
    return tire_id

def update_tire_import(conn, tire_id, brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture): 
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE tires SET
                brand = %s,
                model = %s,
                size = %s,
                quantity = %s, 
                cost_sc = %s,
                cost_dunlop = %s,
                cost_online = %s,
                wholesale_price1 = %s,
                wholesale_price2 = %s,
                price_per_item = %s,
                promotion_id = %s,
                year_of_manufacture = %s
            WHERE id = %s
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, tire_id))
    else:
        cursor.execute("""
            UPDATE tires SET
                brand = ?,
                model = ?,
                size = ?,
                quantity = ?, 
                cost_sc = ?,
                cost_dunlop = ?,
                cost_online = ?,
                wholesale_price1 = ?,
                wholesale_price2 = ?,
                price_per_item = ?,
                promotion_id = ?,
                year_of_manufacture = ?
            WHERE id = ?
        """, (brand, model, size, quantity, cost_sc, cost_dunlop, cost_online, wholesale_price1, wholesale_price2, price_per_item, promotion_id, year_of_manufacture, tire_id))
    conn.commit()

def calculate_tire_promo_prices(price_per_item, promo_type, promo_value1, promo_value2):
    price_per_item_promo = price_per_item
    price_for_4_promo = price_per_item * 4
    promo_description_text = None

    if price_per_item is None or promo_type is None:
        return {
            'price_per_item_promo': None, 
            'price_for_4_promo': price_per_item * 4 if price_per_item is not None else None,
            'promo_description_text': None
        }

    if promo_type == 'buy_x_get_y' and promo_value1 is not None and promo_value2 is not None:
        if (promo_value1 > 0 and promo_value2 >= 0):
            if (promo_value1 + promo_value2) > 0:
                price_per_item_promo = (price_per_item * promo_value1) / (promo_value1 + promo_value2)
                price_for_4_promo = price_per_item_promo * 4
                promo_description_text = f"ซื้อ {int(promo_value1)} แถม {int(promo_value2)} ฟรี"
            else:
                price_per_item_promo = None
                price_for_4_promo = None
                promo_description_text = "โปรไม่ถูกต้อง (X+Y=0)"
        else:
            price_per_item_promo = None
            price_for_4_promo = None
            promo_description_text = "โปรไม่ถูกต้อง (X,Y<=0)"
    
    elif promo_type == 'percentage_discount' and promo_value1 is not None:
        if (promo_value1 >= 0 and promo_value1 <= 100):
            price_per_item_promo = price_per_item * (1 - (promo_value1 / 100))
            price_for_4_promo = price_per_item_promo * 4
            promo_description_text = f"ลด {promo_value1}%"
        else:
            price_per_item_promo = None
            price_for_4_promo = None
            promo_description_text = "โปรไม่ถูกต้อง (%ไม่ถูกต้อง)"
    
    elif promo_type == 'fixed_price_per_n' and promo_value1 is not None and promo_value2 is not None:
        if promo_value2 > 0:
            price_per_item_promo = promo_value1 / promo_value2
            price_for_4_promo = price_per_item_promo * 4
            promo_description_text = f"ราคา {promo_value1:.2f} บาท สำหรับ {int(promo_value2)} เส้น"
        else:
            price_per_item_promo = None
            price_for_4_promo = None
            promo_description_text = "โปรไม่ถูกต้อง (N<=0)"
            
    if price_per_item_promo is None:
        price_per_item_promo = price_per_item
        price_for_4_promo = price_per_item * 4
        promo_description_text = None

    return {
        'price_per_item_promo': price_per_item_promo, 
        'price_for_4_promo': price_for_4_promo,
        'promo_description_text': promo_description_text
    }


def get_all_tires(conn, query=None, brand_filter='all', include_deleted=False): # ADDED include_deleted
    cursor = conn.cursor()
    sql_query = """
        SELECT t.*,
               p.name AS promo_name,
               p.type AS promo_type,
               p.value1 AS promo_value1,
               p.value2 AS promo_value2,
               p.is_active AS promo_is_active
        FROM tires t
        LEFT JOIN promotions p ON t.promotion_id = p.id
    """
    params = []
    conditions = []

    if not include_deleted: # Conditionally add is_deleted filter
        conditions.append("t.is_deleted = FALSE" if "psycopg2" in str(type(conn)) else "t.is_deleted = 0")

    if query:
        search_term = f"%{query}%"
        conditions.append("(t.brand ILIKE %s OR t.model ILIKE %s OR t.size ILIKE %s)" if "psycopg2" in str(type(conn)) else "(t.brand LIKE ? OR t.model LIKE ? OR t.size LIKE ?)")
        params.extend([search_term, search_term, search_term])

    if brand_filter != 'all':
        conditions.append("t.brand = %s" if "psycopg2" in str(type(conn)) else "t.brand = ?")
        params.append(brand_filter)

    if conditions:
        sql_query += " WHERE " + " AND ".join(conditions) # Changed WHERE to AND for filtering soft deleted items

    sql_query += " ORDER BY t.brand, t.model"

    if "psycopg2" in str(type(conn)):
        cursor.execute(sql_query, params)
    else:
        cursor.execute(sql_query, params)

    tires = cursor.fetchall()

    processed_tires = []
    for tire in tires:
        tire_dict = dict(tire) 

        promo_calc_result = {
            'price_per_item_promo': None,
            'price_for_4_promo': tire_dict['price_per_item'] * 4 if tire_dict['price_per_item'] is not None else None,
            'promo_description_text': None
        }

        promo_active_check = tire_dict['promo_is_active']
        if "psycopg2" in str(type(conn)):
            promo_active_check = bool(promo_active_check)
        else:
            promo_active_check = (promo_active_check == 1)

        if tire_dict['promotion_id'] is not None and promo_active_check:
            promo_calc_result = calculate_tire_promo_prices(
                tire_dict['price_per_item'],
                tire_dict['promo_type'],
                tire_dict['promo_value1'],
                tire_dict['promo_value2']
            )

        tire_dict['display_promo_price_per_item'] = promo_calc_result['price_per_item_promo']
        tire_dict['display_price_for_4'] = promo_calc_result['price_for_4_promo']
        tire_dict['display_promo_description_text'] = promo_calc_result['promo_description_text']

        processed_tires.append(tire_dict)

    def sort_key_for_tire_size(tire_item):
        size_str = tire_item.get('size', '')
        match = re.search(r'R(\d+)$', size_str)
        if not match:
            match = re.search(r'(\d+)$', size_str)

        try:
            rim_size = int(match.group(1)) if match else 0
            return rim_size
        except ValueError:
            return 0
    
    sorted_processed_tires = sorted(processed_tires, key=lambda x: (x.get('brand', ''), x.get('model', ''), sort_key_for_tire_size(x)))

    return sorted_processed_tires

def get_tire_movement(conn, movement_id):
    cursor = conn.cursor()
    # เพิ่มการดึงข้อมูล channel, platform, customer, return_customer_type
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            SELECT tm.*, t.brand, t.model, t.size, u.username,
                   sc.name AS channel_name,
                   op.name AS online_platform_name,
                   wc.name AS wholesale_customer_name
            FROM tire_movements tm
            JOIN tires t ON tm.tire_id = t.id
            LEFT JOIN users u ON tm.user_id = u.id
            LEFT JOIN sales_channels sc ON tm.channel_id = sc.id
            LEFT JOIN online_platforms op ON tm.online_platform_id = op.id
            LEFT JOIN wholesale_customers wc ON tm.wholesale_customer_id = wc.id
            WHERE tm.id = %s
        """, (movement_id,))
    else:
        cursor.execute("""
            SELECT tm.*, t.brand, t.model, t.size, u.username,
                   sc.name AS channel_name,
                   op.name AS online_platform_name,
                   wc.name AS wholesale_customer_name
            FROM tire_movements tm
            JOIN tires t ON tm.tire_id = t.id
            LEFT JOIN users u ON tm.user_id = u.id
            LEFT JOIN sales_channels sc ON tm.channel_id = sc.id
            LEFT JOIN online_platforms op ON tm.online_platform_id = op.id
            LEFT JOIN wholesale_customers wc ON tm.wholesale_customer_id = wc.id
            WHERE tm.id = ?
        """, (movement_id,))
    movement_data = cursor.fetchone()
    if isinstance(movement_data, sqlite3.Row):
        movement_data = dict(movement_data)
    return movement_data

def get_wheel_movement(conn, movement_id):
    cursor = conn.cursor()
    # เพิ่มการดึงข้อมูล channel, platform, customer, return_customer_type
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            SELECT wm.*, w.brand, w.model, w.diameter, u.username,
                   sc.name AS channel_name,
                   op.name AS online_platform_name,
                   wc.name AS wholesale_customer_name
            FROM wheel_movements wm
            JOIN wheels w ON wm.wheel_id = w.id
            LEFT JOIN users u ON wm.user_id = u.id
            LEFT JOIN sales_channels sc ON wm.channel_id = sc.id
            LEFT JOIN online_platforms op ON wm.online_platform_id = op.id
            LEFT JOIN wholesale_customers wc ON wm.wholesale_customer_id = wc.id
            WHERE wm.id = %s
        """, (movement_id,))
    else:
        cursor.execute("""
            SELECT wm.*, w.brand, w.model, w.diameter, u.username,
                   sc.name AS channel_name,
                   op.name AS online_platform_name,
                   wc.name AS wholesale_customer_name
            FROM wheel_movements wm
            JOIN wheels w ON wm.wheel_id = w.id
            LEFT JOIN users u ON wm.user_id = u.id
            LEFT JOIN sales_channels sc ON wm.channel_id = sc.id
            LEFT JOIN online_platforms op ON wm.online_platform_id = op.id
            LEFT JOIN wholesale_customers wc ON wm.wholesale_customer_id = wc.id
            WHERE wm.id = ?
        """, (movement_id,))
    movement_data = cursor.fetchone()
    if isinstance(movement_data, sqlite3.Row):
        movement_data = dict(movement_data)
    return movement_data

def update_wheel_movement(conn, movement_id, new_notes, new_image_filename, new_type, new_quantity_change, 
                          new_channel_id, new_online_platform_id, new_wholesale_customer_id, new_return_customer_type):
    """
    อัปเดตข้อมูลการเคลื่อนไหวสต็อกแม็กและปรับยอดคงเหลือของแม็กหลัก
    """
    cursor = conn.cursor()
    
    # 1. ดึงข้อมูลการเคลื่อนไหวเดิม
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT wheel_id, type, quantity_change FROM wheel_movements WHERE id = %s", (movement_id,))
    else:
        cursor.execute("SELECT wheel_id, type, quantity_change FROM wheel_movements WHERE id = ?", (movement_id,))
    
    old_movement = cursor.fetchone()
    if not old_movement:
        raise ValueError("ไม่พบข้อมูลการเคลื่อนไหวแม็กที่ระบุ")
    
    old_wheel_id = old_movement['wheel_id']
    old_type = old_movement['type']
    old_quantity_change = old_movement['quantity_change']

    # 2. ปรับยอดสต็อกของแม็กหลักกลับไปก่อนการเคลื่อนไหวเดิม
    current_wheel = get_wheel(conn, old_wheel_id)
    if not current_wheel:
        raise ValueError("ไม่พบแม็กหลักที่เกี่ยวข้องกับการเคลื่อนไหวนี้")
    
    current_quantity_in_stock = current_wheel['quantity']

    # ย้อนกลับการเปลี่ยนแปลงเก่า
    if old_type == 'IN' or old_type == 'RETURN': # รับเข้าหรือรับคืน (เพิ่มสต็อก)
        current_quantity_in_stock -= old_quantity_change
    elif old_type == 'OUT': # จ่ายออก (ลดสต็อก)
        current_quantity_in_stock += old_quantity_change

    # 3. อัปเดตข้อมูลการเคลื่อนไหวในตาราง wheel_movements
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE wheel_movements
            SET notes = %s, image_filename = %s, type = %s, quantity_change = %s,
                channel_id = %s, online_platform_id = %s, wholesale_customer_id = %s, return_customer_type = %s
            WHERE id = %s
        """, (new_notes, new_image_filename, new_type, new_quantity_change,
              new_channel_id, new_online_platform_id, new_wholesale_customer_id, new_return_customer_type,
              movement_id))
    else:
        cursor.execute("""
            UPDATE wheel_movements
            SET notes = ?, image_filename = ?, type = ?, quantity_change = ?,
                channel_id = ?, online_platform_id = ?, wholesale_customer_id = ?, return_customer_type = ?
            WHERE id = ?
        """, (new_notes, new_image_filename, new_type, new_quantity_change,
              new_channel_id, new_online_platform_id, new_wholesale_customer_id, new_return_customer_type,
              movement_id))
    
    # 4. ปรับยอดสต็อกของแม็กหลักตามการเคลื่อนไหวใหม่
    if new_type == 'IN' or new_type == 'RETURN': # รับเข้าหรือรับคืน (เพิ่มสต็อก)
        current_quantity_in_stock += new_quantity_change
    elif new_type == 'OUT': # จ่ายออก (ลดสต็อก)
        current_quantity_in_stock -= new_quantity_change
    
    # 5. อัปเดตยอดคงเหลือในตาราง wheels
    update_wheel_quantity(conn, old_wheel_id, current_quantity_in_stock)

    # 6. อัปเดต remaining_quantity ในรายการ movement ที่แก้ไขและรายการหลังจากนั้น
    # ดึงรายการ movement ทั้งหมดสำหรับ wheel_id นั้นๆ ที่ timestamp มากกว่าหรือเท่ากับรายการที่แก้ไข
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM wheel_movements WHERE wheel_id = %s AND timestamp >= (SELECT timestamp FROM wheel_movements WHERE id = %s) ORDER BY timestamp ASC, id ASC", (old_wheel_id, movement_id))
    else:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM wheel_movements WHERE wheel_id = ? AND timestamp >= (SELECT timestamp FROM wheel_movements WHERE id = ?) ORDER BY timestamp ASC, id ASC", (old_wheel_id, movement_id))
    
    subsequent_movements = cursor.fetchall()

    # คำนวณยอดคงเหลือเริ่มต้นก่อนรายการที่แก้ไข
    if is_postgres:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type = 'IN' THEN quantity_change ELSE -quantity_change END), 0) FROM wheel_movements WHERE wheel_id = %s AND timestamp < (SELECT timestamp FROM wheel_movements WHERE id = %s)", (old_wheel_id, movement_id))
    else:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type = 'IN' THEN quantity_change ELSE -quantity_change END), 0) FROM wheel_movements WHERE wheel_id = ? AND timestamp < (SELECT timestamp FROM wheel_movements WHERE id = ?)", (old_wheel_id, movement_id))
    
    initial_qty_before_edited_movement = cursor.fetchone()[0] or 0

    new_remaining_qty = initial_qty_before_edited_movement
    for sub_move in subsequent_movements:
        if sub_move['id'] == movement_id:
            # ใช้ค่าใหม่ที่แก้ไข
            if new_type == 'IN' or new_type == 'RETURN':
                new_remaining_qty += new_quantity_change
            else: # new_type == 'OUT'
                new_remaining_qty -= new_quantity_change
        else:
            # ใช้ค่าเดิมของ movement ที่ตามมา
            if sub_move['type'] == 'IN' or sub_move['type'] == 'RETURN':
                new_remaining_qty += sub_move['quantity_change']
            else: # sub_move['type'] == 'OUT'
                new_remaining_qty -= sub_move['quantity_change']
        
        # อัปเดต remaining_quantity ในฐานข้อมูล
        if is_postgres:
            cursor.execute("UPDATE wheel_movements SET remaining_quantity = %s WHERE id = %s", (new_remaining_qty, sub_move['id']))
        else:
            cursor.execute("UPDATE wheel_movements SET remaining_quantity = ? WHERE id = ?", (new_remaining_qty, sub_move['id']))

    conn.commit()


def update_tire_movement(conn, movement_id, new_notes, new_image_filename, new_type, new_quantity_change,
                         new_channel_id, new_online_platform_id, new_wholesale_customer_id, new_return_customer_type):
    """
    อัปเดตข้อมูลการเคลื่อนไหวสต็อกยางและปรับยอดคงเหลือของยางหลัก
    """
    cursor = conn.cursor()

    # 1. ดึงข้อมูลการเคลื่อนไหวเดิม
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT tire_id, type, quantity_change FROM tire_movements WHERE id = %s", (movement_id,))
    else:
        cursor.execute("SELECT tire_id, type, quantity_change FROM tire_movements WHERE id = ?", (movement_id,))
    
    old_movement = cursor.fetchone()
    if not old_movement:
        raise ValueError("ไม่พบข้อมูลการเคลื่อนไหวสต็อกยางที่ระบุ")
    
    old_tire_id = old_movement['tire_id']
    old_type = old_movement['type']
    old_quantity_change = old_movement['quantity_change']

    # 2. ปรับยอดสต็อกของยางหลักกลับไปก่อนการเคลื่อนไหวเดิม
    current_tire = get_tire(conn, old_tire_id)
    if not current_tire:
        raise ValueError("ไม่พบยางหลักที่เกี่ยวข้องกับการเคลื่อนไหวนี้")
    
    current_quantity_in_stock = current_tire['quantity']

    # ย้อนกลับการเปลี่ยนแปลงเก่า
    if old_type == 'IN' or old_type == 'RETURN': # รับเข้าหรือรับคืน (เพิ่มสต็อก)
        current_quantity_in_stock -= old_quantity_change
    elif old_type == 'OUT': # จ่ายออก (ลดสต็อก)
        current_quantity_in_stock += old_quantity_change

    # 3. อัปเดตข้อมูลการเคลื่อนไหวในตาราง tire_movements
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE tire_movements
            SET notes = %s, image_filename = %s, type = %s, quantity_change = %s,
                channel_id = %s, online_platform_id = %s, wholesale_customer_id = %s, return_customer_type = %s
            WHERE id = %s
        """, (new_notes, new_image_filename, new_type, new_quantity_change,
              new_channel_id, new_online_platform_id, new_wholesale_customer_id, new_return_customer_type,
              movement_id))
    else:
        cursor.execute("""
            UPDATE tire_movements
            SET notes = ?, image_filename = ?, type = ?, quantity_change = ?,
                channel_id = ?, online_platform_id = ?, wholesale_customer_id = ?, return_customer_type = ?
            WHERE id = ?
        """, (new_notes, new_image_filename, new_type, new_quantity_change,
              new_channel_id, new_online_platform_id, new_wholesale_customer_id, new_return_customer_type,
              movement_id))
    
    # 4. ปรับยอดสต็อกของยางหลักตามการเคลื่อนไหวใหม่
    if new_type == 'IN' or new_type == 'RETURN': # รับเข้าหรือรับคืน (เพิ่มสต็อก)
        current_quantity_in_stock += new_quantity_change
    elif new_type == 'OUT': # จ่ายออก (ลดสต็อก)
        current_quantity_in_stock -= new_quantity_change
    
    # 5. อัปเดตยอดคงเหลือในตาราง tires
    update_tire_quantity(conn, old_tire_id, current_quantity_in_stock)

    # 6. อัปเดต remaining_quantity ในรายการ movement ที่แก้ไขและรายการหลังจากนั้น
    # ดึงรายการ movement ทั้งหมดสำหรับ tire_id นั้นๆ ที่ timestamp มากกว่าหรือเท่ากับรายการที่แก้ไข
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM tire_movements WHERE tire_id = %s AND timestamp >= (SELECT timestamp FROM tire_movements WHERE id = %s) ORDER BY timestamp ASC, id ASC", (old_tire_id, movement_id))
    else:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM tire_movements WHERE tire_id = ? AND timestamp >= (SELECT timestamp FROM tire_movements WHERE id = ?) ORDER BY timestamp ASC, id ASC", (old_tire_id, movement_id))
    
    subsequent_movements = cursor.fetchall()

    # คำนวณยอดคงเหลือเริ่มต้นก่อนรายการที่แก้ไข
    if is_postgres:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type = 'IN' THEN quantity_change ELSE -quantity_change END), 0) FROM tire_movements WHERE tire_id = %s AND timestamp < (SELECT timestamp FROM tire_movements WHERE id = %s)", (old_tire_id, movement_id))
    else:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type = 'IN' THEN quantity_change ELSE -quantity_change END), 0) FROM tire_movements WHERE tire_id = ? AND timestamp < (SELECT timestamp FROM tire_movements WHERE id = ?)", (old_tire_id, movement_id))
    
    initial_qty_before_edited_movement = cursor.fetchone()[0] or 0

    new_remaining_qty = initial_qty_before_edited_movement
    for sub_move in subsequent_movements:
        if sub_move['id'] == movement_id:
            # ใช้ค่าใหม่ที่แก้ไข
            if new_type == 'IN' or new_type == 'RETURN':
                new_remaining_qty += new_quantity_change
            else: # new_type == 'OUT'
                new_remaining_qty -= new_quantity_change
        else:
            # ใช้ค่าเดิมของ movement ที่ตามมา
            if sub_move['type'] == 'IN' or sub_move['type'] == 'RETURN':
                new_remaining_qty += sub_move['quantity_change']
            else: # sub_move['type'] == 'OUT'
                new_remaining_qty -= sub_move['quantity_change']
        
        # อัปเดต remaining_quantity ในฐานข้อมูล
        if is_postgres:
            cursor.execute("UPDATE tire_movements SET remaining_quantity = %s WHERE id = %s", (new_remaining_qty, sub_move['id']))
        else:
            cursor.execute("UPDATE tire_movements SET remaining_quantity = ? WHERE id = ?", (new_remaining_qty, sub_move['id']))

    conn.commit()


def delete_tire_movement(conn, movement_id, deleted_by_user_id):
    """
    ลบข้อมูลการเคลื่อนไหวสต็อกยาง, บันทึกประวัติการลบ, และปรับยอดคงเหลือ
    """
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    # 1. ดึงข้อมูลการเคลื่อนไหวที่จะลบ (รวมข้อมูล item)
    if is_postgres:
        cursor.execute("""
            SELECT tm.*, t.brand, t.model, t.size
            FROM tire_movements tm
            JOIN tires t ON tm.tire_id = t.id
            WHERE tm.id = %s
        """, (movement_id,))
    else:
        cursor.execute("""
            SELECT tm.*, t.brand, t.model, t.size
            FROM tire_movements tm
            JOIN tires t ON tm.tire_id = t.id
            WHERE tm.id = ?
        """, (movement_id,))

    movement_to_delete = cursor.fetchone()
    if not movement_to_delete:
        raise ValueError("ไม่พบข้อมูลการเคลื่อนไหวสต็อกยางที่ระบุ")

    # แปลงเป็น dict เพื่อใช้งานง่าย
    movement_to_delete_dict = dict(movement_to_delete)
    tire_id = movement_to_delete_dict['tire_id']
    move_type = movement_to_delete_dict['type']
    quantity_change = movement_to_delete_dict['quantity_change']
    movement_timestamp = movement_to_delete_dict['timestamp']

    # 2. บันทึกประวัติการลบลงตาราง deleted_movements
    item_details_str = f"ยาง: {movement_to_delete_dict['brand'].title()} {movement_to_delete_dict['model'].title()} ({movement_to_delete_dict['size']})"
    deleted_at_iso = get_bkk_time().isoformat()
    original_data_json = json.dumps({k: str(v) for k, v in movement_to_delete_dict.items()}) # เก็บข้อมูลเดิมเป็น JSON

    if is_postgres:
        cursor.execute("""
            INSERT INTO deleted_movements (original_table, original_movement_id, item_details, movement_type, quantity_change, deleted_by_user_id, deleted_at, original_data_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, ('tire_movements', movement_id, item_details_str, move_type, quantity_change, deleted_by_user_id, deleted_at_iso, original_data_json))
    else:
        cursor.execute("""
            INSERT INTO deleted_movements (original_table, original_movement_id, item_details, movement_type, quantity_change, deleted_by_user_id, deleted_at, original_data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ('tire_movements', movement_id, item_details_str, move_type, quantity_change, deleted_by_user_id, deleted_at_iso, original_data_json))

    # 3. ปรับยอดสต็อกของยางหลัก (เหมือนเดิม)
    current_tire = get_tire(conn, tire_id)
    if not current_tire:
        raise ValueError("ไม่พบยางหลักที่เกี่ยวข้องกับการเคลื่อนไหวนี้")

    new_quantity_for_main_item = current_tire['quantity']
    if move_type == 'IN' or move_type == 'RETURN':
        new_quantity_for_main_item -= quantity_change
    elif move_type == 'OUT':
        new_quantity_for_main_item += quantity_change
    update_tire_quantity(conn, tire_id, new_quantity_for_main_item)

    # 4. ลบรายการเคลื่อนไหว (เหมือนเดิม)
    if is_postgres:
        cursor.execute("DELETE FROM tire_movements WHERE id = %s", (movement_id,))
    else:
        cursor.execute("DELETE FROM tire_movements WHERE id = ?", (movement_id,))

    # 5. อัปเดต remaining_quantity ของรายการที่ตามมา (เหมือนเดิม)
    # ... (ส่วนนี้ไม่ต้องแก้ไข) ...
    if is_postgres:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM tire_movements WHERE tire_id = %s AND timestamp >= %s ORDER BY timestamp ASC, id ASC", (tire_id, movement_timestamp))
    else:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM tire_movements WHERE tire_id = ? AND timestamp >= ? ORDER BY timestamp ASC, id ASC", (tire_id, movement_timestamp))
    
    subsequent_movements = cursor.fetchall()

    if is_postgres:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type IN ('IN', 'RETURN') THEN quantity_change ELSE -quantity_change END), 0) FROM tire_movements WHERE tire_id = %s AND timestamp < %s", (tire_id, movement_timestamp))
    else:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type IN ('IN', 'RETURN') THEN quantity_change ELSE -quantity_change END), 0) FROM tire_movements WHERE tire_id = ? AND timestamp < ?", (tire_id, movement_timestamp))
    
    current_remaining_qty = cursor.fetchone()[0] or 0

    for sub_move in subsequent_movements:
        if sub_move['type'] == 'IN' or sub_move['type'] == 'RETURN':
            current_remaining_qty += sub_move['quantity_change']
        else:
            current_remaining_qty -= sub_move['quantity_change']
        
        if is_postgres:
            cursor.execute("UPDATE tire_movements SET remaining_quantity = %s WHERE id = %s", (current_remaining_qty, sub_move['id']))
        else:
            cursor.execute("UPDATE tire_movements SET remaining_quantity = ? WHERE id = ?", (current_remaining_qty, sub_move['id']))

    # conn.commit() จะถูกเรียกจาก app.py
    return item_details_str, move_type, quantity_change # คืนค่าสำหรับสร้าง Notification


def delete_wheel_movement(conn, movement_id, deleted_by_user_id):
    """
    ลบข้อมูลการเคลื่อนไหวสต็อกแม็ก, บันทึกประวัติการลบ, และปรับยอดคงเหลือ
    """
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    # 1. ดึงข้อมูลการเคลื่อนไหวที่จะลบ (รวมข้อมูล item)
    if is_postgres:
        cursor.execute("""
            SELECT wm.*, w.brand, w.model, w.pcd
            FROM wheel_movements wm
            JOIN wheels w ON wm.wheel_id = w.id
            WHERE wm.id = %s
        """, (movement_id,))
    else:
        cursor.execute("""
            SELECT wm.*, w.brand, w.model, w.pcd
            FROM wheel_movements wm
            JOIN wheels w ON wm.wheel_id = w.id
            WHERE wm.id = ?
        """, (movement_id,))

    movement_to_delete = cursor.fetchone()
    if not movement_to_delete:
        raise ValueError("ไม่พบข้อมูลการเคลื่อนไหวสต็อกแม็กที่ระบุ")

    movement_to_delete_dict = dict(movement_to_delete)
    wheel_id = movement_to_delete_dict['wheel_id']
    move_type = movement_to_delete_dict['type']
    quantity_change = movement_to_delete_dict['quantity_change']
    movement_timestamp = movement_to_delete_dict['timestamp']

    # 2. บันทึกประวัติการลบลงตาราง deleted_movements
    item_details_str = f"แม็ก: {movement_to_delete_dict['brand'].title()} {movement_to_delete_dict['model'].title()} ({movement_to_delete_dict['pcd']})"
    deleted_at_iso = get_bkk_time().isoformat()
    original_data_json = json.dumps({k: str(v) for k, v in movement_to_delete_dict.items()})

    if is_postgres:
        cursor.execute("""
            INSERT INTO deleted_movements (original_table, original_movement_id, item_details, movement_type, quantity_change, deleted_by_user_id, deleted_at, original_data_json)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, ('wheel_movements', movement_id, item_details_str, move_type, quantity_change, deleted_by_user_id, deleted_at_iso, original_data_json))
    else:
        cursor.execute("""
            INSERT INTO deleted_movements (original_table, original_movement_id, item_details, movement_type, quantity_change, deleted_by_user_id, deleted_at, original_data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, ('wheel_movements', movement_id, item_details_str, move_type, quantity_change, deleted_by_user_id, deleted_at_iso, original_data_json))

    # 3. ปรับยอดสต็อกของแม็กหลัก
    current_wheel = get_wheel(conn, wheel_id)
    if not current_wheel:
        raise ValueError("ไม่พบแม็กหลักที่เกี่ยวข้องกับการเคลื่อนไหวนี้")

    new_quantity_for_main_item = current_wheel['quantity']
    if move_type == 'IN' or move_type == 'RETURN':
        new_quantity_for_main_item -= quantity_change
    elif move_type == 'OUT':
        new_quantity_for_main_item += quantity_change
    update_wheel_quantity(conn, wheel_id, new_quantity_for_main_item)

    # 4. ลบรายการเคลื่อนไหว
    if is_postgres:
        cursor.execute("DELETE FROM wheel_movements WHERE id = %s", (movement_id,))
    else:
        cursor.execute("DELETE FROM wheel_movements WHERE id = ?", (movement_id,))

    # 5. อัปเดต remaining_quantity ของรายการที่ตามมา
    if is_postgres:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM wheel_movements WHERE wheel_id = %s AND timestamp >= %s ORDER BY timestamp ASC, id ASC", (wheel_id, movement_timestamp))
    else:
        cursor.execute("SELECT id, type, quantity_change, timestamp FROM wheel_movements WHERE wheel_id = ? AND timestamp >= ? ORDER BY timestamp ASC, id ASC", (wheel_id, movement_timestamp))
    
    subsequent_movements = cursor.fetchall()

    if is_postgres:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type IN ('IN', 'RETURN') THEN quantity_change ELSE -quantity_change END), 0) FROM wheel_movements WHERE wheel_id = %s AND timestamp < %s", (wheel_id, movement_timestamp))
    else:
        cursor.execute("SELECT COALESCE(SUM(CASE WHEN type IN ('IN', 'RETURN') THEN quantity_change ELSE -quantity_change END), 0) FROM wheel_movements WHERE wheel_id = ? AND timestamp < ?", (wheel_id, movement_timestamp))
    
    current_remaining_qty = cursor.fetchone()[0] or 0

    for sub_move in subsequent_movements:
        if sub_move['type'] == 'IN' or sub_move['type'] == 'RETURN':
            current_remaining_qty += sub_move['quantity_change']
        else:
            current_remaining_qty -= sub_move['quantity_change']
        
        if is_postgres:
            cursor.execute("UPDATE wheel_movements SET remaining_quantity = %s WHERE id = %s", (current_remaining_qty, sub_move['id']))
        else:
            cursor.execute("UPDATE wheel_movements SET remaining_quantity = ? WHERE id = ?", (current_remaining_qty, sub_move['id']))

    return item_details_str, move_type, quantity_change


def update_tire_quantity(conn, tire_id, new_quantity):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("UPDATE tires SET quantity = %s WHERE id = %s", (new_quantity, tire_id))
    else:
        cursor.execute("UPDATE tires SET quantity = ? WHERE id = ?", (new_quantity, tire_id))
    conn.commit()
    
def update_wheel_quantity(conn, wheel_id, new_quantity):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("UPDATE wheels SET quantity = %s WHERE id = %s", (new_quantity, wheel_id))
    else:
        cursor.execute("UPDATE wheels SET quantity = ? WHERE id = ?", (new_quantity, wheel_id))
    conn.commit()

def add_tire_movement(conn, tire_id, move_type, quantity_change, remaining_quantity, notes, image_filename=None, user_id=None,
                      channel_id=None, online_platform_id=None, wholesale_customer_id=None, return_customer_type=None):
    timestamp = get_bkk_time()
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    commission_amount = 0.0

    if move_type == 'OUT' and channel_id:
        sales_channel_name = get_sales_channel_name(conn, channel_id)
        
        if sales_channel_name == 'หน้าร้าน':
            date_str = timestamp.strftime('%Y-%m-%d')
            # --- START: แก้ไขชื่อตารางตรงนี้ ---
            comm_query = "SELECT commission_amount_per_item FROM commission_programs WHERE item_type = 'tire' AND item_id = ? AND start_date <= ? AND (end_date IS NULL OR end_date >= ?)"
            # --- END: แก้ไขชื่อตารางตรงนี้ ---
            comm_params = (tire_id, date_str, date_str)

            if is_postgres:
                comm_query = comm_query.replace('?', '%s')
            
            cursor.execute(comm_query, comm_params)
            commission_program = cursor.fetchone()

            if commission_program:
                commission_per_item = commission_program['commission_amount_per_item']
                commission_amount = commission_per_item * quantity_change

    # ... (ส่วน INSERT INTO ไม่ต้องแก้ไข) ...
    if is_postgres:
        cursor.execute("""
            INSERT INTO tire_movements (tire_id, timestamp, type, quantity_change, remaining_quantity, notes, image_filename, user_id,
                                        channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
                                        commission_amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (tire_id, timestamp.isoformat(), move_type, quantity_change, remaining_quantity, notes, image_filename, user_id,
              channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
              commission_amount))
    else:
        cursor.execute("""
            INSERT INTO tire_movements (tire_id, timestamp, type, quantity_change, remaining_quantity, notes, image_filename, user_id,
                                        channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
                                        commission_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (tire_id, timestamp.isoformat(), move_type, quantity_change, remaining_quantity, notes, image_filename, user_id,
              channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
              commission_amount))
    conn.commit()

def delete_tire(conn, tire_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("UPDATE tires SET is_deleted = TRUE WHERE id = %s", (tire_id,)) # SOFT DELETE
    else:
        cursor.execute("UPDATE tires SET is_deleted = 1 WHERE id = ?", (tire_id,)) # SOFT DELETE
    conn.commit()

def get_all_tire_brands(conn):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT DISTINCT brand FROM tires WHERE is_deleted = FALSE ORDER BY brand") # Filter soft deleted
    else:
        cursor.execute("SELECT DISTINCT brand FROM tires WHERE is_deleted = 0 ORDER BY brand") # Filter soft deleted
    brands_data = cursor.fetchall()
    return [row['brand'] for row in brands_data]

# เพิ่มฟังก์ชันสำหรับดึงยางที่ถูกลบ
def get_deleted_tires(conn):
    cursor = conn.cursor()
    sql_query = """
        SELECT t.*,
               p.name AS promo_name,
               p.type AS promo_type,
               p.value1 AS promo_value1,
               p.value2 AS promo_value2,
               p.is_active AS promo_is_active
        FROM tires t
        LEFT JOIN promotions p ON t.promotion_id = p.id
        WHERE t.is_deleted = TRUE
        ORDER BY t.brand, t.model
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(sql_query)
    else:
        cursor.execute(sql_query.replace('TRUE', '1')) # SQLite boolean
    tires = cursor.fetchall()
    # Process for display if needed (like index page)
    processed_tires = []
    for tire in tires:
        tire_dict = dict(tire) 
        # Add promo price calculation if needed, similar to get_all_tires
        # For deleted items, usually just basic info is enough, so skip complex calculations here
        processed_tires.append(tire_dict)
    return processed_tires


# เพิ่มฟังก์ชันสำหรับกู้คืนยาง (restore_tire)
def restore_tire(conn, tire_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("UPDATE tires SET is_deleted = FALSE WHERE id = %s", (tire_id,))
    else:
        cursor.execute("UPDATE tires SET is_deleted = 0 WHERE id = ?", (tire_id,))
    conn.commit()

# --- Wheel Functions ---
def get_all_wheels(conn, query=None, brand_filter='all', include_deleted=False): # ADDED include_deleted
    cursor = conn.cursor()
    sql_query = """
        SELECT * FROM wheels
    """
    params = []
    conditions = []

    if not include_deleted: # Conditionally add is_deleted filter
        conditions.append("is_deleted = FALSE" if "psycopg2" in str(type(conn)) else "is_deleted = 0")

    if "psycopg2" in str(type(conn)):
        if query:
            search_term = f"%{query}%"
            conditions.append("(brand ILIKE %s OR model ILIKE %s OR pcd ILIKE %s OR color ILIKE %s)")
            params.extend([search_term, search_term, search_term, search_term])
        
        if brand_filter != 'all':
            conditions.append("brand = %s")
            params.append(brand_filter)
    else: # SQLite
        if query:
            search_term = f"%{query}%"
            conditions.append("(brand LIKE ? OR model LIKE ? OR pcd LIKE ? OR color LIKE ?)")
            params.extend([search_term, search_term, search_term, search_term])
        
        if brand_filter != 'all':
            conditions.append("brand = ?")
            params.append(brand_filter)
    
    if conditions:
        sql_query += " WHERE " + " AND ".join(conditions)
    
    sql_query += " ORDER BY brand, model, diameter"
    
    if "psycopg2" in str(type(conn)):
        cursor.execute(sql_query, params)
    else:
        cursor.execute(sql_query, params)
    wheels_data = cursor.fetchall()
    
    if all(isinstance(row, sqlite3.Row) for row in wheels_data):
        processed_wheels = [dict(row) for row in wheels_data]
    else:
        processed_wheels = wheels_data
    return processed_wheels

def get_wheel(conn, wheel_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT * FROM wheels WHERE id = %s", (wheel_id,))
    else:
        cursor.execute("SELECT * FROM wheels WHERE id = ?", (wheel_id,))
    wheel_data = cursor.fetchone()
    if isinstance(wheel_data, sqlite3.Row):
        wheel_data = dict(wheel_data)
    return wheel_data

def add_wheel(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url, user_id=None):
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    if is_postgres:
        cursor.execute("""
            INSERT INTO wheels (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename, is_deleted)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE) RETURNING id
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url))
        wheel_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO wheels (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url))
        wheel_id = cursor.lastrowid
    
    # เมื่อเพิ่มแม็กใหม่ ให้บันทึกการเคลื่อนไหวเป็น "ซื้อเข้า"
    buy_in_channel_id = get_sales_channel_id(conn, 'ซื้อเข้า')
    add_wheel_movement(conn, wheel_id, 'IN', quantity, quantity, 'เพิ่มแม็กใหม่เข้าสต็อก (ซื้อเข้า)', None, user_id=user_id, channel_id=buy_in_channel_id)
    
    conn.commit()
    return wheel_id
    
def update_wheel(conn, wheel_id, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE wheels SET
                brand = %s,
                model = %s,
                diameter = %s,
                pcd = %s,
                width = %s,
                et = %s,
                quantity = %s,
                color = %s,
                cost = %s,
                cost_online = %s,
                wholesale_price1 = %s,
                wholesale_price2 = %s,
                retail_price = %s,
                image_filename = %s
            WHERE id = %s
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url, wheel_id))
    else:
        cursor.execute("""
            UPDATE wheels SET
                brand = ?,
                model = ?,
                diameter = ?,
                pcd = ?,
                width = ?,
                et = ?,
                color = ?,
                quantity = ?,
                cost = ?,
                cost_online = ?,
                wholesale_price1 = ?,
                wholesale_price2 = ?,
                retail_price = ?,
                image_filename = ?
            WHERE id = ?
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url, wheel_id))
    conn.commit()

def add_wheel_movement(conn, wheel_id, move_type, quantity_change, remaining_quantity, notes, image_filename=None, user_id=None,
                       channel_id=None, online_platform_id=None, wholesale_customer_id=None, return_customer_type=None):
    timestamp = get_bkk_time()
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    commission_amount = 0.0

    if move_type == 'OUT' and channel_id:
        sales_channel_name = get_sales_channel_name(conn, channel_id)
        
        if sales_channel_name == 'หน้าร้าน':
            date_str = timestamp.strftime('%Y-%m-%d')
            # --- START: แก้ไขชื่อตารางตรงนี้ ---
            comm_query = "SELECT commission_amount_per_item FROM commission_programs WHERE item_type = 'wheel' AND item_id = ? AND start_date <= ? AND (end_date IS NULL OR end_date >= ?)"
            # --- END: แก้ไขชื่อตารางตรงนี้ ---
            comm_params = (wheel_id, date_str, date_str)
            if is_postgres:
                comm_query = comm_query.replace('?', '%s')
            
            cursor.execute(comm_query, comm_params)
            commission_program = cursor.fetchone()

            if commission_program:
                commission_per_item = commission_program['commission_amount_per_item']
                commission_amount = commission_per_item * quantity_change

    # ... (ส่วน INSERT INTO ไม่ต้องแก้ไข) ...
    if is_postgres:
        cursor.execute("""
            INSERT INTO wheel_movements (wheel_id, timestamp, type, quantity_change, remaining_quantity, notes, image_filename, user_id,
                                         channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
                                         commission_amount)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (wheel_id, timestamp.isoformat(), move_type, quantity_change, remaining_quantity, notes, image_filename, user_id,
              channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
              commission_amount))
    else:
        cursor.execute("""
            INSERT INTO wheel_movements (wheel_id, timestamp, type, quantity_change, remaining_quantity, notes, image_filename, user_id,
                                         channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
                                         commission_amount)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (wheel_id, timestamp.isoformat(), move_type, quantity_change, remaining_quantity, notes, image_filename, user_id,
              channel_id, online_platform_id, wholesale_customer_id, return_customer_type,
              commission_amount))
    conn.commit()

def add_wheel_import(conn, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO wheels (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename, is_deleted)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, FALSE) RETURNING id
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url))
        wheel_id = cursor.fetchone()['id']
    else:
        cursor.execute("""
            INSERT INTO wheels (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_filename, is_deleted)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url))
        wheel_id = cursor.lastrowid
    conn.commit()
    return wheel_id

def update_wheel_import(conn, wheel_id, brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE wheels SET
                brand = %s,
                model = %s,
                diameter = %s,
                pcd = %s,
                width = %s,
                et = %s,
                color = %s,
                quantity = %s,
                cost = %s,
                cost_online = %s,
                wholesale_price1 = %s,
                wholesale_price2 = %s,
                retail_price = %s,
                image_filename = %s
            WHERE id = %s
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url, wheel_id))
    else:
        cursor.execute("""
            UPDATE wheels SET
                brand = ?,
                model = ?,
                diameter = ?,
                pcd = ?,
                width = ?,
                et = ?,
                color = ?,
                quantity = ?,
                cost = ?,
                cost_online = ?,
                wholesale_price1 = ?,
                wholesale_price2 = ?,
                retail_price = ?,
                image_filename = ?
            WHERE id = ?
        """, (brand, model, diameter, pcd, width, et, color, quantity, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url, wheel_id))
    conn.commit()

def delete_wheel(conn, wheel_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("UPDATE wheels SET is_deleted = TRUE WHERE id = %s", (wheel_id,)) # SOFT DELETE
    else:
        cursor.execute("UPDATE wheels SET is_deleted = 1 WHERE id = ?", (wheel_id,)) # SOFT DELETE
    conn.commit()

def get_all_wheel_brands(conn):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT DISTINCT brand FROM wheels WHERE is_deleted = FALSE ORDER BY brand") # Filter soft deleted
    else:
        cursor.execute("SELECT DISTINCT brand FROM wheels WHERE is_deleted = 0 ORDER BY brand") # Filter soft deleted
    brands_data = cursor.fetchall()
    return [row['brand'] for row in brands_data]

# เพิ่มฟังก์ชันสำหรับดึงแม็กที่ถูกลบ
def get_deleted_wheels(conn):
    cursor = conn.cursor()
    sql_query = """
        SELECT w.*
        FROM wheels w
        WHERE w.is_deleted = TRUE
        ORDER BY w.brand, w.model
    """
    if "psycopg2" in str(type(conn)):
        cursor.execute(sql_query)
    else:
        cursor.execute(sql_query.replace('TRUE', '1')) # SQLite boolean
    wheels = cursor.fetchall()
    processed_wheels = []
    for wheel in wheels:
        processed_wheels.append(dict(wheel)) # Convert to dict
    return processed_wheels

# เพิ่มฟังก์ชันสำหรับกู้คืนแม็ก (restore_wheel)
def restore_wheel(conn, wheel_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("UPDATE wheels SET is_deleted = FALSE WHERE id = %s", (wheel_id,))
    else:
        cursor.execute("UPDATE wheels SET is_deleted = 0 WHERE id = ?", (wheel_id,))
    conn.commit()

def add_wheel_fitment(conn, wheel_id, brand, model, year_start, year_end):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO wheel_fitments (wheel_id, brand, model, year_start, year_end)
            VALUES (%s, %s, %s, %s, %s)
        """, (wheel_id, brand, model, year_start, year_end))
    else:
        cursor.execute("""
            INSERT INTO wheel_fitments (wheel_id, brand, model, year_start, year_end)
            VALUES (?, ?, ?, ?, ?)
        """, (wheel_id, brand, model, year_start, year_end))
    conn.commit()

def get_wheel_fitments(conn, wheel_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT * FROM wheel_fitments WHERE wheel_id = %s ORDER BY brand, model, year_start", (wheel_id,))
    else:
        cursor.execute("SELECT * FROM wheel_fitments WHERE wheel_id = ? ORDER BY brand, model, year_start", (wheel_id,))
    fitments_data = cursor.fetchall()
    if all(isinstance(row, sqlite3.Row) for row in fitments_data):
        processed_fitments = [dict(row) for row in fitments_data]
    else:
        processed_fitments = fitments_data
    return processed_fitments

def delete_wheel_fitment(conn, fitment_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("DELETE FROM wheel_fitments WHERE id = %s", (fitment_id,))
    else:
        cursor.execute("DELETE FROM wheel_fitments WHERE id = ?", (fitment_id,))
    conn.commit()

def add_tire_barcode(conn, tire_id, barcode_string, is_primary=False):
    """
    เพิ่ม Barcode ID ใหม่สำหรับยางที่ระบุ
    tire_id: ID ของยางในตาราง tires
    barcode_string: Barcode ID ที่ยิงได้
    is_primary: True ถ้าต้องการให้เป็นบาร์โค้ดหลักสำหรับยางนี้
    """
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("INSERT INTO tire_barcodes (tire_id, barcode_string, is_primary_barcode) VALUES (%s, %s, %s) ON CONFLICT (barcode_string) DO NOTHING",
                       (tire_id, barcode_string, is_primary))
    else:
        # SQLite
        cursor.execute("INSERT OR IGNORE INTO tire_barcodes (tire_id, barcode_string, is_primary_barcode) VALUES (?, ?, ?)",
                       (tire_id, barcode_string, is_primary))
    # ไม่ต้อง conn.commit() ที่นี่ เพราะจะให้ caller (app.py) จัดการใน transaction

def get_tire_id_by_barcode(conn, barcode_string):
    """
    ค้นหา tire_id จาก barcode_string ที่ระบุ
    """
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT tire_id FROM tire_barcodes WHERE barcode_string = %s", (barcode_string,))
    else:
        cursor.execute("SELECT tire_id FROM tire_barcodes WHERE barcode_string = ?", (barcode_string,))
    result = cursor.fetchone()
    return result['tire_id'] if result else None

def get_barcodes_for_tire(conn, tire_id):
    """
    ดึง Barcode ID ทั้งหมดสำหรับยางที่ระบุ
    """
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT barcode_string, is_primary_barcode FROM tire_barcodes WHERE tire_id = %s ORDER BY is_primary_barcode DESC, barcode_string ASC", (tire_id,))
    else:
        cursor.execute("SELECT barcode_string, is_primary_barcode FROM tire_barcodes WHERE tire_id = ? ORDER BY is_primary_barcode DESC, barcode_string ASC", (tire_id,))
    return [dict(row) for row in cursor.fetchall()]

# --- ฟังก์ชันสำหรับจัดการ Barcode ID ของแม็ก (Wheel Barcodes) ---

def add_wheel_barcode(conn, wheel_id, barcode_string, is_primary=False):
    """
    เพิ่ม Barcode ID ใหม่สำหรับแม็กที่ระบุ
    wheel_id: ID ของแม็กในตาราง wheels
    barcode_string: Barcode ID ที่ยิงได้
    is_primary: True ถ้าต้องการให้เป็นบาร์โค้ดหลักสำหรับแม็กนี้
    """
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("INSERT INTO wheel_barcodes (wheel_id, barcode_string, is_primary_barcode) VALUES (%s, %s, %s) ON CONFLICT (barcode_string) DO NOTHING",
                       (wheel_id, barcode_string, is_primary))
    else:
        # SQLite
        cursor.execute("INSERT OR IGNORE INTO wheel_barcodes (wheel_id, barcode_string, is_primary_barcode) VALUES (?, ?, ?)",
                       (wheel_id, barcode_string, is_primary))
    # ไม่ต้อง conn.commit() ที่นี่
    
def delete_tire_barcode(conn, barcode_string):
    """
    ลบ Barcode ID ที่ระบุออกจากตาราง tire_barcodes
    """
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("DELETE FROM tire_barcodes WHERE barcode_string = %s", (barcode_string,))
    else:
        cursor.execute("DELETE FROM tire_barcodes WHERE barcode_string = ?", (barcode_string,))
        
def delete_wheel_barcode(conn, barcode_string):
    """
    ลบ Barcode ID ที่ระบุออกจากตาราง wheel_barcodes
    """
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("DELETE FROM wheel_barcodes WHERE barcode_string = %s", (barcode_string,))
    else:
        cursor.execute("DELETE FROM wheel_barcodes WHERE barcode_string = ?", (barcode_string,))

def get_wheel_id_by_barcode(conn, barcode_string):
    """
    ค้นหา wheel_id จาก barcode_string ที่ระบุ
    """
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT wheel_id FROM wheel_barcodes WHERE barcode_string = %s", (barcode_string,))
    else:
        cursor.execute("SELECT wheel_id FROM wheel_barcodes WHERE barcode_string = ?", (barcode_string,))
    result = cursor.fetchone()
    return result['wheel_id'] if result else None

def get_barcodes_for_wheel(conn, wheel_id):
    """
    ดึง Barcode ID ทั้งหมดสำหรับแม็กที่ระบุ
    """
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT barcode_string, is_primary_barcode FROM wheel_barcodes WHERE wheel_id = %s ORDER BY is_primary_barcode DESC, barcode_string ASC", (wheel_id,))
    else:
        cursor.execute("SELECT barcode_string, is_primary_barcode FROM wheel_barcodes WHERE wheel_id = ? ORDER BY is_primary_barcode DESC, barcode_string ASC", (wheel_id,))
    return [dict(row) for row in cursor.fetchall()]

def recalculate_all_stock_histories(conn):
    """
    Recalculates the entire history of remaining_quantity for ALL tires and wheels.
    This is a one-time fix for corrupted historical data.
    """
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    print("Starting recalculation for all items...")

    # --- Recalculate for all TIRES ---
    print("Processing tires...")
    cursor.execute("SELECT DISTINCT tire_id FROM tire_movements")
    all_tire_ids = [row['tire_id'] for row in cursor.fetchall()]

    for tire_id in all_tire_ids:
        print(f"  Recalculating for tire_id: {tire_id}")
        # ดึงประวัติทั้งหมดของยางเส้นนี้ เรียงตามเวลา
        sql_get_movements = f"""
            SELECT id, type, quantity_change FROM tire_movements
            WHERE tire_id = ? ORDER BY timestamp ASC, id ASC
        """
        cursor.execute(sql_get_movements.replace('?','%s') if is_postgres else sql_get_movements, (tire_id,))
        movements = cursor.fetchall()

        # เริ่มคำนวณใหม่จาก 0
        running_stock = 0
        for move in movements:
            if move['type'] in ('IN', 'RETURN'):
                running_stock += move['quantity_change']
            elif move['type'] == 'OUT':
                running_stock -= move['quantity_change']

            # อัปเดตค่า remaining_quantity ของทุกรายการให้ถูกต้อง
            sql_update_remaining = f"UPDATE tire_movements SET remaining_quantity = ? WHERE id = ?"
            cursor.execute(sql_update_remaining.replace('?','%s') if is_postgres else sql_update_remaining, (running_stock, move['id']))

    # --- Recalculate for all WHEELS ---
    print("Processing wheels...")
    cursor.execute("SELECT DISTINCT wheel_id FROM wheel_movements")
    all_wheel_ids = [row['wheel_id'] for row in cursor.fetchall()]

    for wheel_id in all_wheel_ids:
        print(f"  Recalculating for wheel_id: {wheel_id}")
        # ดึงประวัติทั้งหมดของแม็กวงนี้ เรียงตามเวลา
        sql_get_movements = f"""
            SELECT id, type, quantity_change FROM wheel_movements
            WHERE wheel_id = ? ORDER BY timestamp ASC, id ASC
        """
        cursor.execute(sql_get_movements.replace('?','%s') if is_postgres else sql_get_movements, (wheel_id,))
        movements = cursor.fetchall()

        running_stock = 0
        for move in movements:
            if move['type'] in ('IN', 'RETURN'):
                running_stock += move['quantity_change']
            elif move['type'] == 'OUT':
                running_stock -= move['quantity_change']

            sql_update_remaining = f"UPDATE wheel_movements SET remaining_quantity = ? WHERE id = ?"
            cursor.execute(sql_update_remaining.replace('?','%s') if is_postgres else sql_update_remaining, (running_stock, move['id']))

    # --- NEW: Recalculate for all SPARE PARTS ---
    print("Processing spare parts...")
    cursor.execute("SELECT DISTINCT spare_part_id FROM spare_part_movements")
    all_spare_part_ids = [row['spare_part_id'] for row in cursor.fetchall()]

    for spare_part_id in all_spare_part_ids:
        print(f"  Recalculating for spare_part_id: {spare_part_id}")
        sql_get_movements = f"""
            SELECT id, type, quantity_change FROM spare_part_movements
            WHERE spare_part_id = ? ORDER BY timestamp ASC, id ASC
        """
        cursor.execute(sql_get_movements.replace('?','%s') if is_postgres else sql_get_movements, (spare_part_id,))
        movements = cursor.fetchall()

        running_stock = 0
        for move in movements:
            if move['type'] in ('IN', 'RETURN'):
                running_stock += move['quantity_change']
            elif move['type'] == 'OUT':
                running_stock -= move['quantity_change']

            sql_update_remaining = f"UPDATE spare_part_movements SET remaining_quantity = ? WHERE id = ?"
            cursor.execute(sql_update_remaining.replace('?','%s') if is_postgres else sql_update_remaining, (running_stock, move['id']))

    conn.commit()
    print("Recalculation complete!")
    return "Recalculation complete for all items."

def add_notification(conn, message, user_id=None):
    """บันทึกข้อความแจ้งเตือนใหม่ลงในฐานข้อมูล"""
    created_at = get_bkk_time().isoformat()
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute(
            "INSERT INTO notifications (message, user_id, created_at, is_read) VALUES (%s, %s, %s, FALSE)",
            (message, user_id, created_at)
        )
    else:
        cursor.execute(
            "INSERT INTO notifications (message, user_id, created_at, is_read) VALUES (?, ?, ?, 0)",
            (message, user_id, created_at)
        )
    # No conn.commit() here, it will be handled by the main route function

def get_all_notifications(conn):
    """ดึงการแจ้งเตือนทั้งหมด เรียงจากใหม่ไปเก่า"""
    cursor = conn.cursor()
    query = """
        SELECT n.id, n.message, n.created_at, n.is_read, u.username
        FROM notifications n
        LEFT JOIN users u ON n.user_id = u.id
        ORDER BY n.created_at DESC
        LIMIT 100
    """
    cursor.execute(query)
    
    # แปลงเวลาให้เป็น BKK Time ก่อนส่งกลับ
    notifications = []
    for row in cursor.fetchall():
        notif_dict = dict(row)
        notif_dict['created_at'] = convert_to_bkk_time(notif_dict['created_at'])
        notifications.append(notif_dict)
    return notifications  

def get_unread_notification_count(conn):
    """นับจำนวนการแจ้งเตือนที่ยังไม่ได้อ่าน"""
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("SELECT COUNT(id) FROM notifications WHERE is_read = FALSE")
    else:
        cursor.execute("SELECT COUNT(id) FROM notifications WHERE is_read = 0")

    # ดึงข้อมูลจาก cursor และปิดการใช้งาน
    count = cursor.fetchone()[0]
    cursor.close()
    return count

def mark_all_notifications_as_read(conn):
    """อัปเดตการแจ้งเตือนทั้งหมดให้เป็น 'อ่านแล้ว'"""
    try:
        cursor = conn.cursor()
        if "psycopg2" in str(type(conn)):
            cursor.execute("UPDATE notifications SET is_read = TRUE WHERE is_read = FALSE")
        else: # SQLite
            cursor.execute("UPDATE notifications SET is_read = 1 WHERE is_read = 0")

        # --- DEBUGGING CODE ---
        # ดึงจำนวนแถวที่ได้รับผลกระทบจากการ UPDATE
        updated_rows = cursor.rowcount
        # พิมพ์ผลลัพธ์ออกทาง Terminal เพื่อตรวจสอบ
        print(f"DEBUG: Attempted to mark notifications as read. Rows affected: {updated_rows}")
        # --- END DEBUGGING ---

        conn.commit()
        cursor.close()
        print("DEBUG: Transaction committed successfully.")

    except Exception as e:
        print(f"ERROR in mark_all_notifications_as_read: {e}")
        conn.rollback() # หากเกิด Error ให้ยกเลิกการเปลี่ยนแปลง

def add_feedback(conn, user_id, feedback_type, message):
    """Adds a new feedback record to the database."""
    created_at = get_bkk_time().isoformat()
    status = 'ใหม่'  # Default status for new feedback
    is_postgres = "psycopg2" in str(type(conn))

    if is_postgres:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO feedback (user_id, feedback_type, message, status, created_at)
            VALUES (%s, %s, %s, %s, %s)
        """, (user_id, feedback_type, message, status, created_at))
    else: # SQLite
        conn.execute("""
            INSERT INTO feedback (user_id, feedback_type, message, status, created_at)
            VALUES (?, ?, ?, ?, ?)
        """, (user_id, feedback_type, message, status, created_at))

def get_all_feedback(conn):
    """Retrieves all feedback, joining with usernames."""
    is_postgres = "psycopg2" in str(type(conn))
    query = """
        SELECT f.id, f.feedback_type, f.message, f.status, f.created_at, u.username
        FROM feedback f
        LEFT JOIN users u ON f.user_id = u.id
        ORDER BY f.created_at DESC
    """
    if is_postgres:
        cursor = conn.cursor()
        cursor.execute(query)
        feedback_list = cursor.fetchall()
    else:
        feedback_list = conn.execute(query).fetchall()

    processed_feedback = []
    for item in feedback_list:
        item_dict = dict(item)
        item_dict['created_at'] = convert_to_bkk_time(item_dict['created_at'])
        processed_feedback.append(item_dict)
    return processed_feedback

def update_feedback_status(conn, feedback_id, new_status):
    """Updates the status of a specific feedback item."""
    is_postgres = "psycopg2" in str(type(conn))
    if is_postgres:
        cursor = conn.cursor()
        cursor.execute("UPDATE feedback SET status = %s WHERE id = %s", (new_status, feedback_id))
    else:
        conn.execute("UPDATE feedback SET status = ? WHERE id = ?", (new_status, feedback_id))

def get_latest_active_announcement(conn):
    """Fetches the most recent active announcement."""
    query = "SELECT id, title, content FROM announcements WHERE is_active = ? ORDER BY created_at DESC LIMIT 1"
    if "psycopg2" in str(type(conn)):
        query = query.replace('?', '%s')
        cursor = conn.cursor()
        cursor.execute(query, (True,))
        return cursor.fetchone()
    else:
        return conn.execute(query, (1,)).fetchone()

def get_all_announcements(conn):
    """Fetches all announcements for the admin page."""
    # --- START: ส่วนที่แก้ไข ---
    is_postgres = "psycopg2" in str(type(conn))
    query = "SELECT id, title, content, is_active, created_at FROM announcements ORDER BY created_at DESC"
    
    if is_postgres:
        cursor = conn.cursor()
        cursor.execute(query)
        items = cursor.fetchall()
    else: # SQLite
        items = conn.execute(query).fetchall()
    # --- END: ส่วนที่แก้ไข ---

    processed = []
    for item in items:
        item_dict = dict(item)
        item_dict['created_at'] = convert_to_bkk_time(item_dict['created_at'])
        processed.append(item_dict)
    return processed

def add_announcement(conn, title, content, is_active):
    """Adds a new announcement."""
    created_at = get_bkk_time().isoformat()
    is_postgres = "psycopg2" in str(type(conn))
    query = "INSERT INTO announcements (title, content, is_active, created_at) VALUES (?, ?, ?, ?)"
    
    if is_postgres:
        query = query.replace('?', '%s')
        cursor = conn.cursor()
        cursor.execute(query, (title, content, is_active, created_at))
    else: # SQLite
        conn.execute(query, (title, content, is_active, created_at))

def update_announcement_status(conn, announcement_id, is_active):
    """Activates or deactivates an announcement."""
    is_postgres = "psycopg2" in str(type(conn))
    query = "UPDATE announcements SET is_active = ? WHERE id = ?"
    
    if is_postgres:
        query = query.replace('?', '%s')
        cursor = conn.cursor()
        cursor.execute(query, (is_active, announcement_id))
    else: # SQLite
        conn.execute(query, (is_active, announcement_id))

def deactivate_all_announcements(conn):
    """Deactivates all other announcements."""
    is_postgres = "psycopg2" in str(type(conn))
    query = "UPDATE announcements SET is_active = ?"
    
    if is_postgres:
        query = query.replace('?', '%s')
        cursor = conn.cursor()
        cursor.execute(query, (False,))
    else: # SQLite
        conn.execute(query, (False,))

def get_wholesale_customers_with_summary(conn, query=None):
    """
    ดึงข้อมูลลูกค้าค้าส่งทั้งหมดพร้อมสรุปยอดซื้อ (OUT) รวม
    และสามารถค้นหาตามชื่อได้
    """
    is_postgres = "psycopg2" in str(type(conn))

    # ใช้ Subquery เพื่อรวมยอดซื้อจากทั้งยางและแม็ก
    sql = f"""
        SELECT
            wc.id,
            wc.name,
            COALESCE(SUM(total_out.quantity), 0) as total_items_purchased
        FROM wholesale_customers wc
        LEFT JOIN (
            SELECT wholesale_customer_id, quantity_change as quantity FROM tire_movements WHERE type = 'OUT'
            UNION ALL
            SELECT wholesale_customer_id, quantity_change as quantity FROM wheel_movements WHERE type = 'OUT'
            UNION ALL -- NEW: Include spare_part_movements
            SELECT wholesale_customer_id, quantity_change as quantity FROM spare_part_movements WHERE type = 'OUT'
        ) AS total_out ON wc.id = total_out.wholesale_customer_id
    """

    params = []
    where_clauses = []

    if query:
        like_operator = "ILIKE" if is_postgres else "LIKE"
        placeholder = "%s" if is_postgres else "?"
        where_clauses.append(f"wc.name {like_operator} {placeholder}")
        params.append(f"%{query}%")

    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)

    sql += """
        GROUP BY wc.id, wc.name
        ORDER BY wc.name;
    """

    cursor = conn.cursor()
    cursor.execute(sql, tuple(params))

    return [dict(row) for row in cursor.fetchall()]

def get_wholesale_customer_details(conn, customer_id):
    """
    ดึงข้อมูลชื่อลูกค้าและข้อมูลสรุป (ยอดซื้อรวม, วันที่ซื้อล่าสุด)
    """
    is_postgres = "psycopg2" in str(type(conn))
    placeholder = "%s" if is_postgres else "?"

    sql = f"""
        SELECT
            wc.id, -- <<< ADD THIS LINE
            wc.name,
            COALESCE(SUM(m.quantity_change), 0) as total_items_purchased,
            MAX(m.timestamp) as last_purchase_date
        FROM wholesale_customers wc
        LEFT JOIN (
            SELECT wholesale_customer_id, quantity_change, timestamp FROM tire_movements WHERE type = 'OUT'
            UNION ALL
            SELECT wholesale_customer_id, quantity_change, timestamp FROM wheel_movements WHERE type = 'OUT'
        ) AS m ON wc.id = m.wholesale_customer_id
        WHERE wc.id = {placeholder}
        GROUP BY wc.id, wc.name;
    """
    cursor = conn.cursor()
    cursor.execute(sql, (customer_id,))
    customer_data = cursor.fetchone()

    if customer_data:
        customer_dict = dict(customer_data)
        if customer_dict.get('last_purchase_date'):
            customer_dict['last_purchase_date'] = convert_to_bkk_time(customer_dict['last_purchase_date'])
        return customer_dict
    return None

def get_wholesale_customer_purchase_history(conn, customer_id, start_date=None, end_date=None):
    """
    ดึงประวัติการซื้อ (OUT) ทั้งหมดของลูกค้า สามารถกรองตามช่วงวันที่ได้
    """
    is_postgres = "psycopg2" in str(type(conn))
    placeholder = "%s" if is_postgres else "?"
    timestamp_cast = "::timestamptz" if is_postgres else ""

    sql_parts = []
    params = []

    # Tire Movements
    sql_parts.append(f"""
        SELECT 'tire' as item_type, tm.timestamp, t.brand, t.model, t.size AS item_details, tm.quantity_change
        FROM tire_movements tm
        JOIN tires t ON tm.tire_id = t.id
        WHERE tm.type = 'OUT' AND tm.wholesale_customer_id = {placeholder}
    """)
    params.append(customer_id)
    if start_date and end_date:
        sql_parts[-1] += f" AND tm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast}"
        params.extend([start_date.isoformat(), end_date.isoformat()])

    # Wheel Movements
    wheel_size_concat = "CONCAT(w.diameter, 'x', w.width, ' ', w.pcd)" if is_postgres else "(w.diameter || 'x' || w.width || ' ' || w.pcd)"
    sql_parts.append(f"""
        SELECT 'wheel' as item_type, wm.timestamp, w.brand, w.model,
               {wheel_size_concat} as item_details,
               wm.quantity_change
        FROM wheel_movements wm
        JOIN wheels w ON wm.wheel_id = w.id
        WHERE wm.type = 'OUT' AND wm.wholesale_customer_id = {placeholder}
    """)
    params.append(customer_id)
    if start_date and end_date:
        sql_parts[-1] += f" AND wm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast}"
        params.extend([start_date.isoformat(), end_date.isoformat()])

    # NEW: Spare Part Movements
    spare_part_details_concat = "CONCAT(sp.name, ' (', COALESCE(sp.brand, ''), ')')" if is_postgres else "(sp.name || ' (' || COALESCE(sp.brand, '') || ')')"
    sql_parts.append(f"""
        SELECT 'spare_part' as item_type, spm.timestamp, sp.name AS brand, sp.part_number AS model,
               {spare_part_details_concat} as item_details, -- Changed size to item_details for spare_parts
               spm.quantity_change
        FROM spare_part_movements spm
        JOIN spare_parts sp ON spm.spare_part_id = sp.id
        WHERE spm.type = 'OUT' AND spm.wholesale_customer_id = {placeholder}
    """)
    params.append(customer_id)
    if start_date and end_date:
        sql_parts[-1] += f" AND spm.timestamp BETWEEN {placeholder}{timestamp_cast} AND {placeholder}{timestamp_cast}"
        params.extend([start_date.isoformat(), end_date.isoformat()])


    full_sql = " UNION ALL ".join(sql_parts)
    full_sql += " ORDER BY timestamp DESC"

    # Replace placeholders for SQLite
    if not is_postgres:
        full_sql = full_sql.replace(timestamp_cast, "") # Remove timestamp cast for SQLite
        full_sql = full_sql.replace(placeholder, '?')

    cursor = conn.cursor()
    cursor.execute(full_sql, tuple(params))

    history = []
    for row in cursor.fetchall():
        row_dict = dict(row)
        row_dict['timestamp'] = convert_to_bkk_time(row_dict['timestamp'])
        history.append(row_dict)
    return history

def add_activity_log(conn, user_id, endpoint, method, url):
    """บันทึกกิจกรรมของผู้ใช้ลงฐานข้อมูล"""
    timestamp = get_bkk_time().isoformat()
    is_postgres = "psycopg2" in str(type(conn))
    query = "INSERT INTO activity_logs (user_id, timestamp, endpoint, method, url) VALUES (?, ?, ?, ?, ?)"
    params = (user_id, timestamp, endpoint, method, url)

    if is_postgres:
        query = query.replace('?', '%s')

    cursor = conn.cursor()
    cursor.execute(query, params)
    # conn.commit() is handled by the request teardown

def get_activity_logs(conn, limit=200):
    """ดึงประวัติการใช้งานล่าสุด"""
    query = """
        SELECT a.id, a.timestamp, a.endpoint, a.method, a.url, u.username
        FROM activity_logs a
        LEFT JOIN users u ON a.user_id = u.id
        ORDER BY a.timestamp DESC
        LIMIT ?
    """
    if "psycopg2" in str(type(conn)):
        query = query.replace('?', '%s')

    cursor = conn.cursor()
    cursor.execute(query, (limit,))

    logs = []
    for row in cursor.fetchall():
        log_dict = dict(row)
        log_dict['timestamp'] = convert_to_bkk_time(log_dict['timestamp'])
        logs.append(log_dict)
    return logs

def delete_old_activity_logs(conn, days=7):
    """ลบ Log ที่เก่ากว่าวันที่กำหนด"""
    cutoff_date = get_bkk_time() - timedelta(days=days)
    is_postgres = "psycopg2" in str(type(conn))
    placeholder = "%s" if is_postgres else "?"
    query = f"DELETE FROM activity_logs WHERE timestamp < {placeholder}"

    cursor = conn.cursor()
    cursor.execute(query, (cutoff_date.isoformat(),))
    deleted_count = cursor.rowcount
    conn.commit()
    return deleted_count

def get_setting(conn, key):
    """ดึงค่าการตั้งค่าจากตาราง app_settings"""
    cursor = conn.cursor()
    query = "SELECT value FROM app_settings WHERE key = ?"
    params = (key,)
    if "psycopg2" in str(type(conn)):
        query = query.replace('?', '%s')

    cursor.execute(query, params)
    result = cursor.fetchone()
    cursor.close()
    return result['value'] if result else None

def set_setting(conn, key, value):
    """เพิ่มหรืออัปเดตค่าการตั้งค่าในตาราง app_settings"""
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    if is_postgres:
        # ใช้ ON CONFLICT เพื่อทำ UPSERT (UPDATE or INSERT)
        query = """
            INSERT INTO app_settings (key, value) VALUES (%s, %s)
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
        """
    else: # SQLite
        query = "INSERT OR REPLACE INTO app_settings (key, value) VALUES (?, ?)"

# --- Reconciliation Functions (NEW) ---

def get_reconciliation_for_date(conn, report_date):
    """
    ดึงข้อมูลการกระทบยอดสำหรับวันที่ระบุ
    report_date: ต้องเป็นอ็อบเจกต์ date ของ Python
    """
    is_postgres = "psycopg2" in str(type(conn))
    
    # แปลง date object เป็น string 'YYYY-MM-DD' สำหรับ query
    date_str = report_date.strftime('%Y-%m-%d')
    
    query = "SELECT * FROM daily_reconciliations WHERE reconciliation_date = ?"
    params = (date_str,)
    
    if is_postgres:
        query = query.replace('?', '%s')
    
    cursor = conn.cursor()
    cursor.execute(query, params)
    reconciliation_data = cursor.fetchone()
    
    if reconciliation_data:
        rec_dict = dict(reconciliation_data)
        # แปลง JSON string กลับเป็น Python object
        if rec_dict.get('manager_ledger_json'):
            rec_dict['manager_ledger'] = json.loads(rec_dict['manager_ledger_json'])
        else:
            rec_dict['manager_ledger'] = []
            
        if rec_dict.get('system_snapshot_json'):
            rec_dict['system_snapshot'] = json.loads(rec_dict['system_snapshot_json'])
        else:
            rec_dict['system_snapshot'] = []
            
        return rec_dict
        
    return None

def get_or_create_reconciliation_for_date(conn, report_date, manager_id):
    """
    ดึงข้อมูลกระทบยอดของวันนั้นๆ หรือสร้างใหม่ถ้ายังไม่มี
    """
    existing_rec = get_reconciliation_for_date(conn, report_date)
    if existing_rec:
        return existing_rec

    # ถ้าไม่มี ให้สร้างใหม่
    is_postgres = "psycopg2" in str(type(conn))
    date_str = report_date.strftime('%Y-%m-%d')
    created_at_iso = get_bkk_time().isoformat()
    
    query = "INSERT INTO daily_reconciliations (reconciliation_date, manager_id, created_at) VALUES (?, ?, ?)"
    params = (date_str, manager_id, created_at_iso)

    if is_postgres:
        query = query.replace('?', '%s') + " RETURNING id"
    
    cursor = conn.cursor()
    cursor.execute(query, params)
    
    # ไม่ต้อง commit ที่นี่ จะให้ app.py จัดการ
    
    return get_reconciliation_for_date(conn, report_date) # ดึงข้อมูลที่เพิ่งสร้างขึ้นมาใหม่

def update_manager_ledger(conn, reconciliation_id, ledger_data):
    """
    อัปเดตข้อมูลในฝั่ง 'สมุดบันทึกของผู้จัดการ'
    ledger_data: ต้องเป็น list/dict ของ Python
    """
    is_postgres = "psycopg2" in str(type(conn))
    
    # แปลง Python object เป็น JSON string
    ledger_json = json.dumps(ledger_data, ensure_ascii=False)
    
    query = "UPDATE daily_reconciliations SET manager_ledger_json = ? WHERE id = ?"
    # สร้างตัวแปร params ให้ถูกต้อง
    params = (ledger_json, reconciliation_id)
    
    if is_postgres:
        query = query.replace('?', '%s')
        
    cursor = conn.cursor()
    # ใช้ตัวแปร params ที่ถูกต้อง
    cursor.execute(query, params)

def complete_reconciliation(conn, reconciliation_id):
    """Updates the status of a reconciliation to 'completed' and sets the completed_at timestamp."""
    completed_at_iso = get_bkk_time().isoformat()
    is_postgres = "psycopg2" in str(type(conn))
    
    query = "UPDATE daily_reconciliations SET status = ?, completed_at = ? WHERE id = ?"
    params = ('completed', completed_at_iso, reconciliation_id)

    if is_postgres:
        query = query.replace('?', '%s')

    cursor = conn.cursor()
    cursor.execute(query, params)

def get_reconciliation_by_id(conn, reconciliation_id):
    """Fetches a single reconciliation record by its ID."""
    is_postgres = "psycopg2" in str(type(conn))
    query = "SELECT * FROM daily_reconciliations WHERE id = ?"
    if is_postgres:
        query = query.replace('?', '%s')
    
    cursor = conn.cursor()
    cursor.execute(query, (reconciliation_id,))
    return cursor.fetchone()

def add_tire_cost_history(conn, tire_id, old_cost, new_cost, user_id, notes=""):
    """บันทึกการเปลี่ยนแปลงราคาทุนของยาง"""
    changed_at = get_bkk_time().isoformat()
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    
    query = "INSERT INTO tire_cost_history (tire_id, changed_at, old_cost_sc, new_cost_sc, user_id, notes) VALUES (?, ?, ?, ?, ?, ?)"
    params = (tire_id, changed_at, old_cost, new_cost, user_id, notes)

    if is_postgres:
        query = query.replace('?', '%s')

    cursor.execute(query, params)
    # ไม่ต้อง commit ที่นี่ เพราะจะถูกจัดการโดยฟังก์ชันที่เรียกใช้

def get_tire_cost_history(conn, tire_id):
    """ดึงประวัติการเปลี่ยนแปลงราคาทุนของยางที่ระบุ"""
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    
    query = """
        SELECT h.*, u.username
        FROM tire_cost_history h
        LEFT JOIN users u ON h.user_id = u.id
        WHERE h.tire_id = ?
        ORDER BY h.changed_at DESC
    """
    params = (tire_id,)
    
    if is_postgres:
        query = query.replace('?', '%s')
        
    cursor.execute(query, params)
    
    history = []
    for row in cursor.fetchall():
        history_item = dict(row)
        history_item['changed_at'] = convert_to_bkk_time(history_item['changed_at'])
        history.append(history_item)
        
    return history

def update_single_tire_cost(conn, tire_id, cost_type, new_cost, user_id):
    """
    อัปเดตราคาทุนเพียงคอลัมน์เดียวสำหรับยางที่ระบุ และบันทึกประวัติการเปลี่ยนแปลง
    """
    # ตรวจสอบว่า cost_type เป็นค่าที่อนุญาตอีกครั้งเพื่อความปลอดภัย
    allowed_cost_types = ['cost_sc', 'cost_dunlop', 'cost_online']
    if cost_type not in allowed_cost_types:
        raise ValueError("ประเภทของราคาทุนไม่ถูกต้อง")

    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    placeholder = "%s" if is_postgres else "?"

    # 1. ดึงข้อมูลราคาทุนเดิม
    # SQL Injection is prevented by the check above
    query_old_cost = f"SELECT {cost_type} FROM tires WHERE id = {placeholder}"
    cursor.execute(query_old_cost, (tire_id,))
    tire_data = cursor.fetchone()

    if not tire_data:
        raise ValueError("ไม่พบยางที่ระบุ")

    old_cost = tire_data[cost_type]

    # 2. เปรียบเทียบและบันทึกประวัติ (เฉพาะเมื่อมีการเปลี่ยนแปลง)
    # แปลง new_cost เป็น float ถ้าไม่ใช่ None เพื่อการเปรียบเทียบที่แม่นยำ
    new_cost_float = float(new_cost) if new_cost is not None else None

    if old_cost != new_cost_float:
        # เราจะบันทึกเฉพาะ cost_sc ลงใน history ตามโครงสร้างปัจจุบัน
        # หากต้องการบันทึก cost_type อื่นๆ ด้วย อาจต้องปรับแก้ตาราง tire_cost_history
        if cost_type == 'cost_sc':
            add_tire_cost_history(
                conn=conn,
                tire_id=tire_id,
                old_cost=old_cost,
                new_cost=new_cost_float,
                user_id=user_id,
                notes="แก้ไขทุนจากหน้า Index"
            )

        # 3. อัปเดตค่าใหม่ลงในตาราง tires
        # SQL Injection is prevented by the check above
        update_query = f"UPDATE tires SET {cost_type} = {placeholder} WHERE id = {placeholder}"
        cursor.execute(update_query, (new_cost_float, tire_id))
  

def get_commission_programs_for_date(conn, for_date):
    """ดึงโปรแกรมคอมมิชชั่นที่ Active ทั้งหมดสำหรับวันที่ระบุ"""
    date_str = for_date.strftime('%Y-%m-%d')
    is_postgres = "psycopg2" in str(type(conn))
    
    # Logic: วันที่ที่ต้องการ ต้องอยู่ระหว่าง start_date และ end_date (หรือ end_date เป็น NULL)
    query = f"""
        SELECT cp.id, cp.item_type, cp.item_id, cp.commission_amount_per_item,
               cp.start_date, cp.end_date,
               CASE
                   WHEN cp.item_type = 'tire' THEN t.brand || ' ' || t.model || ' ' || t.size
                   WHEN cp.item_type = 'wheel' THEN w.brand || ' ' || w.model || ' ' || w.pcd
                   WHEN cp.item_type = 'spare_part' THEN sp.name || ' (' || sp.part_number || ')'
               END as item_description
        FROM commission_programs cp
        LEFT JOIN tires t ON cp.item_id = t.id AND cp.item_type = 'tire'
        LEFT JOIN wheels w ON cp.item_id = w.id AND cp.item_type = 'wheel'
        LEFT JOIN spare_parts sp ON cp.item_id = sp.id AND cp.item_type = 'spare_part'
        WHERE cp.start_date <= ? AND (cp.end_date IS NULL OR cp.end_date >= ?)
    """
    if is_postgres:
        query = query.replace("||", "||").replace('?', '%s')
    
    cursor = conn.cursor()
    cursor.execute(query, (date_str, date_str))
    return [dict(row) for row in cursor.fetchall()]

def set_commission_program(conn, start_date, end_date, item_type, item_id, amount, user_id):
    """ตั้งค่าโปรแกรมคอมมิชชั่นสำหรับสินค้าในช่วงเวลาที่กำหนด"""
    start_date_str = start_date.strftime('%Y-%m-%d')
    end_date_str = end_date.strftime('%Y-%m-%d') if end_date else None
    now_iso = get_bkk_time().isoformat()
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))

    # Logic: เราจะลบโปรแกรมเก่าที่อาจจะทับซ้อนกันออกก่อน แล้วสร้างใหม่
    # (นี่เป็นวิธีที่ง่ายที่สุดในการจัดการช่วงเวลาทับซ้อน)
    delete_query = "DELETE FROM commission_programs WHERE item_type = ? AND item_id = ?"
    if is_postgres:
        delete_query = delete_query.replace('?', '%s')
    cursor.execute(delete_query, (item_type, item_id))
    
    insert_query = """
        INSERT INTO commission_programs (start_date, end_date, item_type, item_id, commission_amount_per_item, user_id, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """
    if is_postgres:
        insert_query = insert_query.replace('?', '%s')
        
    cursor.execute(insert_query, (start_date_str, end_date_str, item_type, item_id, amount, user_id, now_iso))
    conn.commit()

def delete_commission_program(conn, program_id):
    """ลบโปรแกรมคอมมิชชั่น"""
    cursor = conn.cursor()
    query = "DELETE FROM commission_programs WHERE id = ?"
    if "psycopg2" in str(type(conn)):
        query = query.replace('?', '%s')
    cursor.execute(query, (program_id,))
    conn.commit()

def calculate_and_log_commission_summary(conn, for_date):
    """
    คำนวณสรุปยอดขายและคอมมิชชั่นของสินค้าโปรแกรมในวันที่กำหนด และบันทึกลง commission_summary_log
    """
    date_str = for_date.strftime('%Y-%m-%d')
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    placeholder = "%s" if is_postgres else "?"
    
    # 1. ตรวจสอบว่าเคยสรุปของวันนี้ไปแล้วหรือยัง
    cursor.execute(f"SELECT id FROM commission_summary_log WHERE summary_date = {placeholder}", (date_str,))
    if cursor.fetchone():
        raise ValueError("ได้ทำการสรุปยอดของวันนี้ไปแล้ว")

    # 2. รวมข้อมูลยอดขายจาก movements ทั้ง 3 ตาราง เฉพาะรายการที่มีคอมมิชชั่น
    query = f"""
        SELECT 
            m.item_type,
            m.item_id,
            m.item_description,
            SUM(m.quantity_change) as total_units_sold,
            SUM(m.commission_amount) as total_commission
        FROM (
            SELECT 'tire' as item_type, tm.tire_id as item_id, t.brand || ' ' || t.model || ' ' || t.size as item_description, tm.quantity_change, tm.commission_amount, tm.timestamp FROM tire_movements tm JOIN tires t ON tm.tire_id = t.id
            UNION ALL
            SELECT 'wheel' as item_type, wm.wheel_id as item_id, w.brand || ' ' || w.model || ' ' || w.pcd as item_description, wm.quantity_change, wm.commission_amount, wm.timestamp FROM wheel_movements wm JOIN wheels w ON wm.wheel_id = w.id
            UNION ALL
            SELECT 'spare_part' as item_type, spm.spare_part_id as item_id, sp.name || ' (' || sp.part_number || ')' as item_description, spm.quantity_change, spm.commission_amount, spm.timestamp FROM spare_part_movements spm JOIN spare_parts sp ON spm.spare_part_id = sp.id
        ) m
        WHERE {get_sql_date_format_for_query('m.timestamp')} = {placeholder} AND m.commission_amount > 0
        GROUP BY m.item_type, m.item_id, m.item_description
    """
    if is_postgres:
        query = query.replace("||", "||").replace('?', '%s') # SQLite and PG use || for concat
    
    cursor.execute(query, (date_str,))
    summary_details = [dict(row) for row in cursor.fetchall()]

    if not summary_details:
        raise ValueError("ไม่พบรายการขายที่มีคอมมิชชั่นในวันนี้")

    # 3. บันทึกผลลัพธ์ลงตาราง commission_summary_log
    details_json = json.dumps(summary_details, ensure_ascii=False)
    created_at = get_bkk_time().isoformat()

    insert_query = f"INSERT INTO commission_summary_log (summary_date, details_json, created_at) VALUES ({placeholder}, {placeholder}, {placeholder})"
    if is_postgres:
        insert_query = insert_query.replace('?', '%s')
        
    cursor.execute(insert_query, (date_str, details_json, created_at))
    conn.commit()
    return len(summary_details)

# ใน database.py

def get_live_commission_summary(conn, for_date):
    """
    คำนวณสรุปยอดขายและคอมมิชชั่นของสินค้าโปรแกรมในวันที่กำหนดแบบสดๆ (สำหรับแสดงผลก่อนปิดยอด)
    """
    date_str = for_date.strftime('%Y-%m-%d')
    cursor = conn.cursor()
    is_postgres = "psycopg2" in str(type(conn))
    placeholder = "%s" if is_postgres else "?"

    # ใช้ Query เดียวกันกับฟังก์ชัน calculate_and_log... เพื่อความสอดคล้องกัน
    query = f"""
        SELECT 
            m.item_type,
            m.item_id,
            m.item_description,
            SUM(m.quantity_change) as total_units_sold,
            SUM(m.commission_amount) as total_commission
        FROM (
            SELECT 'tire' as item_type, tm.tire_id as item_id, t.brand || ' ' || t.model || ' ' || t.size as item_description, tm.quantity_change, tm.commission_amount, tm.timestamp FROM tire_movements tm JOIN tires t ON tm.tire_id = t.id
            UNION ALL
            SELECT 'wheel' as item_type, wm.wheel_id as item_id, w.brand || ' ' || w.model || ' ' || w.pcd as item_description, wm.quantity_change, wm.commission_amount, wm.timestamp FROM wheel_movements wm JOIN wheels w ON wm.wheel_id = w.id
            UNION ALL
            SELECT 'spare_part' as item_type, spm.spare_part_id as item_id, sp.name || ' (' || sp.part_number || ')' as item_description, spm.quantity_change, spm.commission_amount, spm.timestamp FROM spare_part_movements spm JOIN spare_parts sp ON spm.spare_part_id = sp.id
        ) m
        WHERE {get_sql_date_format_for_query('m.timestamp')} = {placeholder} AND m.commission_amount > 0
        GROUP BY m.item_type, m.item_id, m.item_description
        ORDER BY total_commission DESC
    """
    if is_postgres:
        query = query.replace("||", "||").replace('?', '%s')
    
    cursor.execute(query, (date_str,))
    summary_details = [dict(row) for row in cursor.fetchall()]
    return summary_details