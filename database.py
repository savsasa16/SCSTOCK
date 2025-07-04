# database.py
import sqlite3
from datetime import datetime
import pytz
import re
from werkzeug.security import generate_password_hash, check_password_hash
import os
from urllib.parse import urlparse

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
    bkk_tz = pytz.timezone('Asia/Bangkok')
    return datetime.now(bkk_tz)

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
                created_at TEXT NOT NULL
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

    # Tire Movements Table (ไม่มี ON DELETE CASCADE)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_movements (
                id SERIAL PRIMARY KEY,
                tire_id INTEGER NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                type VARCHAR(50) NOT NULL,
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                image_filename VARCHAR(500) NULL,
                user_id INTEGER NULL,
                FOREIGN KEY (tire_id) REFERENCES tires(id), -- ไม่มี ON DELETE CASCADE
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                tire_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                image_filename TEXT NULL,
                user_id INTEGER NULL,
                FOREIGN KEY (tire_id) REFERENCES tires(id), -- ไม่มี ON DELETE CASCADE
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

    # Wheel Movements Table (ไม่มี ON DELETE CASCADE)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_movements (
                id SERIAL PRIMARY KEY,
                wheel_id INTEGER NOT NULL,
                timestamp TIMESTAMP WITH TIME ZONE NOT NULL,
                type VARCHAR(50) NOT NULL,
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                image_filename VARCHAR(500) NULL,
                user_id INTEGER NULL,
                FOREIGN KEY (wheel_id) REFERENCES wheels(id), -- ไม่มี ON DELETE CASCADE
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_movements (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                wheel_id INTEGER NOT NULL,
                timestamp TEXT NOT NULL,
                type TEXT NOT NULL,
                quantity_change INTEGER NOT NULL,
                remaining_quantity INTEGER NOT NULL,
                notes TEXT,
                image_filename TEXT NULL,
                user_id INTEGER NULL,
                FOREIGN KEY (wheel_id) REFERENCES wheels(id), -- ไม่มี ON DELETE CASCADE
                FOREIGN KEY (user_id) REFERENCES users(id)
            );
        """)

    # Wheel Fitments Table (ยังคงมี ON DELETE CASCADE)
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

    # Users Table (ไม่มีอะไรเปลี่ยน)
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
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_barcodes (
                barcode_string VARCHAR(255) NOT NULL UNIQUE,
                tire_id INTEGER NOT NULL,
                is_primary_barcode BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (barcode_string),
                FOREIGN KEY (tire_id) REFERENCES tires(id) ON DELETE CASCADE
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS tire_barcodes (
                barcode_string TEXT NOT NULL UNIQUE,
                tire_id INTEGER NOT NULL,
                is_primary_barcode BOOLEAN DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (barcode_string),
                FOREIGN KEY (tire_id) REFERENCES tires(id) ON DELETE CASCADE
            );
        """)
    if is_postgres:
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_barcodes (
                barcode_string VARCHAR(255) NOT NULL UNIQUE,
                wheel_id INTEGER NOT NULL,
                is_primary_barcode BOOLEAN DEFAULT FALSE,
                created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (barcode_string),
                FOREIGN KEY (wheel_id) REFERENCES wheels(id) ON DELETE CASCADE
            );
        """)
    else: # SQLite
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS wheel_barcodes (
                barcode_string TEXT NOT NULL UNIQUE,
                wheel_id INTEGER NOT NULL,
                is_primary_barcode BOOLEAN DEFAULT 0,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (barcode_string),
                FOREIGN KEY (wheel_id) REFERENCES wheels(id) ON DELETE CASCADE
            );
        """)
        
    conn.commit()

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
        else:
            cursor.execute("INSERT INTO users (username, password, role) VALUES (?, ?, ?)", (username, hashed_password, role))
            user_id = cursor.lastrowid
        conn.commit()
        return user_id
    except (sqlite3.IntegrityError, Exception) as e:
        if "UNIQUE constraint failed" in str(e) or "duplicate key value violates unique constraint" in str(e):
            return None
        else:
            raise

def update_user_role(conn, user_id, new_role):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("UPDATE users SET role = %s WHERE id = %s", (new_role, user_id))
    else:
        cursor.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
    conn.commit()

