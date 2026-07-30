import time
import json
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import StandardizedInventory, AuditReport, ViolationDetail, AgentStep, AgentStatus, LogLevel
from src.tools.audit_tools import price_checker, expiry_checker, duplicate_checker
import config

class AuditAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Audit", default_model=config.MODEL_FLASH, default_temp=0.0)

    def execute(self, inventory: StandardizedInventory, transaction_id: str) -> Generator[AgentStep, None, AuditReport]:
        """
        Verify product specs against contracts and store safety rules.
        Yields AgentStep updates detailing audit checks for each item in real time.
        """
        start_time = time.time()
        error_msg = None
        raw_response = ""
        compiled_prompt = ""
        total_billed = 0.0

        # 1. Deterministic scans in Python
        duplicates = duplicate_checker(inventory.items)
        duplicate_skus = {item.standard_sku for item in duplicates}

        raw_facts = []
        total_items = len(inventory.items)

        step = AgentStep(
            transaction_id=transaction_id,
            agent="Audit",
            status=AgentStatus.RUNNING,
            current_activity="Initializing compliance contract scans...",
            metrics={"pass": 0, "fail": 0, "warnings": 0, "risk": 0.0},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Loading pricing contracts and expiration limits...")
        yield step

        table_rows = []
        pass_count = 0
        fail_count = 0
        warning_count = 0

        # 2. Gather contract and expiry facts per row
        for i, item in enumerate(inventory.items):
            total_billed += round(item.price * item.quantity, 2)
            step.current_activity = f"Scanning item {i+1} of {total_items}: \"{item.standard_sku}\""
            yield step

            price_fact = price_checker(inventory.supplier, item.standard_sku, item.price)
            expiry_fact = expiry_checker(item.expiry_date)
            is_dup = item.standard_sku in duplicate_skus
            is_unknown = item.matched_product_id == "UNKNOWN"
            is_review = item.matched_product_id == "REVIEW"

            item_facts = {
                "sku": item.standard_sku,
                "billed_price": item.price,
                "quantity": item.quantity,
                "expected_price": price_fact["expected_price"],
                "price_difference": price_fact["price_difference"],
                "is_price_violation": price_fact["has_violation"],
                "days_to_expiry": expiry_fact["days_to_expiry"],
                "is_expiry_violation": expiry_fact["has_violation"],
                "is_duplicate": is_dup,
                "is_unknown": is_unknown,
                "needs_review": is_review
            }
            raw_facts.append(item_facts)

            # Audit logging & metrics logic
            row_has_fail = price_fact["has_violation"] or expiry_fact["has_violation"] or is_unknown
            row_has_warn = is_dup or is_review

            if row_has_fail:
                fail_count += 1
                if price_fact["has_violation"]:
                    step.add_log(LogLevel.ERROR, f"Price Violation: {item.standard_sku} billed ${item.price:.2f} (Expected: ${price_fact['expected_price']:.2f})")
                if expiry_fact["has_violation"]:
                    step.add_log(LogLevel.ERROR, f"Expiry Violation: {item.standard_sku} expires in {expiry_fact['days_to_expiry']} days")
                if is_unknown:
                    step.add_log(LogLevel.ERROR, f"Unknown SKU: Catalog entry missing for {item.standard_sku}")
            elif row_has_warn:
                warning_count += 1
                if is_dup:
                    step.add_log(LogLevel.WARNING, f"Duplicate Entry: {item.standard_sku} duplicated in invoice")
                if is_review:
                    step.add_log(LogLevel.WARNING, f"Low Confidence Mapping: {item.standard_sku} needs review")
            else:
                pass_count += 1
                step.add_log(LogLevel.SUCCESS, f"Item compliance verified for {item.standard_sku}")

            computed_risk = round(min(10.0, ((fail_count + warning_count * 0.5) / total_items) * 10), 1)
            step.metrics = {
                "pass": pass_count,
                "fail": fail_count,
                "warnings": warning_count,
                "risk": computed_risk
            }

            table_rows.append({
                "SKU": item.standard_sku,
                "Billed Price": f"${item.price:.2f}",
                "Contract Price": f"${price_fact['expected_price']:.2f}" if price_fact['expected_price'] else "N/A",
                "Audit Status": "FAIL" if row_has_fail else ("WARN" if row_has_warn else "PASS")
            })

            step.table_data = list(table_rows)
            step.progress = (i + 1) / total_items * 0.8
            yield step
            time.sleep(0.1)

        step.current_activity = "Describing contract exceptions via LLM..."
        step.add_log(LogLevel.INFO, "Formulating compliance write-ups...")
        yield step

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
                    v_type = v.get("violation_type")
                    v_details = v.get("details")
                    v_sku = v.get("sku")
                    violations_list.append(ViolationDetail(
                        sku=v_sku,
                        violation_type=v_type,
                        details=v_details,
                        expected_value=v.get("expected_value"),
                        actual_value=v.get("actual_value")
                    ))
                    step.add_log(LogLevel.INFO, f"Violation logged: [{v_type}] SKU {v_sku}: {v_details}")

            parsed_data = AuditReport(
                supplier=inventory.supplier,
                total_billed=round(total_billed, 2),
                violations=violations_list
            )

            status_code = AgentStatus.WARNING if len(violations_list) > 0 else AgentStatus.SUCCESS
            step.status = status_code
            step.current_activity = "Compliance audit completed."
            step.add_log(LogLevel.SUCCESS, f"Invoice compliance audit finished. Identified {len(violations_list)} infractions.")
            step.progress = 1.0
            yield step
            
        except Exception as e:
            error_msg = f"Audit reporting compilation failed: {str(e)}"
            self._log_run(inventory.dict(), compiled_prompt, raw_response, None, time.time() - start_time, error_msg)
            step.status = AgentStatus.FAILED
            step.current_activity = "Compliance audit failed."
            step.add_log(LogLevel.ERROR, error_msg)
            yield step
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
