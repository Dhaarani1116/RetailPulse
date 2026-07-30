import time
import json
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import AgentStep, AgentStatus, LogLevel
import config

class InventoryOptimizationAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Inventory_Optimization", default_model=config.MODEL_FLASH, default_temp=0.1)

    def execute(self, accepted_items: list, warehouse_snapshot: dict, transaction_id: str) -> Generator[AgentStep, None, dict]:
        """
        Determines stock strategy using explicit, predefined prioritizations.
        Yields AgentStep updates for real-time tracking.
        """
        start_time = time.time()
        
        step = AgentStep(
            transaction_id=transaction_id,
            agent="Inventory_Optimization",
            status=AgentStatus.RUNNING,
            current_activity="Formulating storage rotation strategies...",
            metrics={"fefo_rotations": 0, "discount_warnings": 0},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Analyzing shelf-life expiries and stock rotation rules...")
        yield step

        system_prompt = self._load_prompt()
        compiled_prompt = (
            f"{system_prompt}\n\n"
            f"Incoming Accepted Shipment Items:\n"
            f"{json.dumps(accepted_items, indent=2)}\n\n"
            f"Current Warehouse Snapshot:\n"
            f"{json.dumps(warehouse_snapshot, indent=2)}\n\n"
            f"Formulate the recommendations list conforming to the expected JSON output schema."
        )

        try:
            raw_response = self.call_llm(compiled_prompt)
            res = json.loads(raw_response)
            
            recs_list = res.get("recommendations", [])
            table_rows = []
            fefo_count = 0
            discount_count = 0
            
            total_recs = len(recs_list)
            step.add_log(LogLevel.INFO, f"Gemini optimizer processed. Found {total_recs} stock strategy entries.")
            yield step

            for idx, item in enumerate(recs_list):
                sku = item.get("sku")
                action = item.get("action")
                reason = item.get("reason")
                
                step.current_activity = f"Optimizing layout strategy for {sku}..."
                
                is_fefo = "fefo" in action.lower() or "rotate" in action.lower() or "merge" in action.lower()
                is_discount = "discount" in action.lower() or "markdown" in action.lower() or "alert" in action.lower()

                if is_fefo:
                    fefo_count += 1
                    step.add_log(LogLevel.SUCCESS, f"Rotation strategy for {sku} set to: {action} ({reason})")
                elif is_discount:
                    discount_count += 1
                    step.add_log(LogLevel.WARNING, f"Discount warning for {sku} set to: {action} ({reason})")
                else:
                    step.add_log(LogLevel.INFO, f"Product {sku} optimization rule: {action} ({reason})")

                table_rows.append({
                    "SKU": sku,
                    "Strategy Action": action,
                    "Markdown Recommendation": reason
                })

                step.metrics = {
                    "fefo_rotations": fefo_count,
                    "discount_warnings": discount_count
                }
                step.table_data = list(table_rows)
                step.progress = (idx + 1) / total_recs
                yield step
                time.sleep(0.1)

            step.status = AgentStatus.SUCCESS
            step.current_activity = "Stock rotation optimization completed."
            step.add_log(LogLevel.SUCCESS, f"Stock optimization complete. Generated {total_recs} strategic recommendations.")
            step.progress = 1.0
            yield step
            return res
            
        except Exception as e:
            step.status = AgentStatus.FAILED
            step.current_activity = "Optimization failed."
            step.add_log(LogLevel.ERROR, f"Optimization error: {str(e)}")
            yield step
            raise e