def delete_user(conn, user_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("DELETE FROM users WHERE id = %s", (user_id,))
    else:
        cursor.execute("DELETE FROM users WHERE id = ?", (user_id,))
    conn.commit()

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
    sql_query = "SELECT * FROM promotions"
    params = []
    if not include_inactive:
        sql_query += " WHERE is_active = TRUE" if "psycopg2" in str(type(conn)) else " WHERE is_active = 1"
    sql_query += " ORDER BY name"
    if "psycopg2" in str(type(conn)):
        cursor.execute(sql_query, params)
    else:
        cursor.execute(sql_query, params)
    promotions_data = cursor.fetchall()
    if all(isinstance(row, sqlite3.Row) for row in promotions_data):
        processed_promotions = [dict(row) for row in promotions_data]
    else:
        processed_promotions = promotions_data
    return processed_promotions

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
    
    add_tire_movement(conn, tire_id, 'IN', quantity, quantity, 'เพิ่มยางใหม่เข้าสต็อก', None, user_id=user_id)
    
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
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            SELECT tm.*, t.brand, t.model, t.size, u.username
            FROM tire_movements tm
            JOIN tires t ON tm.tire_id = t.id
            LEFT JOIN users u ON tm.user_id = u.id
            WHERE tm.id = %s
        """, (movement_id,))
    else:
        cursor.execute("""
            SELECT tm.*, t.brand, t.model, t.size, u.username
            FROM tire_movements tm
            JOIN tires t ON tm.tire_id = t.id
            LEFT JOIN users u ON tm.user_id = u.id
            WHERE tm.id = ?
        """, (movement_id,))
    movement_data = cursor.fetchone()
    if isinstance(movement_data, sqlite3.Row):
        movement_data = dict(movement_data)
    return movement_data

def get_wheel_movement(conn, movement_id):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            SELECT wm.*, w.brand, w.model, w.diameter, u.username
            FROM wheel_movements wm
            JOIN wheels w ON wm.wheel_id = w.id
            LEFT JOIN users u ON wm.user_id = u.id
            WHERE wm.id = %s
        """, (movement_id,))
    else:
        cursor.execute("""
            SELECT wm.*, w.brand, w.model, w.diameter, u.username
            FROM wheel_movements wm
            JOIN wheels w ON wm.wheel_id = w.id
            LEFT JOIN users u ON wm.user_id = u.id
            WHERE wm.id = ?
        """, (movement_id,))
    movement_data = cursor.fetchone()
    if isinstance(movement_data, sqlite3.Row):
        movement_data = dict(movement_data)
    return movement_data

def update_wheel_movement(conn, movement_id, new_notes, new_image_filename=None):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE wheel_movements
            SET notes = %s, image_filename = %s
            WHERE id = %s
        """, (new_notes, new_image_filename, movement_id))
    else:
        cursor.execute("""
            UPDATE wheel_movements
            SET notes = ?, image_filename = ?
            WHERE id = ?
        """, (new_notes, new_image_filename, movement_id))
    conn.commit()

def update_tire_movement(conn, movement_id, new_notes, new_image_filename=None):
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            UPDATE tire_movements
            SET notes = %s, image_filename = %s
            WHERE id = %s
        """, (new_notes, new_image_filename, movement_id))
    else:
        cursor.execute("""
            UPDATE tire_movements
            SET notes = ?, image_filename = ?
            WHERE id = ?
        """, (new_notes, new_image_filename, movement_id))
    conn.commit()

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

def add_tire_movement(conn, tire_id, move_type, quantity_change, remaining_quantity, notes, image_filename=None, user_id=None):
    timestamp = get_bkk_time().isoformat()
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO tire_movements (tire_id, timestamp, type, quantity_change, remaining_quantity, notes, image_filename, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (tire_id, timestamp, move_type, quantity_change, remaining_quantity, notes, image_filename, user_id))
    else:
        cursor.execute("""
            INSERT INTO tire_movements (tire_id, timestamp, type, quantity_change, remaining_quantity, notes, image_filename, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (tire_id, timestamp, move_type, quantity_change, remaining_quantity, notes, image_filename, user_id))
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
    
    add_wheel_movement(conn, wheel_id, 'IN', quantity, quantity, 'เพิ่มแม็กใหม่เข้าสต็อก', None, user_id=user_id)
    
    conn.commit()
    return wheel_id
    
def update_wheel(conn, wheel_id, brand, model, diameter, pcd, width, et, color, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url):
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
                cost = %s,
                cost_online = %s,
                wholesale_price1 = %s,
                wholesale_price2 = %s,
                retail_price = %s,
                image_filename = %s
            WHERE id = %s
        """, (brand, model, diameter, pcd, width, et, color, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url, wheel_id))
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
                cost = ?,
                cost_online = ?,
                wholesale_price1 = ?,
                wholesale_price2 = ?,
                retail_price = ?,
                image_filename = ?
            WHERE id = ?
        """, (brand, model, diameter, pcd, width, et, color, cost, cost_online, wholesale_price1, wholesale_price2, retail_price, image_url, wheel_id))
    conn.commit()

def add_wheel_movement(conn, wheel_id, move_type, quantity_change, remaining_quantity, notes, image_filename=None, user_id=None):
    timestamp = get_bkk_time().isoformat()
    cursor = conn.cursor()
    if "psycopg2" in str(type(conn)):
        cursor.execute("""
            INSERT INTO wheel_movements (wheel_id, timestamp, type, quantity_change, remaining_quantity, notes, image_filename, user_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        """, (wheel_id, timestamp, move_type, quantity_change, remaining_quantity, notes, image_filename, user_id))
    else:
        cursor.execute("""
            INSERT INTO wheel_movements (wheel_id, timestamp, type, quantity_change, remaining_quantity, notes, image_filename, user_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (wheel_id, timestamp, move_type, quantity_change, remaining_quantity, notes, image_filename, user_id))
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