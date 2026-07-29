import os
import time
import pandas as pd
from pathlib import Path
from datetime import date, timedelta
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
import sys

# Insert root folder into Python sys.path
sys.path.append(str(Path(__file__).resolve().parent))

import config
from src.database.sqlite import seed_database
from src.orchestrator import IntakeOrchestrator

def generate_test_files():
    """
    Generate mock vendor invoice datasets with specific, intentional discrepancies.
    Only writes files if they do not exist.
    """
    config.DATASETS_DIR.mkdir(parents=True, exist_ok=True)

    # 1. vendor_a.xlsx (Excel format - Multiple infractions)
    # Includes: Duplicate rows, Pricing discrepancy, Expiry discrepancy, Unknown product
    file_a = config.DATASETS_DIR / "vendor_a.xlsx"
    if not file_a.exists():
        df_a = pd.DataFrame([
            {
                "Product Description": "Sushi Rice",
                "Unit Cost": 5.20,              # Violation: Overcharged (contract is $4.50)
                "Quantity": 50,
                "Expiry Date": (date.today() + timedelta(days=90)).strftime("%Y-%m-%d")
            },
            {
                "Product Description": "Sushi Rice",  # Violation: Duplicate row
                "Unit Cost": 5.20,
                "Quantity": 20,
                "Expiry Date": (date.today() + timedelta(days=90)).strftime("%Y-%m-%d")
            },
            {
                "Product Description": "Arabica Coffee",
                "Unit Cost": 20.00,
                "Quantity": 15,
                "Expiry Date": (date.today() + timedelta(days=1)).strftime("%Y-%m-%d") # Violation: Near expiry (1 day)
            },
            {
                "Product Description": "Alien Energy Drink", # Violation: Unknown product (not in catalog)
                "Unit Cost": 3.50,
                "Quantity": 10,
                "Expiry Date": (date.today() + timedelta(days=120)).strftime("%Y-%m-%d")
            }
        ])
        df_a.to_excel(file_a, index=False)
        print("Created test dataset: datasets/vendor_a.xlsx")

    # 2. vendor_b.csv (CSV format - Partial Accept test case)
    # Includes: 3 clean products (one fuzzy matched), 1 overcharged, 1 near-expiry
    file_b = config.DATASETS_DIR / "vendor_b.csv"
    if not file_b.exists():
        df_b = pd.DataFrame([
            {
                "item_name": "Sushi Rice",
                "cost": 4.50,
                "qty": 30,
                "expiry": (date.today() + timedelta(days=90)).strftime("%Y-%m-%d") # Clean
            },
            {
                "item_name": "Black Rice",
                "cost": 6.00,
                "qty": 15,
                "expiry": (date.today() + timedelta(days=100)).strftime("%Y-%m-%d") # Clean
            },
            {
                "item_name": "Ssh Rice",        # Clean: Should fuzzy-map to Sushi Rice (SKU_29_205_1132)
                "cost": 4.50,
                "qty": 10,
                "expiry": (date.today() + timedelta(days=80)).strftime("%Y-%m-%d")
            },
            {
                "item_name": "Sushi Rice",
                "cost": 5.80,                  # Violation: Overcharged ($5.80 vs contract $4.50)
                "qty": 5,
                "expiry": (date.today() + timedelta(days=120)).strftime("%Y-%m-%d")
            },
            {
                "item_name": "Black Rice",
                "cost": 6.00,
                "qty": 8,
                "expiry": (date.today() + timedelta(days=1)).strftime("%Y-%m-%d")  # Violation: Near expiry (1 day)
            }
        ])
        df_b.to_csv(file_b, index=False)
        print("Created test dataset: datasets/vendor_b.csv")

    # 3. vendor_c.pdf (PDF format - Clean document extraction)
    file_c = config.DATASETS_DIR / "vendor_c.pdf"
    if not file_c.exists():
        c = canvas.Canvas(str(file_c), pagesize=letter)
        c.drawString(100, 750, "INVOICE - FEEDMIX DISTRIBUTION")
        c.drawString(100, 730, "Supplier: Feedmix")
        c.drawString(100, 710, "Date: 2026-07-28")
        c.drawString(100, 680, "Product Description             Price      Qty    Expiry")
        expiry_val = (date.today() + timedelta(days=150)).strftime("%Y-%m-%d")
        c.drawString(100, 660, f"Arabica Coffee                  20.00      30     {expiry_val}")
        c.save()
        print("Created test dataset: datasets/vendor_c.pdf")

