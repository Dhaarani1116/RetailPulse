import sqlite3
from typing import List, Dict, Any, Optional
from src.database.sqlite import get_connection

def lookup_product(raw_name: str, conn=None) -> Optional[Dict[str, Any]]:
    """
    Search the standard catalog for a product matching raw_name exactly (case-insensitive).
    """
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
    
    cursor = conn.cursor()
    cursor.execute(
        "SELECT id, sku, name, category, aisle, unit_price FROM products WHERE LOWER(name) = LOWER(?)",
        (raw_name.strip(),)
    )
    row = cursor.fetchone()
    
    if close_conn:
        conn.close()
        
    if row:
        return {
            "id": row[0],
            "sku": row[1],
            "name": row[2],
            "category": row[3],
            "aisle": row[4],
            "unit_price": row[5]
        }
    return None

def get_known_mapping(supplier_name: str, raw_name: str, conn=None) -> Optional[str]:
    """
    Query the SKU Agent's mapping memory for a previously matched standard SKU.
    """
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
        
    cursor = conn.cursor()
    cursor.execute(
        "SELECT matched_sku FROM supplier_mapping WHERE LOWER(supplier_name) = LOWER(?) AND LOWER(raw_name) = LOWER(?) ORDER BY id DESC",
        (supplier_name.strip(), raw_name.strip())
    )
    row = cursor.fetchone()
    
    if close_conn:
        conn.close()
        
    return row[0] if row else None

def save_mapping(supplier_name: str, raw_name: str, standard_sku: str, confidence_score: float, conn=None) -> None:
    """
    Write a newly learned supplier-to-store product mapping to the SQLite database.
    """
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
        
    cursor = conn.cursor()
    cursor.execute(
        "INSERT INTO supplier_mapping (supplier_name, raw_name, matched_sku, confidence_score) VALUES (?, ?, ?, ?)",
        (supplier_name.strip(), raw_name.strip(), standard_sku.strip(), confidence_score)
    )
    conn.commit()
    
    if close_conn:
        conn.close()

def get_all_products(conn=None) -> List[Dict[str, Any]]:
    """
    Retrieve all products in the store's master catalog.
    """
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
        
    cursor = conn.cursor()
    cursor.execute("SELECT id, sku, name, category, aisle, unit_price FROM products")
    rows = cursor.fetchall()
    
    if close_conn:
        conn.close()
        
    return [
        {
            "id": r[0],
            "sku": r[1],
            "name": r[2],
            "category": r[3],
            "aisle": r[4],
            "unit_price": r[5]
        }
        for r in rows
    ]
