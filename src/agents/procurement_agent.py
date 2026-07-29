import time
import json
import uuid
from src.agents.base_agent import BaseAgent
from src.models.schemas import DecisionReport, AuditReport, PurchaseDocuments
from src.tools.document_tools import generate_po, draft_dispute_email, generate_supplier_notice
from src.database.sqlite import get_connection
import config

class ProcurementAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Procurement", default_model=config.MODEL_PRO, default_temp=0.4)

    def execute(self, decision_report: DecisionReport, audit_report: AuditReport) -> PurchaseDocuments:
        """
        Evaluate intake decision and audit violations, generate required files, and write database PO records.
        """
        start_time = time.time()
        error_msg = None
        raw_response = ""
        parsed_data = None
        input_meta = {"decision_report": decision_report.dict(), "audit_report": audit_report.dict()}

        system_prompt = self._load_prompt()
        compiled_prompt = (
            f"{system_prompt}\n\n"
            f"Supplier Name: {decision_report.supplier}\n"
            f"Intake Disposition: {decision_report.disposition}\n"
            f"Accepted Items:\n"
            f"{json.dumps([item.dict() for item in decision_report.items_accepted], indent=2)}\n\n"
            f"Audit Violations Findings:\n"
            f"{json.dumps([v.dict() for v in audit_report.violations], indent=2)}\n\n"
            f"Rejection Reasoning:\n{decision_report.reasoning}\n\n"
            f"Decide which actions are necessary. If items were accepted, generate a PO. "
            f"If price violations exist, draft a dispute email. If items were rejected, generate a notice. "
            f"Return JSON mapping keys:\n"
            f"\"generate_po\": boolean,\n"
            f"\"generate_dispute\": boolean,\n"
            f"\"generate_notice\": boolean."
        )

        try:
            raw_response = self.call_llm(compiled_prompt)
            res = json.loads(raw_response)

            po_path = None
            dispute_path = None
            notice_path = None

            # 1. Draft PO if approved items exist
            if res.get("generate_po") and len(decision_report.items_accepted) > 0:
                po_path = str(config.OUTPUTS_DIR / "purchase_order.docx")
                generate_po([item.dict() for item in decision_report.items_accepted], po_path)

                # Save POs to the SQLite database
                conn = get_connection()
                cursor = conn.cursor()
                shipment_id = f"SHIP_{uuid.uuid4().hex[:8].upper()}"
                for item in decision_report.items_accepted:
                    po_id = f"PO_{uuid.uuid4().hex[:8].upper()}"
                    cursor.execute(
                        "INSERT INTO purchase_orders (id, shipment_id, sku, quantity_ordered, unit_price, status) VALUES (?, ?, ?, ?, ?, ?)",
                        (po_id, shipment_id, item.sku, item.quantity, item.price, "DRAFT")
                    )
                conn.commit()
                conn.close()

            # 2. Draft Dispute Email if pricing violations were reported
            if res.get("generate_dispute") and len(audit_report.violations) > 0:
                price_violations = [v.dict() for v in audit_report.violations if v.violation_type == "PRICE_VIOLATION"]
                if price_violations:
                    dispute_path = str(config.OUTPUTS_DIR / "supplier_dispute_email.txt")
                    draft_dispute_email(price_violations, dispute_path)

            # 3. Draft Rejection Notice if items were rejected
            if res.get("generate_notice") and len(decision_report.items_rejected) > 0:
                notice_path = str(config.OUTPUTS_DIR / "supplier_notice.txt")
                generate_supplier_notice(decision_report.supplier, decision_report.reasoning, notice_path)

            parsed_data = PurchaseDocuments(
                po_path=po_path,
                dispute_email_path=dispute_path,
                notice_path=notice_path
            )
        except Exception as e:
            error_msg = f"Procurement execution failed: {str(e)}"
            self._log_run(input_meta, compiled_prompt, raw_response, None, time.time() - start_time, error_msg)
            raise e

        execution_time = time.time() - start_time
        self._log_run(
            input_meta,
            compiled_prompt,
            raw_response,
            parsed_data.dict(),
            execution_time
        )
        return parsed_data
