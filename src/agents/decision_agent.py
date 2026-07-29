import time
import json
from src.agents.base_agent import BaseAgent
from src.models.schemas import AuditReport, StandardizedInventory, DecisionReport
import config

class DecisionAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Decision", default_model=config.MODEL_PRO, default_temp=0.3)

    def execute(self, audit_report: AuditReport, inventory: StandardizedInventory) -> DecisionReport:
        """
        Evaluate audit facts (violations, duplicates, short shelf lives) to make a business disposition decision.
        Uses Gemini 2.5 Pro to evaluate risks and generate logic.
        """
        start_time = time.time()
        error_msg = None
        raw_response = ""
        parsed_data = None
        input_meta = {"audit_report": audit_report.dict(), "inventory": inventory.dict()}

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
        except Exception as e:
            error_msg = f"Decision reasoning failed: {str(e)}"
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
