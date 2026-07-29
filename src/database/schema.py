# SQLite Schema DDL statements for RetailPulse database tables

CREATE_PRODUCTS_TABLE = """
CREATE TABLE IF NOT EXISTS products (
    id TEXT PRIMARY KEY,
    sku TEXT UNIQUE,
    name TEXT,
    category TEXT,
    aisle TEXT,
    unit_price REAL
);
"""

CREATE_SUPPLIER_MAPPING_TABLE = """
CREATE TABLE IF NOT EXISTS supplier_mapping (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_name TEXT,
    raw_name TEXT,
    matched_sku TEXT,
    confidence_score REAL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
"""

CREATE_CONTRACTS_TABLE = """
CREATE TABLE IF NOT EXISTS contracts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    supplier_name TEXT,
    sku TEXT,
    contract_price REAL,
    effective_date TEXT
);
"""

CREATE_SHIPMENTS_TABLE = """
CREATE TABLE IF NOT EXISTS shipments (
    id TEXT PRIMARY KEY,
    supplier_name TEXT,
    date TEXT,
    status TEXT, -- ACCEPTED | REJECTED | PARTIAL | REVIEW
    decision_reason TEXT,
    total_amount REAL,
    risk_score REAL
);
"""

CREATE_AUDIT_LOGS_TABLE = """
CREATE TABLE IF NOT EXISTS audit_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    shipment_id TEXT,
    sku TEXT,
    violation_type TEXT,
    details TEXT,
    billed_price REAL,
    contract_price REAL
);
"""

CREATE_PURCHASE_ORDERS_TABLE = """
CREATE TABLE IF NOT EXISTS purchase_orders (
    id TEXT PRIMARY KEY,
    shipment_id TEXT,
    sku TEXT,
    quantity_ordered INTEGER,
    unit_price REAL,
    status TEXT
);
"""

def initialize_database(conn):
    """
    Initialize all database tables inside the current SQLite connection.
    """
    cursor = conn.cursor()
    cursor.execute(CREATE_PRODUCTS_TABLE)
    cursor.execute(CREATE_SUPPLIER_MAPPING_TABLE)
    cursor.execute(CREATE_CONTRACTS_TABLE)
    cursor.execute(CREATE_SHIPMENTS_TABLE)
    cursor.execute(CREATE_AUDIT_LOGS_TABLE)
    cursor.execute(CREATE_PURCHASE_ORDERS_TABLE)
    conn.commit()
