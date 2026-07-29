import time
import json
from src.agents.base_agent import BaseAgent
from src.models.schemas import StandardizedInventory, AuditReport, ViolationDetail
from src.tools.audit_tools import price_checker, expiry_checker, duplicate_checker
import config

class AuditAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Audit", default_model=config.MODEL_FLASH, default_temp=0.0)

    def execute(self, inventory: StandardizedInventory) -> AuditReport:
        """
        Verify product specs against contracts and store safety rules.
        Python calculates all price differentials and expiry limits; Gemini formats the final descriptions.
        """
        start_time = time.time()
        error_msg = None
        raw_response = ""
        total_billed = 0.0

        # 1. Deterministic scans in Python
        duplicates = duplicate_checker(inventory.items)
        duplicate_skus = {item.standard_sku for item in duplicates}

        raw_facts = []

        # 2. Gather contract and expiry facts per row
        for item in inventory.items:
            total_billed += round(item.price * item.quantity, 2)

            price_fact = price_checker(inventory.supplier, item.standard_sku, item.price)
            expiry_fact = expiry_checker(item.expiry_date)

            item_facts = {
                "sku": item.standard_sku,
                "billed_price": item.price,
                "quantity": item.quantity,
                "expected_price": price_fact["expected_price"],
                "price_difference": price_fact["price_difference"],
                "is_price_violation": price_fact["has_violation"],
                "days_to_expiry": expiry_fact["days_to_expiry"],
                "is_expiry_violation": expiry_fact["has_violation"],
                "is_duplicate": item.standard_sku in duplicate_skus,
                "is_unknown": item.matched_product_id == "UNKNOWN",
                "needs_review": item.matched_product_id == "REVIEW"
            }
            raw_facts.append(item_facts)

        # 3. Format facts into user-readable detail texts using Gemini
        system_prompt = self._load_prompt()
        compiled_prompt = (
            f"{system_prompt}\n\n"
            f"Supplier Name: {inventory.supplier}\n"
            f"Invoice Calculations (Computed deterministically in Python):\n"
            f"{json.dumps(raw_facts, indent=2)}\n\n"
            f"Structure the violations and return JSON strictly matching the output schema. "
            f"Use descriptive summaries for 'details'."
        )

        try:
            raw_response = self.call_llm(compiled_prompt)
            res = json.loads(raw_response)

            violations_list = []
            if isinstance(res, list):
                violations_raw = res
            elif isinstance(res, dict):
                violations_raw = res.get("violations", [])
            else:
                violations_raw = []

            for v in violations_raw:
                if isinstance(v, dict):
                    violations_list.append(ViolationDetail(
                        sku=v.get("sku"),
                        violation_type=v.get("violation_type"),
                        details=v.get("details"),
                        expected_value=v.get("expected_value"),
                        actual_value=v.get("actual_value")
                    ))

            parsed_data = AuditReport(
                supplier=inventory.supplier,
                total_billed=round(total_billed, 2),
                violations=violations_list
            )
        except Exception as e:
            error_msg = f"Audit reporting compilation failed: {str(e)}"
            self._log_run(inventory.dict(), compiled_prompt, raw_response, None, time.time() - start_time, error_msg)
            raise e

        execution_time = time.time() - start_time
        self._log_run(
            inventory.dict(),
            compiled_prompt,
            raw_response,
            parsed_data.dict(),
            execution_time
        )
        return parsed_data
