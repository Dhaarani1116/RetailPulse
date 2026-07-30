import uuid
import time
from typing import Generator
from src.agents.receiving_agent import ReceivingAgent
from src.agents.sku_agent import SKUAgent
from src.agents.audit_agent import AuditAgent
from src.agents.decision_agent import DecisionAgent
from src.agents.inventory_analysis_agent import InventoryAnalysisAgent
from src.agents.inventory_optimization_agent import InventoryOptimizationAgent
from src.agents.warehouse_allocation_agent import WarehouseAllocationAgent
from src.agents.inventory_update_agent import InventoryUpdateAgent
from src.agents.floor_agent import FloorAgent
from src.agents.procurement_agent import ProcurementAgent
from src.agents.warehouse_health_agent import WarehouseHealthAgent
from src.agents.executive_reporting_agent import ExecutiveReportingAgent
from src.agents.erp_export_agent import ERPExportAgent
from src.models.schemas import AgentStep, AgentStatus, LogLevel, MissionLogEntry
from src.database.sqlite import get_connection

class PipelineRunner:
    def __init__(self):
        self.receiving = ReceivingAgent()
        self.sku = SKUAgent()
        self.audit = AuditAgent()
        self.decision = DecisionAgent()
        self.analysis = InventoryAnalysisAgent()
        self.optimization = InventoryOptimizationAgent()
        self.allocation = WarehouseAllocationAgent()
        self.update = InventoryUpdateAgent()
        self.floor = FloorAgent()
        self.procurement = ProcurementAgent()
        self.health = WarehouseHealthAgent()
        self.executive = ExecutiveReportingAgent()
        self.erp = ERPExportAgent()

    def run_pre_approval(self, file_path: str, supplier_name: str, file_type: str, transaction_id: str) -> Generator[AgentStep, None, dict]:
        """
        Runs the pre-approval phase: Ingest, SKU Match, Audit, and Decision.
        Yields AgentStep events, returning the final decision outputs.
        """
        # 1. Receiving
        receiving_out = None
        gen1 = self.receiving.execute(file_path, supplier_name, file_type, transaction_id)
        while True:
            try:
                step = next(gen1)
                yield step
            except StopIteration as e:
                receiving_out = e.value
                break

        # 2. SKU Intelligence
        sku_out = None
        gen2 = self.sku.execute(receiving_out, transaction_id)
        while True:
            try:
                step = next(gen2)
                yield step
            except StopIteration as e:
                sku_out = e.value
                break

        # 3. Audit Checks
        audit_out = None
        gen3 = self.audit.execute(sku_out, transaction_id)
        while True:
            try:
                step = next(gen3)
                yield step
            except StopIteration as e:
                audit_out = e.value
                break

        # 4. Decision Engine
        decision_out = None
        gen4 = self.decision.execute(audit_out, sku_out, transaction_id)
        while True:
            try:
                step = next(gen4)
                yield step
            except StopIteration as e:
                decision_out = e.value
                break

        return {
            "receiving": receiving_out,
            "sku": sku_out,
            "audit": audit_out,
            "decision": decision_out
        }

    def run_post_approval(self, transaction_id: str, supplier_name: str, pre_approval_results: dict, approved: bool) -> Generator[AgentStep, None, dict]:
        """
        Runs the post-approval operations phase: Analysis, Optimization, Allocation, DB update,
        Floor assignments, Procurement, Health, Reporting, and ERP Export.
        Yields AgentStep events, returning the final transaction summary.
        """
        decision_out = pre_approval_results["decision"]
        audit_out = pre_approval_results["audit"]

        if not approved:
            # Skip all operations
            skipped_agents = ["Inventory_Analysis", "Inventory_Optimization", "Warehouse_Allocation", "Inventory_Update", "Floor", "Procurement", "Warehouse_Health", "Executive_Reporting", "ERP_Export"]
            for agent in skipped_agents:
                yield AgentStep(
                    transaction_id=transaction_id,
                    agent=agent,
                    status=AgentStatus.SKIPPED,
                    current_activity="Intake Rejected.",
                    metrics={},
                    mission_log=[MissionLogEntry(level=LogLevel.WARNING, message="Manager rejected shipment. Downstream operations skipped.")],
                    progress=1.0
                )
            return {"status": "REJECTED"}

        # Convert decision items to list of dicts for next agents
        accepted_items = []
        for item in decision_out.items_accepted:
            accepted_items.append({
                "sku": item.sku,
                "quantity": item.quantity,
                "price": item.price,
                "supplier_name": supplier_name,
                "expiry_date": next((x.expiry_date for x in pre_approval_results["sku"].items if x.standard_sku == item.sku), None)
            })

        # 5. Inventory Analysis
        analysis_out = None
        gen5 = self.analysis.execute(accepted_items, transaction_id)
        while True:
            try:
                step = next(gen5)
                yield step
            except StopIteration as e:
                analysis_out = e.value
                break

        # 6. Inventory Optimization
        optimization_out = None
        gen6 = self.optimization.execute(accepted_items, analysis_out, transaction_id)
        while True:
            try:
                step = next(gen6)
                yield step
            except StopIteration as e:
                optimization_out = e.value
                break

        # 7. Warehouse Allocation
        allocation_out = None
        gen7 = self.allocation.execute(accepted_items, analysis_out, optimization_out, transaction_id)
        while True:
            try:
                step = next(gen7)
                yield step
            except StopIteration as e:
                allocation_out = e.value
                break

        # 8. Inventory Update (SQLite Transaction)
        update_out = None
        gen8 = self.update.execute(allocation_out, transaction_id)
        while True:
            try:
                step = next(gen8)
                yield step
            except StopIteration as e:
                update_out = e.value
                break

        # 9. Floor Operations
        floor_out = None
        gen9 = self.floor.execute(transaction_id)
        while True:
            try:
                step = next(gen9)
                yield step
            except StopIteration as e:
                floor_out = e.value
                break

        # 10. Procurement Filing
        procurement_out = None
        violations_dict = [v.dict() for v in audit_out.violations]
        gen10 = self.procurement.execute(transaction_id, supplier_name, violations_dict)
        while True:
            try:
                step = next(gen10)
                yield step
            except StopIteration as e:
                procurement_out = e.value
                break

        # 11. Warehouse Health Audit
        health_out = None
        gen11 = self.health.execute(transaction_id)
        while True:
            try:
                step = next(gen11)
                yield step
            except StopIteration as e:
                health_out = e.value
                break

        # 12. Executive Summary PDF Compilation
        executive_out = None
        gen12 = self.executive.execute(transaction_id, supplier_name, violations_dict)
        while True:
            try:
                step = next(gen12)
                yield step
            except StopIteration as e:
                executive_out = e.value
                break

        # 13. ERP Export JSON File
        erp_out = None
        gen13 = self.erp.execute(transaction_id, supplier_name)
        while True:
            try:
                step = next(gen13)
                yield step
            except StopIteration as e:
                erp_out = e.value
                break

        # Generate excel workbook from SQLite state
        try:
            from src.tools.excel_tools import write_excel
            import config
            
            excel_path = str(config.OUTPUTS_DIR / "master_inventory.xlsx")
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT i.sku, i.quantity, p.unit_price, i.supplier_name, i.last_updated "
                "FROM inventory i JOIN products p ON i.sku = p.sku "
                "WHERE i.status = 'ACTIVE'"
            )
            rows = cursor.fetchall()
            conn.close()

            inventory_data = []
            for r in rows:
                inventory_data.append({
                    "SKU": r[0],
                    "Quantity": r[1],
                    "Price": r[2],
                    "Supplier": r[3],
                    "Date": r[4][:10] if r[4] else ""
                })
            write_excel(inventory_data, excel_path)
        except Exception as ex:
            print(f"[Warning] Failed to generate master_inventory.xlsx: {str(ex)}")

        return {
            "status": "APPROVED",
            "analysis": analysis_out,
            "optimization": optimization_out,
            "allocation": allocation_out,
            "update": update_out,
            "floor": floor_out.dict() if hasattr(floor_out, "dict") else floor_out,
            "procurement": procurement_out.dict() if hasattr(procurement_out, "dict") else procurement_out,
            "health": health_out,
            "executive": executive_out.dict() if hasattr(executive_out, "dict") else executive_out,
            "erp": erp_out
        }