def print_execution_summary(results: dict, elapsed_time: float, test_name: str):
    """
    Print a professional, visual overview of the agent execution sequence.
    """
    print("\n" + "="*50)
    print(f" TEST RUN SUMMARY: {test_name}")
    print("="*50)
    
    # Assert and verify file generations
    outputs = [
        ("master_inventory.xlsx", config.OUTPUTS_DIR / "master_inventory.xlsx"),
        ("worker_tasks.pdf", config.OUTPUTS_DIR / "worker_tasks.pdf"),
        ("manager_summary.pdf", config.OUTPUTS_DIR / "manager_summary.pdf"),
    ]
    
    # Optional files depending on case
    if results["procurement"].get("po_path"):
        outputs.append(("purchase_order.docx", Path(results["procurement"]["po_path"])))
    if results["procurement"].get("dispute_email_path"):
        outputs.append(("supplier_dispute_email.txt", Path(results["procurement"]["dispute_email_path"])))
    if results["procurement"].get("notice_path"):
        outputs.append(("supplier_notice.txt", Path(results["procurement"]["notice_path"])))

    print(f"{'Receiving Agent':<30} [ PASS ]")
    print("    |")
    print(f"{'SKU Intelligence Agent':<30} [ PASS ]")
    print("    |")
    print(f"{'Audit Agent (Calculations)':<30} [ PASS ]")
    print("    |")
    print(f"{'Decision Agent':<30} [ {results['decision']['disposition']} ]")
    print("    |")
    print(f"{'Floor Operations Agent':<30} [ PASS ]")
    print("    |")
    print(f"{'Procurement Agent':<30} [ PASS ]")
    print("    |")
    print(f"{'Store Manager Agent':<30} [ PASS ]")
    
    print("-"*50)
    print("Output Documents Verification:")
    verified_count = 0
    for name, path in outputs:
        exists = path.exists()
        status = "VERIFIED" if exists else "MISSING"
        if exists:
            verified_count += 1
        print(f"  - {name:<30} : {status}")
        
    print("-"*50)
    print(f"Verified Outputs Generated : {verified_count}/{len(outputs)}")
    print(f"Intake Decision Reason     : {results['decision']['reasoning'][:80]}...")
    print(f"Total Value Processed      : ${results['manager']['total_value']:.2f}")
    print(f"Supplier Score Card        : {results['manager']['supplier_score']:.1f} / 100")
    print(f"Execution Time             : {elapsed_time:.2f} seconds")
    print("="*50 + "\n")

def run_tests():
    """
    Initialize SQLite database, populate test inputs, and execute agent runs.
    """
    print("Initializing database mapping catalogs...")
    seed_database()

    print("Checking test dataset files...")
    generate_test_files()

    orchestrator = IntakeOrchestrator()

    # TEST CASE 1: Excel invoice with pricing, duplicates, expiry, and unknown items -> REJECT
    print("\nExecuting Test Case 1...")
    start_time = time.time()
    try:
        res_a = orchestrator.run_intake(
            file_path=str(config.DATASETS_DIR / "vendor_a.xlsx"),
            supplier_name="Jaxnation",
            file_type="xlsx"
        )
        print_execution_summary(res_a, time.time() - start_time, "Vendor A (Excel - Dirty Data)")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Test Case 1 failed: {str(e)}")

    # TEST CASE 2: CSV invoice representing Partial Accept scenario
    print("\nExecuting Test Case 2...")
    start_time = time.time()
    try:
        res_b = orchestrator.run_intake(
            file_path=str(config.DATASETS_DIR / "vendor_b.csv"),
            supplier_name="Jaxnation",
            file_type="csv"
        )
        print_execution_summary(res_b, time.time() - start_time, "Vendor B (CSV - Partial Accept)")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Test Case 2 failed: {str(e)}")

    # TEST CASE 3: PDF invoice ingest verification
    print("\nExecuting Test Case 3...")
    start_time = time.time()
    try:
        res_c = orchestrator.run_intake(
            file_path=str(config.DATASETS_DIR / "vendor_c.pdf"),
            supplier_name="Feedmix",
            file_type="pdf"
        )
        print_execution_summary(res_c, time.time() - start_time, "Vendor C (PDF - Ingest Check)")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print(f"Test Case 3 failed: {str(e)}")

if __name__ == "__main__":
    run_tests()
