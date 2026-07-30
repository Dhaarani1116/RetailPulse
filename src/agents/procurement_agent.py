import time
import json
import uuid
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import PurchaseDocuments, AgentStep, AgentStatus, LogLevel
from src.tools.document_tools import generate_po, draft_dispute_email, generate_supplier_notice
from src.database.sqlite import get_connection
import config

class ProcurementAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Procurement", default_model=config.MODEL_PRO, default_temp=0.4)

    def execute(self, transaction_id: str, supplier_name: str, audit_report_violations: list) -> Generator[AgentStep, None, PurchaseDocuments]:
        """
        Evaluate intake decision and audit violations, generate required files, and write database PO records.
        Yields AgentStep updates for real-time tracking.
        """
        start_time = time.time()
        error_msg = None
        raw_response = ""
        compiled_prompt = ""
        parsed_data = None

        step = AgentStep(
            transaction_id=transaction_id,
            agent="Procurement",
            status=AgentStatus.RUNNING,
            current_activity="Scanning database reorder levels...",
            metrics={"reorder_alerts": 0, "po_status": "SKIPPED"},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Initiating safety reorder checks...")
        yield step

        try:
            # Query SQLite for accepted items in this transaction joining catalog products for category
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT i.sku, i.quantity, p.unit_price, i.category FROM inventory i JOIN products p ON i.sku = p.sku WHERE i.transaction_id = ? AND i.status = 'ACTIVE'",
                (transaction_id,)
            )
            accepted_rows = cursor.fetchall()
            conn.close()

            accepted_items = []
            for r in accepted_rows:
                accepted_items.append({
                    "sku": r[0],
                    "quantity": r[1],
                    "price": r[2],
                    "category": r[3]
                })

            reorders_detected = []
            table_rows = []
            
            # Query products database to check minimum stock levels
            total_checked = len(accepted_items)
            for idx, item in enumerate(accepted_items):
                sku = item["sku"]
                step.current_activity = f"Verifying stock levels for {sku}..."
                
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT SUM(quantity) FROM inventory WHERE sku = ? AND status = 'ACTIVE'", (sku,)
                )
                sum_row = cursor.fetchone()
                current_total = sum_row[0] if (sum_row and sum_row[0]) else 0
                conn.close()
                
                cat_lower = item["category"].lower()
                min_stock = 40
                if "grain" in cat_lower or "pulse" in cat_lower:
                    min_stock = 80
                elif "dairy" in cat_lower:
                    min_stock = 50
                elif "beverage" in cat_lower:
                    min_stock = 60
                
                is_low = current_total < min_stock
                if is_low:
                    reorders_detected.append({
                        "sku": sku,
                        "current": current_total,
                        "minimum": min_stock,
                        "purchase": min_stock - current_total
                    })
                    step.add_log(LogLevel.WARNING, f"Safety stock warning: {sku} inventory at {current_total} units (Safety Min: {min_stock})")
                else:
                    step.add_log(LogLevel.SUCCESS, f"Stock Check: {sku} inventory at {current_total} units (Safety Min: {min_stock})")

                table_rows.append({
                    "SKU": sku,
                    "Current Stock": current_total,
                    "Safety Minimum": min_stock,
                    "Reorder Status": "REORDER" if is_low else "OK"
                })

                step.metrics = {
                    "reorder_alerts": len(reorders_detected),
                    "po_status": "SKIPPED"
                }
                step.table_data = list(table_rows)
                step.progress = ((idx + 1) / total_checked) * 0.4
                yield step
                time.sleep(0.05)

            step.current_activity = "Drafting supplier resolutions..."
            step.add_log(LogLevel.INFO, "Resolving Po reorder requirements...")
            yield step

            system_prompt = self._load_prompt()
            compiled_prompt = (
                f"{system_prompt}\n\n"
                f"Supplier Name: {supplier_name}\n"
                f"Accepted Items:\n"
                f"{json.dumps(accepted_items, indent=2)}\n\n"
                f"Audit Violations Findings:\n"
                f"{json.dumps(audit_report_violations, indent=2)}\n\n"
                f"Safety Reorders Required:\n"
                f"{json.dumps(reorders_detected, indent=2)}\n\n"
                f"Decide which actions are necessary. If items were accepted, generate a PO. "
                f"If price violations exist, draft a dispute email. If items were rejected, generate a notice. "
                f"Return JSON mapping keys:\n"
                f"\"generate_po\": boolean,\n"
                f"\"generate_dispute\": boolean,\n"
                f"\"generate_notice\": boolean."
            )

            raw_response = self.call_llm(compiled_prompt)
            res = json.loads(raw_response)

            po_path = None
            dispute_path = None
            notice_path = None
            po_status_val = "SKIPPED"

            # 1. Draft PO
            if res.get("generate_po") and len(accepted_items) > 0:
                po_path = str(config.OUTPUTS_DIR / "purchase_order.docx")
                generate_po(accepted_items, po_path)
                po_status_val = "DRAFT"
                
                # Save draft POs to database linked to transaction
                conn = get_connection()
                cursor = conn.cursor()
                for item in accepted_items:
                    po_id = f"PO_{uuid.uuid4().hex[:8].upper()}"
                    cursor.execute(
                        "INSERT INTO purchase_orders (id, shipment_id, sku, quantity_ordered, unit_price, status) VALUES (?, ?, ?, ?, ?, ?)",
                        (po_id, transaction_id, item["sku"], item["quantity"], item["price"], "DRAFT")
                    )
                conn.commit()
                conn.close()
                step.add_log(LogLevel.SUCCESS, "Created replenishment Purchase Order Word document: purchase_order.docx")

            # 2. Draft Dispute Email if pricing violations were reported
            price_violations = [v for v in audit_report_violations if v.get("violation_type") == "PRICE_VIOLATION"]
            if res.get("generate_dispute") and len(price_violations) > 0:
                dispute_path = str(config.OUTPUTS_DIR / "supplier_dispute_email.txt")
                draft_dispute_email(price_violations, dispute_path)
                step.add_log(LogLevel.WARNING, f"Disputed Billed Charges: Drafted dispute email for {len(price_violations)} contract infractions: supplier_dispute_email.txt")

            # 3. Draft Rejection Notice if items were rejected
            rejections = [v for v in audit_report_violations if v.get("violation_type") in ("EXPIRY_VIOLATION", "UNKNOWN_PRODUCT")]
            if res.get("generate_notice") and len(rejections) > 0:
                notice_path = str(config.OUTPUTS_DIR / "supplier_notice.txt")
                rejection_reason = "Expired batches or unmapped catalog items detected in audit."
                generate_supplier_notice(supplier_name, rejection_reason, notice_path)
                step.add_log(LogLevel.ERROR, f"Shipment Items Rejected: Drafted formal supplier notice: supplier_notice.txt")

            parsed_data = PurchaseDocuments(
                po_path=po_path,
                dispute_email_path=dispute_path,
                notice_path=notice_path
            )

            status_code = AgentStatus.WARNING if len(reorders_detected) > 0 else AgentStatus.SUCCESS
            step.status = status_code
            step.current_activity = "Procurement filing completed."
            step.metrics = {
                "reorder_alerts": len(reorders_detected),
                "po_status": po_status_val
            }
            step.add_log(LogLevel.SUCCESS, "Procurement documents compiled successfully.")
            step.progress = 1.0
            yield step

        except Exception as e:
            error_msg = f"Procurement execution failed: {str(e)}"
            self._log_run({"transaction_id": transaction_id}, compiled_prompt, raw_response, None, time.time() - start_time, error_msg)
            step.status = AgentStatus.FAILED
            step.current_activity = "Procurement filing failed."
            step.add_log(LogLevel.ERROR, error_msg)
            yield step
            raise e

        execution_time = time.time() - start_time
        self._log_run(
            {"transaction_id": transaction_id},
            compiled_prompt,
            raw_response,
            parsed_data.dict() if parsed_data else None,
            execution_time
        )
        return parsed_data
