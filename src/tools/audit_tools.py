import sqlite3
from datetime import datetime
from typing import List, Dict, Any, Optional
from src.database.sqlite import get_connection

def parse_date(date_str: str) -> Optional[datetime]:
    """
    Clean and parse various date string formats into standard datetime objects.
    """
    if not date_str:
        return None
    # Strip any trailing times or spaces
    date_str = date_str.split(" ")[0].strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d/%m/%Y", "%Y/%m/%d", "%m-%d-%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(date_str, fmt)
        except ValueError:
            continue
    return None

def price_checker(supplier_name: str, sku: str, billed_price: float, conn=None) -> Dict[str, Any]:
    """
    Cross-reference incoming price with contract pricing.
    """
    close_conn = False
    if conn is None:
        conn = get_connection()
        close_conn = True
        
    cursor = conn.cursor()
    cursor.execute(
        "SELECT contract_price FROM contracts WHERE LOWER(supplier_name) = LOWER(?) AND sku = ?",
        (supplier_name.strip(), sku.strip())
    )
    row = cursor.fetchone()
    
    contract_price = row[0] if row else None
    
    # Fallback to general price catalog if no direct supplier contract exists
    if contract_price is None:
        cursor.execute("SELECT unit_price FROM products WHERE sku = ?", (sku.strip(),))
        row_prod = cursor.fetchone()
        contract_price = row_prod[0] if row_prod else billed_price
        
    if close_conn:
        conn.close()
        
    difference = round(billed_price - contract_price, 2)
    
    return {
        "expected_price": contract_price,
        "actual_price": billed_price,
        "price_difference": difference,
        "has_violation": difference > 0.01
    }

def expiry_checker(expiry_date_str: str, baseline_date_str: str = None) -> Dict[str, Any]:
    """
    Check if the product is near or past expiration (critical threshold: < 3 days).
    """
    if not expiry_date_str:
        return {
            "days_to_expiry": 999,
            "has_violation": False,
            "details": "No expiry date provided."
        }
        
    exp_date = parse_date(expiry_date_str)
    
    if not baseline_date_str:
        base_date = datetime.today()
    else:
        base_date = parse_date(baseline_date_str) or datetime.today()
    
    if not exp_date:
        # If date is invalid format, log as warning
        return {
            "days_to_expiry": -999,
            "has_violation": True,
            "details": f"Invalid expiry date format: {expiry_date_str}"
        }
        
    delta = (exp_date - base_date).days
    return {
        "days_to_expiry": delta,
        "has_violation": delta < 3,
        "details": f"Product expires in {delta} days on {expiry_date_str}."
    }

def duplicate_checker(items: List[Any]) -> List[Any]:
    """
    Scan the shipment item lists to check for duplicate SKU rows.
    Supports both Pydantic models (object attributes) and standard dictionaries.
    """
    seen = {}
    duplicates = []
    for item in items:
        if hasattr(item, "standard_sku"):
            sku = item.standard_sku
        elif isinstance(item, dict):
            sku = item.get("standard_sku")
        else:
            continue
            
        if not sku:
            continue
        if sku in seen:
            duplicates.append(item)
        else:
            seen[sku] = item
    return duplicates
