import time
import json
from src.agents.base_agent import BaseAgent
from src.models.schemas import DecisionReport, WorkerTasks, WorkerTaskItem
from src.tools.document_tools import export_worker_pdf
import config

class FloorAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Floor", default_model=config.MODEL_FLASH, default_temp=0.5)

    def execute(self, decision_report: DecisionReport) -> WorkerTasks:
        """
        Produce physical stock placement operations based on the decision output.
        Calls export_worker_pdf to save worker instructions to output.
        """
        start_time = time.time()
        error_msg = None
        raw_response = ""
        parsed_data = None

        system_prompt = self._load_prompt()
        compiled_prompt = (
            f"{system_prompt}\n\n"
            f"Decision Disposition: {decision_report.disposition}\n"
            f"Accepted Items:\n"
            f"{json.dumps([item.dict() for item in decision_report.items_accepted], indent=2)}\n\n"
            f"Determine stock placement zones, write task instructions, and order them appropriately. "
            f"Return JSON matching the output format with a 'tasks' list."
        )

        try:
            raw_response = self.call_llm(compiled_prompt)
            res = json.loads(raw_response)

            pdf_path = str(config.OUTPUTS_DIR / "worker_tasks.pdf")

            tasks_list = []
            for t in res.get("tasks", []):
                sku = t.get("sku")
                action = t.get("action") or t.get("instruction") or t.get("description") or "Stock item to shelves"
                zone = t.get("zone") or "General Aisle"
                tasks_list.append(WorkerTaskItem(
                    sku=sku,
                    action=action,
                    zone=zone
                ))

            # Write physical worker tasks PDF
            export_worker_pdf([t.dict() for t in tasks_list], pdf_path)

            parsed_data = WorkerTasks(
                pdf_path=pdf_path,
                task_count=len(tasks_list),
                tasks=tasks_list
            )
        except Exception as e:
            error_msg = f"Floor tasks generation failed: {str(e)}"
            self._log_run(decision_report.dict(), compiled_prompt, raw_response, None, time.time() - start_time, error_msg)
            raise e

        execution_time = time.time() - start_time
        self._log_run(
            decision_report.dict(),
            compiled_prompt,
            raw_response,
            parsed_data.dict(),
            execution_time
        )
        return parsed_data
