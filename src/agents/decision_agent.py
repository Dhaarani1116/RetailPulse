import time
import json
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import AuditReport, StandardizedInventory, DecisionReport, AgentStep, AgentStatus, LogLevel
import config

class DecisionAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Decision", default_model=config.MODEL_PRO, default_temp=0.3)

    def execute(self, audit_report: AuditReport, inventory: StandardizedInventory, transaction_id: str) -> Generator[AgentStep, None, DecisionReport]:
        """
        Evaluate audit facts (violations, duplicates, short shelf lives) to make a business disposition decision.
        Yields AgentStep updates and holds for Manager approval state.
        """
        start_time = time.time()
        error_msg = None
        raw_response = ""
        compiled_prompt = ""
        parsed_data = None
        input_meta = {"audit_report": audit_report.dict(), "inventory": inventory.dict()}

        step = AgentStep(
            transaction_id=transaction_id,
            agent="Decision",
            status=AgentStatus.RUNNING,
            current_activity="Evaluating shipment risk profile...",
            metrics={"disposition": "PENDING", "risk_score": 0.0},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Reviewing contract compliance audit findings...")
        yield step

        system_prompt = self._load_prompt()
        compiled_prompt = (
            f"{system_prompt}\n\n"
            f"Supplier Name: {audit_report.supplier}\n"
            f"Standardized Inventory Items:\n"
            f"{json.dumps(inventory.dict()['items'], indent=2)}\n\n"
            f"Audit Violations Findings:\n"
            f"{json.dumps(audit_report.dict()['violations'], indent=2)}\n\n"
            f"Please evaluate the findings, determine Accepted and Rejected items lists, "
            f"assign a disposition (ACCEPT | REJECT | PARTIAL_ACCEPT | HUMAN_REVIEW), "
            f"calculate risk_score (0.0 to 10.0), and explain your reasoning. "
            f"Return JSON strictly conforming to the DecisionReport output schema."
        )

        try:
            raw_response = self.call_llm(compiled_prompt)
            parsed_json = json.loads(raw_response)
            parsed_data = DecisionReport(**parsed_json)

            table_rows = []
            for item in parsed_data.items_accepted:
                table_rows.append({
                    "Product SKU": item.sku,
                    "Quantity": item.quantity,
                    "Action Status": "Accept",
                    "Disposition / Justification": "Pricing and expiry criteria fully satisfied."
                })
            for item in parsed_data.items_rejected:
                table_rows.append({
                    "Product SKU": item.sku,
                    "Quantity": item.quantity,
                    "Action Status": "Reject",
                    "Disposition / Justification": item.reason
                })

            step.add_log(LogLevel.INFO, f"Risk Score evaluated: {parsed_data.risk_score}/10")
            step.add_log(LogLevel.INFO, f"Proposed intake action: {parsed_data.disposition}")
            yield step

            # Stream proposal summaries item-by-item
            for item in parsed_data.items_accepted:
                step.add_log(LogLevel.SUCCESS, f"Accept Proposal: {item.sku} (Qty {item.quantity})")
            for item in parsed_data.items_rejected:
                step.add_log(LogLevel.WARNING, f"Reject Proposal: {item.sku} (Reason: {item.reason})")

            step.status = AgentStatus.WAITING_APPROVAL
            step.current_activity = "Awaiting operations manager manual override..."
            step.metrics = {
                "disposition": parsed_data.disposition,
                "risk_score": parsed_data.risk_score
            }
            step.table_data = table_rows
            step.progress = 1.0
            step.add_log(LogLevel.WARNING, "Workflow paused. Awaiting manual manager review.")
            yield step

        except Exception as e:
            error_msg = f"Decision reasoning failed: {str(e)}"
            self._log_run(input_meta, compiled_prompt, raw_response, None, time.time() - start_time, error_msg)
            step.status = AgentStatus.FAILED
            step.current_activity = "Decision calculation failed."
            step.metrics = {"disposition": "FAILED", "risk_score": 10.0}
            step.add_log(LogLevel.ERROR, error_msg)
            yield step
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
