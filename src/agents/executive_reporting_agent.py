import time
import json
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import ManagerSummary, AgentStep, AgentStatus, LogLevel
from src.tools.document_tools import generate_manager_pdf
from src.database.sqlite import get_connection
import config

class ExecutiveReportingAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Executive_Reporting", default_model=config.MODEL_PRO, default_temp=0.3)

    def execute(self, transaction_id: str, supplier_name: str, audit_report_violations: list) -> Generator[AgentStep, None, ManagerSummary]:
        """
        Synthesize the full execution flow, compile dashboard metrics, and export manager_summary.pdf.
        Yields AgentStep updates for real-time tracking.
        """
        start_time = time.time()
        
        step = AgentStep(
            transaction_id=transaction_id,
            agent="Executive_Reporting",
            status=AgentStatus.RUNNING,
            current_activity="Aggregating transaction database tables...",
            metrics={"supplier_score": 0.0, "valuation_total": 0.0},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Initiating operations report synthesis...")
        yield step

        try:
            # Query active SQLite status for final counts
            conn = get_connection()
            cursor = conn.cursor()
            
            # Count accepted
            cursor.execute("SELECT COUNT(*), SUM(quantity) FROM inventory WHERE transaction_id = ? AND status = 'ACTIVE'", (transaction_id,))
            accepted_stats = cursor.fetchone()
            accepted_count = accepted_stats[0] if accepted_stats else 0
            accepted_qty = accepted_stats[1] if (accepted_stats and accepted_stats[1]) else 0

            # Count rejected/held
            cursor.execute("SELECT COUNT(*) FROM audit_logs WHERE shipment_id = ?", (transaction_id,))
            violations_count = cursor.fetchone()[0]
            
            # Calculate inventory valuation
            cursor.execute(
                "SELECT SUM(i.quantity * p.unit_price) FROM inventory i JOIN products p ON i.sku = p.sku WHERE i.transaction_id = ? AND i.status = 'ACTIVE'",
                (transaction_id,)
            )
            total_value_row = cursor.fetchone()
            total_val = total_value_row[0] if (total_value_row and total_value_row[0]) else 0.0
            
            conn.close()

            step.current_activity = "Synthesizing executive summary details..."
            step.metrics = {
                "supplier_score": 0.0,
                "valuation_total": round(total_val, 2)
            }
            step.add_log(LogLevel.INFO, f"Aggregated final metrics: Accepted Qty {accepted_qty} over {accepted_count} rows. Intake Valuation: ${total_val:.2f}")
            step.progress = 0.4
            yield step
            time.sleep(0.1)

            system_prompt = self._load_prompt()
            input_summary = {
                "transaction_id": transaction_id,
                "supplier_name": supplier_name,
                "accepted_lines_count": accepted_count,
                "accepted_total_quantity": accepted_qty,
                "violations_count": violations_count,
                "violations_details": audit_report_violations,
                "total_inventory_value": total_val
            }

            compiled_prompt = (
                f"{system_prompt}\n\n"
                f"Warehouse Intake Metrics:\n"
                f"{json.dumps(input_summary, indent=2)}\n\n"
                f"Please synthesize the summary. Calculate accepted_items_count, rejected_items_count, "
                f"pending_items_count, total_value of accepted items, and a supplier_score (0.0 to 100.0). "
                f"Write a professional executive_summary paragraph summarizing violations, compliance, and recommendations. "
                f"Return JSON strictly conforming to the ManagerSummary output schema."
            )

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
            
            step.add_log(LogLevel.SUCCESS, f"Supplier compliance score computed: {parsed_data.supplier_score}/100")
            step.add_log(LogLevel.SUCCESS, f"Executive summary compiled: {parsed_data.executive_summary[:60]}...")
            
            table_rows = [
                {"Metric Indicator": "Supplier Score Card", "Value": f"{parsed_data.supplier_score:.1f} / 100.0"},
                {"Metric Indicator": "Accepted Products Count", "Value": str(parsed_data.accepted_items_count)},
                {"Metric Indicator": "Rejected Products Count", "Value": str(parsed_data.rejected_items_count)},
                {"Metric Indicator": "Total Billed Intake", "Value": f"${parsed_data.total_value:,.2f}"}
            ]

            step.status = AgentStatus.SUCCESS
            step.current_activity = "Manager executive PDF report compiled."
            step.add_log(LogLevel.SUCCESS, f"Executive summary compilation complete. Report exported: manager_summary.pdf")
            step.metrics = {
                "supplier_score": parsed_data.supplier_score,
                "valuation_total": parsed_data.total_value
            }
            step.table_data = table_rows
            step.progress = 1.0
            yield step

        except Exception as e:
            error_msg = f"Store executive synthesis failed: {str(e)}"
            self._log_run(input_summary, compiled_prompt, raw_response, None, time.time() - start_time, error_msg)
            step.status = AgentStatus.FAILED
            step.current_activity = "Executive synthesis failed."
            step.add_log(LogLevel.ERROR, error_msg)
            yield step
            raise e

        execution_time = time.time() - start_time
        self._log_run(
            input_summary,
            compiled_prompt,
            raw_response,
            parsed_data.dict() if parsed_data else None,
            execution_time
        )
        return parsed_data
