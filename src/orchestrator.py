import uuid
from datetime import datetime
from src.agents.receiving_agent import ReceivingAgent
from src.agents.sku_agent import SKUAgent
from src.agents.audit_agent import AuditAgent
from src.agents.decision_agent import DecisionAgent
from src.agents.floor_agent import FloorAgent
from src.agents.procurement_agent import ProcurementAgent
from src.agents.manager_agent import ManagerAgent
from src.database.sqlite import get_connection
import config

class IntakeOrchestrator:
    def __init__(self):
        self.receiving = ReceivingAgent()
        self.sku = SKUAgent()
        self.audit = AuditAgent()
        self.decision = DecisionAgent()
        self.floor = FloorAgent()
        self.procurement = ProcurementAgent()
        self.manager = ManagerAgent()

    def run_intake(self, file_path: str, supplier_name: str, file_type: str) -> dict:
        """
        Execute the 7-agent sequential workflow.
        Passes structured Pydantic schemas between agents and logs outcomes in SQLite.
        """
        # Step 1: Ingest invoice
        print("[Intake Pipeline] Step 1: Running Receiving Agent...")
        receiving_out = self.receiving.execute(file_path, supplier_name, file_type)

        # Step 2: Resolve catalog matches
        print("[Intake Pipeline] Step 2: Running SKU Intelligence Agent...")
        sku_out = self.sku.execute(receiving_out)

        # Step 3: Audit calculations (Python + Gemini reports formatting)
        print("[Intake Pipeline] Step 3: Running Audit Agent...")
        audit_out = self.audit.execute(sku_out)

        # Step 4: Decision disposition reasoning
        print("[Intake Pipeline] Step 4: Running Inventory Decision Agent...")
        decision_out = self.decision.execute(audit_out, sku_out)

        # Step 5: Stock actions layout
        print("[Intake Pipeline] Step 5: Running Floor Operations Agent...")
        floor_out = self.floor.execute(decision_out)

        # Step 6: Replenishments & disputes drafts
        print("[Intake Pipeline] Step 6: Running Procurement Agent...")
        procurement_out = self.procurement.execute(decision_out, audit_out)

        # Step 7: Complete summary PDF compile
        print("[Intake Pipeline] Step 7: Running Store Manager Agent...")
        manager_out = self.manager.execute(
            receiving_out,
            sku_out,
            audit_out,
            decision_out,
            floor_out,
            procurement_out
        )

        # Log results to SQLite database
        print("[Intake Pipeline] Recording transaction to SQLite shipments log...")
        shipment_id = f"SHIP_{uuid.uuid4().hex[:8].upper()}"
        conn = get_connection()
        cursor = conn.cursor()

        # Log shipment
        cursor.execute(
            "INSERT INTO shipments (id, supplier_name, date, status, decision_reason, total_amount, risk_score) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                shipment_id,
                supplier_name,
                datetime.now().strftime("%Y-%m-%d"),
                decision_out.disposition,
                decision_out.reasoning,
                audit_out.total_billed,
                decision_out.risk_score
            )
        )

        # Log violations details
        for v in audit_out.violations:
            actual_val = v.actual_value if isinstance(v.actual_value, (int, float)) else 0.0
            expected_val = v.expected_value if isinstance(v.expected_value, (int, float)) else 0.0
            cursor.execute(
                "INSERT INTO audit_logs (shipment_id, sku, violation_type, details, billed_price, contract_price) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    shipment_id,
                    v.sku,
                    v.violation_type,
                    v.details,
                    actual_val,
                    expected_val
                )
            )

        conn.commit()
        conn.close()

        # Write final master inventory Excel log sheet
        try:
            from src.tools.excel_tools import write_excel
            excel_path = str(config.OUTPUTS_DIR / "master_inventory.xlsx")
            inventory_data = []
            for item in decision_out.items_accepted:
                inventory_data.append({
                    "SKU": item.sku,
                    "Quantity": item.quantity,
                    "Price": item.price,
                    "Supplier": supplier_name,
                    "Date": datetime.now().strftime("%Y-%m-%d")
                })
            
            if not inventory_data:
                inventory_data.append({
                    "SKU": "None",
                    "Quantity": 0,
                    "Price": 0.0,
                    "Supplier": supplier_name,
                    "Date": datetime.now().strftime("%Y-%m-%d")
                })
            
            write_excel(inventory_data, excel_path)
        except Exception as e:
            print(f"[Warning] Failed to write master_inventory.xlsx: {str(e)}")

        print(f"[Intake Pipeline] Pipeline successfully finished for {supplier_name}. ID: {shipment_id}")
        return {
            "shipment_id": shipment_id,
            "receiving": receiving_out.dict(),
            "sku": sku_out.dict(),
            "audit": audit_out.dict(),
            "decision": decision_out.dict(),
            "floor": floor_out.dict(),
            "procurement": procurement_out.dict(),
            "manager": manager_out.dict()
        }
