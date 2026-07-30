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

def standardize_date(date_str):
    """
    Standardize M/D/YYYY date string into YYYY-MM-DD.
    """
    if not date_str:
        return ""
    parts = date_str.split("/")
    if len(parts) == 3:
        try:
            m = int(parts[0])
            d = int(parts[1])
            y = int(parts[2])
            return f"{y:04d}-{m:02d}-{d:02d}"
        except ValueError:
            return date_str
    return date_str

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
        # Even if products are seeded, make sure warehouse tables are seeded
        pass
    else:
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

    # 3. Seed warehouse locations
    cursor.execute("SELECT COUNT(*) FROM warehouse_locations")
    if cursor.fetchone()[0] == 0:
        default_locations = [
            ("LOC_DRY_A1", "Dry", "A", "Shelf 1", 200, 0, "Grains & Pulses"),
            ("LOC_DRY_A2", "Dry", "A", "Shelf 2", 200, 0, "Oils & Fats"),
            ("LOC_DRY_B1", "Dry", "B", "Shelf 1", 150, 0, "Fruits & Vegetables"),
            ("LOC_DRY_B2", "Dry", "B", "Shelf 2", 150, 0, "Others"),
            ("LOC_COLD_C1", "Cold", "C", "Shelf 1", 100, 0, "Dairy"),
            ("LOC_COLD_C2", "Cold", "C", "Shelf 2", 100, 0, "Dairy"),
            ("LOC_COLD_D1", "Cold", "D", "Shelf 1", 100, 0, "Beverages"),
            ("LOC_COLD_D2", "Cold", "D", "Shelf 2", 100, 0, "Beverages")
        ]
        cursor.executemany(
            "INSERT INTO warehouse_locations (location_id, zone, rack, shelf, capacity, occupied, allowed_category) VALUES (?, ?, ?, ?, ?, ?, ?)",
            default_locations
        )

    # 4. Seed initial inventory
    cursor.execute("SELECT COUNT(*) FROM inventory")
    if cursor.fetchone()[0] == 0:
        grocery_csv_path = config.DATASETS_DIR / "grocery_inventory.csv"
        if grocery_csv_path.exists():
            with open(grocery_csv_path, mode='r', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                location_occupancy = {}
                for row in reader:
                    p_id = row.get("Product_ID")
                    category = row.get("Catagory")
                    supplier_name = row.get("Supplier_Name")
                    stock_qty = int(row.get("Stock_Quantity", 0))
                    expiry_raw = row.get("Expiration_Date")
                    date_received_raw = row.get("Date_Received")
                    
                    sku = f"SKU_{p_id.replace('-', '_')}"
                    expiry_date = standardize_date(expiry_raw)
                    
                    # Determine rack and shelf zone
                    cat_lower = (category or "").lower()
                    if "grain" in cat_lower or "pulse" in cat_lower:
                        loc_id = "LOC_DRY_A1"
                    elif "oil" in cat_lower or "fat" in cat_lower:
                        loc_id = "LOC_DRY_A2"
                    elif "fruit" in cat_lower or "vegetable" in cat_lower:
                        loc_id = "LOC_DRY_B1"
                    elif "dairy" in cat_lower:
                        loc_id = "LOC_COLD_C1"
                    elif "beverage" in cat_lower:
                        loc_id = "LOC_COLD_D1"
                    else:
                        loc_id = "LOC_DRY_B2"
                        
                    batch_no = f"BAT-{p_id.split('-')[-1]}-{expiry_date.replace('-', '')}"
                    status = "ACTIVE"
                    
                    cursor.execute("SELECT zone FROM warehouse_locations WHERE location_id = ?", (loc_id,))
                    loc_row = cursor.fetchone()
                    zone = loc_row[0] if loc_row else "Dry"
                    
                    cursor.execute(
                        "INSERT INTO inventory (transaction_id, sku, quantity, rack, shelf, expiry_date, batch_number, supplier_name, status, zone, category) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        ("SEED-INITIAL", sku, stock_qty, loc_id.split("_")[-1][0], "Shelf " + loc_id.split("_")[-1][-1], expiry_date, batch_no, supplier_name, status, zone, category)
                    )
                    
                    location_occupancy[loc_id] = location_occupancy.get(loc_id, 0) + stock_qty
                
                # Update location occupied levels
                for loc_id, occ in location_occupancy.items():
                    cursor.execute(
                        "UPDATE warehouse_locations SET occupied = MIN(capacity, ?) WHERE location_id = ?",
                        (occ, loc_id)
                    )

    conn.commit()
    conn.close()

if __name__ == "__main__":
    seed_database()
    print("Database seeding completed.")

