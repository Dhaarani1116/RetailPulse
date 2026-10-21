import uuid
from datetime import datetime
from src.pipeline_runner import PipelineRunner
from src.database.sqlite import get_connection

class IntakeOrchestrator:
    def __init__(self):
        self.runner = PipelineRunner()

    def run_intake(self, file_path: str, supplier_name: str, file_type: str) -> dict:
        """
        Execute the sequential workforce pipeline.
        Consumes the PipelineRunner generator stream to retain backward compatibility with synchronous test runners.
        """
        transaction_id = f"RP-2026-{uuid.uuid4().hex[:6].upper()}"
        
        # 1. Pre-approval Ingestion Phase
        print(f"[Intake Pipeline] Running pre-approval phase for {transaction_id}...")
        pre_gen = self.runner.run_pre_approval(file_path, supplier_name, file_type, transaction_id)
        pre_results = None
        try:
            while True:
                step = next(pre_gen)
                print(f"  [{step.agent}] Activity: {step.current_activity} | Progress: {int(step.progress * 100)}%")
        except StopIteration as e:
            pre_results = e.value

        # Log shipment & audit logs to database before post-approval
        print("[Intake Pipeline] Logging pre-approval decision outputs in SQLite shipments table...")
        conn = get_connection()
        cursor = conn.cursor()
        cursor.execute(
            "INSERT INTO shipments (id, supplier_name, date, status, decision_reason, total_amount, risk_score) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                transaction_id,
                supplier_name,
                datetime.now().strftime("%Y-%m-%d"),
                pre_results["decision"].disposition,
                pre_results["decision"].reasoning,
                pre_results["audit"].total_billed,
                pre_results["decision"].risk_score
            )
        )
        for v in pre_results["audit"].violations:
            actual_val = v.actual_value if isinstance(v.actual_value, (int, float)) else 0.0
            expected_val = v.expected_value if isinstance(v.expected_value, (int, float)) else 0.0
            cursor.execute(
                "INSERT INTO audit_logs (shipment_id, sku, violation_type, details, billed_price, contract_price) VALUES (?, ?, ?, ?, ?, ?)",
                (transaction_id, v.sku, v.violation_type, v.details, actual_val, expected_val)
            )
        conn.commit()
        conn.close()

        # 2. Evaluate approval decision
        approved = pre_results["decision"].disposition in ("ACCEPT", "PARTIAL_ACCEPT", "HUMAN_REVIEW")
        
        # 3. Post-approval Operations Phase
        print(f"[Intake Pipeline] Running post-approval operations phase (Approved = {approved})...")
        post_gen = self.runner.run_post_approval(transaction_id, supplier_name, pre_results, approved=approved)
        post_results = None
        try:
            while True:
                step = next(post_gen)
                print(f"  [{step.agent}] Activity: {step.current_activity} | Progress: {int(step.progress * 100)}%")
        except StopIteration as e:
            post_results = e.value

        def to_dict(obj, default=None):
            if obj is None:
                return default if default is not None else {}
            if hasattr(obj, "dict"):
                return obj.dict()
            if isinstance(obj, dict):
                return obj
            return default if default is not None else {}

        # Standard return map mapping new variables to deprecated keys for backward testing compatibility
        print(f"[Intake Pipeline] Ingest run finished. Shipment ID: {transaction_id}")
        
        floor_data = to_dict(post_results.get("floor") if post_results else None, {"pdf_path": "", "task_count": 0, "tasks": []}) if approved else {"pdf_path": "", "task_count": 0, "tasks": []}
        procurement_data = to_dict(post_results.get("procurement") if post_results else None, {"po_path": None, "dispute_email_path": None, "notice_path": None}) if approved else {"po_path": None, "dispute_email_path": None, "notice_path": None}
        manager_data = to_dict(post_results.get("executive") if post_results else None, {
            "pdf_path": "",
            "accepted_items_count": 0,
            "rejected_items_count": 0,
            "pending_items_count": 0,
            "total_value": 0.0,
            "supplier_score": 0.0,
            "executive_summary": "Shipment Rejected."
        }) if approved else {
            "pdf_path": "",
            "accepted_items_count": 0,
            "rejected_items_count": 0,
            "pending_items_count": 0,
            "total_value": 0.0,
            "supplier_score": 0.0,
            "executive_summary": "Shipment Rejected."
        }

        return {
            "shipment_id": transaction_id,
            "receiving": to_dict(pre_results.get("receiving")),
            "sku": to_dict(pre_results.get("sku")),
            "audit": to_dict(pre_results.get("audit")),
            "decision": to_dict(pre_results.get("decision")),
            "floor": floor_data,
            "procurement": procurement_data,
            "manager": manager_data
        }
