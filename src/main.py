import sys
import argparse
from pathlib import Path

# Insert root folder into Python sys.path
sys.path.append(str(Path(__file__).resolve().parent.parent))

from src.orchestrator import IntakeOrchestrator
from src.database.sqlite import seed_database

def main():
    parser = argparse.ArgumentParser(description="RetailPulse Autonomous AI Inventory Intake Platform CLI")
    parser.add_argument("--file", type=str, required=True, help="Absolute path to incoming supplier invoice file")
    parser.add_argument("--supplier", type=str, required=True, help="Name of the vendor/supplier")
    parser.add_argument("--type", type=str, choices=["xlsx", "csv", "pdf"], help="Override file type (extension default)")

    args = parser.parse_args()

    file_path = Path(args.file)
    if not file_path.exists():
        print(f"Error: Specified file does not exist at: {file_path}")
        sys.exit(1)

    file_type = args.type or file_path.suffix.lstrip(".").lower()

    # Pre-seed the database if not initialized
    seed_database()

    print(f"Initializing Intake Pipeline for '{args.supplier}'...")
    orchestrator = IntakeOrchestrator()

    try:
        results = orchestrator.run_intake(
            file_path=str(file_path),
            supplier_name=args.supplier,
            file_type=file_type
        )
        print("\n==============================================")
        print("INVENTORY INTAKE TRANSACTION RUN COMPLETED")
        print("==============================================")
        print(f"Shipment Transaction ID : {results['shipment_id']}")
        print(f"Final Intake Decision   : {results['decision']['disposition']}")
        print(f"Evaluated Risk Score    : {results['decision']['risk_score']} / 10.0")
        print(f"Executive Manager PDF   : {results['manager']['pdf_path']}")
        print(f"Worker Placements PDF   : {results['floor']['pdf_path']}")
        print("==============================================")
    except Exception as e:
        print(f"\nIntake run encountered critical error: {str(e)}")
        sys.exit(1)

if __name__ == "__main__":
    main()
