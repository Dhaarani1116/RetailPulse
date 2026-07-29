import time
import json
from src.agents.base_agent import BaseAgent
from src.models.schemas import (
    UnifiedShipment, StandardizedInventory, AuditReport, 
    DecisionReport, WorkerTasks, PurchaseDocuments, ManagerSummary
)
from src.tools.document_tools import generate_manager_pdf
import config

class ManagerAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Manager", default_model=config.MODEL_PRO, default_temp=0.3)

    def execute(self,
                receiving_out: UnifiedShipment,
                sku_out: StandardizedInventory,
                audit_out: AuditReport,
                decision_out: DecisionReport,
                floor_out: WorkerTasks,
                procurement_out: PurchaseDocuments) -> ManagerSummary:
        """
        Synthesize the full execution flow, compile dashboard metrics, and export manager_summary.pdf.
        """
        start_time = time.time()
        error_msg = None
        raw_response = ""
        parsed_data = None

        input_data = {
            "receiving_output": receiving_out.dict(),
            "sku_output": sku_out.dict(),
            "audit_output": audit_out.dict(),
            "decision_output": decision_out.dict(),
            "floor_output": floor_out.dict(),
            "procurement_output": procurement_out.dict()
        }

        system_prompt = self._load_prompt()
        compiled_prompt = (
            f"{system_prompt}\n\n"
            f"All Pipeline Outputs:\n"
            f"{json.dumps(input_data, indent=2)}\n\n"
            f"Please synthesize the summary. Calculate accepted_items_count, rejected_items_count, "
            f"pending_items_count, total_value of accepted items, and a supplier_score (0.0 to 100.0). "
            f"Write a professional executive_summary paragraph summarizing violations, compliance, and recommendations. "
            f"Return JSON strictly conforming to the ManagerSummary output schema."
        )

        try:
            raw_response = self.call_llm(compiled_prompt)
            res = json.loads(raw_response)

            pdf_path = str(config.OUTPUTS_DIR / "manager_summary.pdf")

            # Parse to Pydantic object
            parsed_data = ManagerSummary(
                pdf_path=pdf_path,
                accepted_items_count=res.get("accepted_items_count", 0),
                rejected_items_count=res.get("rejected_items_count", 0),
                pending_items_count=res.get("pending_items_count", 0),
                total_value=res.get("total_value", 0.0),
                supplier_score=res.get("supplier_score", 0.0),
                executive_summary=res.get("executive_summary", "")
            )

            # Write manager PDF summary document
            generate_manager_pdf(parsed_data.dict(), pdf_path)
        except Exception as e:
            error_msg = f"Store manager synthesis failed: {str(e)}"
            self._log_run(input_data, compiled_prompt, raw_response, None, time.time() - start_time, error_msg)
            raise e

        execution_time = time.time() - start_time
        self._log_run(
            input_data,
            compiled_prompt,
            raw_response,
            parsed_data.dict(),
            execution_time
        )
        return parsed_data
