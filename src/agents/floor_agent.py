import time
import json
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import WorkerTasks, WorkerTaskItem, AgentStep, AgentStatus, LogLevel
from src.tools.document_tools import export_worker_pdf
from src.database.sqlite import get_connection
import config

class FloorAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Floor", default_model=config.MODEL_FLASH, default_temp=0.5)

    def execute(self, transaction_id: str) -> Generator[AgentStep, None, WorkerTasks]:
        """
        Produce physical stock placement operations based on the latest database state.
        Yields AgentStep updates and exports worker instructions to outputs/worker_tasks.pdf.
        """
        start_time = time.time()
        error_msg = None
        raw_response = ""
        parsed_data = None

        step = AgentStep(
            transaction_id=transaction_id,
            agent="Floor",
            status=AgentStatus.RUNNING,
            current_activity="Scanning SQLite transaction logs...",
            metrics={"floor_tasks": 0, "high_priority": 0},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Acquiring committed stock levels from SQLite...")
        yield step

        try:
            # Query SQLite for the items accepted in this transaction
            conn = get_connection()
            cursor = conn.cursor()
            cursor.execute(
                "SELECT sku, quantity, rack, shelf, zone, expiry_date, batch_number FROM inventory WHERE transaction_id = ?",
                (transaction_id,)
            )
            rows = cursor.fetchall()
            conn.close()

            if not rows:
                step.status = AgentStatus.SKIPPED
                step.current_activity = "Operations skipped."
                step.add_log(LogLevel.WARNING, "No accepted database entries located. Downstream tasks skipped.")
                step.progress = 1.0
                yield step
                return WorkerTasks(pdf_path="", task_count=0, tasks=[])

            # Standardize records for LLM context
            db_records = []
            for r in rows:
                db_records.append({
                    "sku": r[0],
                    "quantity": r[1],
                    "rack": r[2],
                    "shelf": r[3],
                    "zone": r[4],
                    "expiry_date": r[5],
                    "batch_number": r[6]
                })

            step.current_activity = "Analyzing coordinate routing constraints..."
            step.add_log(LogLevel.INFO, f"Formulating instructions for {len(db_records)} committed lines...")
            step.progress = 0.2
            yield step

            system_prompt = self._load_prompt()
            compiled_prompt = (
                f"{system_prompt}\n\n"
                f"Transaction ID: {transaction_id}\n"
                f"Warehouse Committed Inventory Records:\n"
                f"{json.dumps(db_records, indent=2)}\n\n"
                f"Determine stock placement zones, write task instructions, and order them appropriately. "
                f"Return JSON matching the output format with a 'tasks' list."
            )

            raw_response = self.call_llm(compiled_prompt)
            res = json.loads(raw_response)

            pdf_path = str(config.OUTPUTS_DIR / "worker_tasks.pdf")
            tasks_list = []
            table_rows = []
            high_priority_count = 0
            
            raw_tasks = res.get("tasks", [])
            total_tasks = len(raw_tasks)
            step.add_log(LogLevel.INFO, f"Gemini compiler successful. Prepared {total_tasks} task dispatches.")
            yield step

            for i, t in enumerate(raw_tasks):
                sku = t.get("sku")
                action = t.get("action") or t.get("instruction") or t.get("description") or "Stock item to shelves"
                zone = t.get("zone") or "General Aisle"
                priority = "HIGH" if (i == 0 or "cold" in zone.lower()) else "NORMAL"
                
                step.current_activity = f"Routing task for: {sku} -> {zone}"
                
                if priority == "HIGH":
                    high_priority_count += 1
                    step.add_log(LogLevel.WARNING, f"Priority Dispatch: Move {sku} -> {zone} ({action})")
                else:
                    step.add_log(LogLevel.SUCCESS, f"Standard Dispatch: Move {sku} -> {zone} ({action})")

                tasks_list.append(WorkerTaskItem(
                    sku=sku,
                    action=action,
                    zone=zone
                ))
                table_rows.append({
                    "Worker Instruction": action,
                    "SKU": sku,
                    "Assigned Zone": zone,
                    "Priority": priority
                })

                step.metrics = {
                    "floor_tasks": len(tasks_list),
                    "high_priority": high_priority_count
                }
                step.table_data = list(table_rows)
                step.progress = 0.2 + ((i + 1) / total_tasks) * 0.8
                yield step
                time.sleep(0.1)

            # Write physical worker tasks PDF
            export_worker_pdf([t.dict() for t in tasks_list], pdf_path)

            parsed_data = WorkerTasks(
                pdf_path=pdf_path,
                task_count=len(tasks_list),
                tasks=tasks_list
            )

            step.status = AgentStatus.SUCCESS
            step.current_activity = "Floor worker instructions dispatched."
            step.add_log(LogLevel.SUCCESS, f"Floor task allocation compiled successfully. Saved to: {pdf_path}")
            step.progress = 1.0
            yield step

        except Exception as e:
            error_msg = f"Floor tasks generation failed: {str(e)}"
            self._log_run({"transaction_id": transaction_id}, compiled_prompt, raw_response, None, time.time() - start_time, error_msg)
            step.status = AgentStatus.FAILED
            step.current_activity = "Floor operations failed."
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
