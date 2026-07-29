import sqlite3
import csv
from pathlib import Path
import sys

# Ensure project root is in path
sys.path.append(str(Path(__file__).resolve().parent.parent.parent))

import config
from src.database.schema import initialize_database

def get_connection():
    """
    Get a connection to the SQLite database.
    """
    return sqlite3.connect(config.DB_PATH)

def clean_price(price_str):
    """
    Clean formatting from raw price strings ($4.50 -> 4.50).
    """
    if not price_str:
        return 0.0
    price_str = price_str.replace("$", "").strip()
    try:
        return float(price_str)
    except ValueError:
        return 0.0

def seed_database():
    """
    Initialize schema tables and seed catalog data from CSV datasets if empty.
    """
    conn = get_connection()
    initialize_database(conn)
    cursor = conn.cursor()

    # Check if catalog data has already been seeded
    cursor.execute("SELECT COUNT(*) FROM products")
    if cursor.fetchone()[0] > 0:
        conn.close()
        return

    # 1. Seed from products.csv
    products_csv_path = config.DATASETS_DIR / "products.csv"
    if products_csv_path.exists():
        with open(products_csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                p_id = row.get("product_id")
                name = row.get("name")
                category = row.get("category")
                price = clean_price(row.get("price"))
                
                # Derive SKU
                sku = f"SKU_{int(p_id):03d}"
                
                cat_lower = (category or "").lower()
                if "grocery" in cat_lower or "food" in cat_lower:
                    aisle = "Aisle 1"
                elif "apparel" in cat_lower or "clothing" in cat_lower:
                    aisle = "Aisle 4"
                elif "electronics" in cat_lower:
                    aisle = "Aisle 3"
                else:
                    aisle = "Aisle 2"
                
                cursor.execute(
                    "INSERT OR IGNORE INTO products (id, sku, name, category, aisle, unit_price) VALUES (?, ?, ?, ?, ?, ?)",
                    (p_id, sku, name, category, aisle, price)
                )

    # 2. Seed from grocery_inventory.csv
    grocery_csv_path = config.DATASETS_DIR / "grocery_inventory.csv"
    if grocery_csv_path.exists():
        with open(grocery_csv_path, mode='r', encoding='utf-8') as f:
            reader = csv.DictReader(f)
            for row in reader:
                p_id = row.get("Product_ID")
                name = row.get("Product_Name")
                category = row.get("Catagory")  # Spelled Catagory in file
                price = clean_price(row.get("Unit_Price"))
                supplier_name = row.get("Supplier_Name")
                
                # Standardize SKU from Product_ID (e.g. 29-205-1132 -> SKU_29_205_1132)
                sku = f"SKU_{p_id.replace('-', '_')}"
                
                cat_lower = (category or "").lower()
                if "grain" in cat_lower or "pulse" in cat_lower:
                    aisle = "Aisle 1"
                elif "beverage" in cat_lower:
                    aisle = "Aisle 2"
                elif "fruit" in cat_lower or "vegetable" in cat_lower:
                    aisle = "Aisle 5"
                elif "dairy" in cat_lower:
                    aisle = "Aisle 6"
                else:
                    aisle = "Aisle 3"

                cursor.execute(
                    "INSERT OR IGNORE INTO products (id, sku, name, category, aisle, unit_price) VALUES (?, ?, ?, ?, ?, ?)",
                    (p_id, sku, name, category, aisle, price)
                )

                # Seed supplier contract price (standard price is the database baseline)
                cursor.execute(
                    "INSERT OR IGNORE INTO contracts (supplier_name, sku, contract_price, effective_date) VALUES (?, ?, ?, ?)",
                    (supplier_name, sku, price, "2026-01-01")
                )

    conn.commit()
    conn.close()

if __name__ == "__main__":
    seed_database()
    print("Database seeding completed.")
