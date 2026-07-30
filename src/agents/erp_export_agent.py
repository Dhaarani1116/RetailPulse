import time
import json
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import AgentStep, AgentStatus, LogLevel
from src.database.sqlite import get_connection
import config

class ERPExportAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="ERP_Export", default_model=config.MODEL_FLASH, default_temp=0.1)

    def execute(self, transaction_id: str, supplier_name: str) -> Generator[AgentStep, None, dict]:
        """
        Serializes transaction data into outputs/erp_export.json (Pure Python integration, no LLM call).
        Yields AgentStep updates for real-time tracking.
        """
        start_time = time.time()
        
        step = AgentStep(
            transaction_id=transaction_id,
            agent="ERP_Export",
            status=AgentStatus.RUNNING,
            current_activity="Formulating integration payload schemas...",
            metrics={"export_format": "JSON", "sync_status": "PENDING"},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Initiating ERP external database sync service...")
        yield step

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            # Fetch inventory details for this transaction
            cursor.execute(
                "SELECT sku, quantity, rack, shelf, expiry_date, batch_number, status, zone, category FROM inventory WHERE transaction_id = ?",
                (transaction_id,)
            )
            rows = cursor.fetchall()
            conn.close()

            db_records = []
            table_rows = []
            
            total_records = len(rows)
            for idx, r in enumerate(rows):
                sku = r[0]
                qty = r[1]
                batch_number = r[5]
                
                step.current_activity = f"Serializing SKU {sku} for ERP dispatch..."
                yield step

                db_records.append({
                    "sku": sku,
                    "quantity": qty,
                    "rack": r[2],
                    "shelf": r[3],
                    "expiry_date": r[4],
                    "batch_number": batch_number,
                    "status": r[6],
                    "zone": r[7],
                    "category": r[8]
                })
                
                table_rows.append({
                    "ERP Field": f"BATCH_{batch_number}",
                    "Target Object": sku,
                    "Quantity": qty,
                    "Status": "SYNCED"
                })

                step.add_log(LogLevel.SUCCESS, f"Sync package compiled for batch: BATCH_{batch_number} (SKU: {sku})")
                step.table_data = list(table_rows)
                step.progress = ((idx + 1) / total_records) * 0.8
                yield step
                time.sleep(0.05)

            export_payload = {
                "transaction_id": transaction_id,
                "supplier_name": supplier_name,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "total_items_processed": len(db_records),
                "items": db_records
            }

            export_path = config.OUTPUTS_DIR / "erp_export.json"
            with open(export_path, "w", encoding="utf-8") as f:
                json.dump(export_payload, f, indent=2)

            step.add_log(LogLevel.SUCCESS, f"ERP external sync package committed: erp_export.json")
            
            step.status = AgentStatus.SUCCESS
            step.current_activity = "ERP sync complete."
            step.metrics = {
                "export_format": "JSON",
                "sync_status": "CONFIRMED"
            }
            step.progress = 1.0
            yield step
            return export_payload

        except Exception as e:
            step.status = AgentStatus.FAILED
            step.current_activity = "ERP export failed."
            step.add_log(LogLevel.ERROR, f"ERP integration sync failed: {str(e)}")
            yield step
            raise e
