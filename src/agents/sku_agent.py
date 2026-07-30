import time
import json
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import UnifiedShipment, StandardizedInventory, StandardizedInventoryItem, AgentStep, AgentStatus, LogLevel
from src.tools.sku_tools import lookup_product, get_known_mapping, save_mapping, get_all_products
import config

class SKUAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="SKU", default_model=config.MODEL_FLASH, default_temp=0.2)

    def execute(self, shipment: UnifiedShipment, transaction_id: str) -> Generator[AgentStep, None, StandardizedInventory]:
        """
        Reconcile incoming raw names against catalog candidate list.
        Yields AgentStep status updates per item matched.
        """
        start_time = time.time()
        standardized_items = []
        raw_response = ""

        # Fetch standard products once
        catalog_products = get_all_products()
        candidates_repr = json.dumps([
            {"sku": p["sku"], "name": p["name"], "category": p["category"]} 
            for p in catalog_products
        ], indent=2)

        system_prompt = self._load_prompt()
        total_items = len(shipment.items)

        step = AgentStep(
            transaction_id=transaction_id,
            agent="SKU",
            status=AgentStatus.RUNNING,
            current_activity="Initializing catalog mapping memory...",
            metrics={"matched": 0, "review": 0, "unknown": 0, "avg_confidence": 0.0},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Fetching master inventory catalog...")
        yield step

        table_rows = []
        matched_count = 0
        review_count = 0
        unknown_count = 0
        total_confidence_sum = 0.0

        # Resolve each item in shipment
        for i, item in enumerate(shipment.items):
            raw_name = item.raw_name
            step.current_activity = f"Fuzzy matching name: \"{raw_name}\""
            step.progress = i / total_items
            yield step

            # 1. Query mapping memory (stateless mapping memory check)
            known_sku = get_known_mapping(shipment.supplier, raw_name)
            if known_sku:
                prod = next((p for p in catalog_products if p["sku"] == known_sku), None)
                if prod:
                    standardized_items.append(StandardizedInventoryItem(
                        standard_sku=prod["sku"],
                        matched_product_id=prod["id"],
                        price=item.raw_price,
                        quantity=item.raw_quantity,
                        expiry_date=item.expiry_date
                    ))
                    table_rows.append({
                        "Raw Description": raw_name,
                        "Matched SKU": prod["sku"],
                        "Product Name": prod["name"],
                        "Confidence %": "100.0% (Cache Hit)"
                    })
                    matched_count += 1
                    total_confidence_sum += 1.0
                    
                    step.add_log(LogLevel.SUCCESS, f"Cache Hit: matched \"{raw_name}\" -> {prod['sku']}")
                    step.metrics = {
                        "matched": matched_count,
                        "review": review_count,
                        "unknown": unknown_count,
                        "avg_confidence": round((total_confidence_sum / (i + 1)) * 100, 1)
                    }
                    step.table_data = list(table_rows)
                    step.progress = (i + 1) / total_items
                    yield step
                    time.sleep(0.1)
                    continue

            # 2. Check catalog exact matches
            exact_match = lookup_product(raw_name)
            if exact_match:
                standardized_items.append(StandardizedInventoryItem(
                    standard_sku=exact_match["sku"],
                    matched_product_id=exact_match["id"],
                    price=item.raw_price,
                    quantity=item.raw_quantity,
                    expiry_date=item.expiry_date
                ))
                save_mapping(shipment.supplier, raw_name, exact_match["sku"], 1.0)
                table_rows.append({
                    "Raw Description": raw_name,
                    "Matched SKU": exact_match["sku"],
                    "Product Name": exact_match["name"],
                    "Confidence %": "100.0% (Exact)"
                })
                matched_count += 1
                total_confidence_sum += 1.0
                
                step.add_log(LogLevel.SUCCESS, f"Catalog Match: matched \"{raw_name}\" -> {exact_match['sku']}")
                step.metrics = {
                    "matched": matched_count,
                    "review": review_count,
                    "unknown": unknown_count,
                    "avg_confidence": round((total_confidence_sum / (i + 1)) * 100, 1)
                }
                step.table_data = list(table_rows)
                step.progress = (i + 1) / total_items
                yield step
                time.sleep(0.1)
                continue

            # 3. Call LLM for semantic naming match
            step.add_log(LogLevel.INFO, f"Searching candidates catalog for \"{raw_name}\"...")
            yield step

            compiled_prompt = (
                f"{system_prompt}\n\n"
                f"Raw Supplier Item Name: \"{raw_name}\"\n"
                f"Store Catalog Candidates:\n{candidates_repr}\n\n"
                f"Provide standard matched SKU from the candidates list. Return JSON with keys:\n"
                f"\"matched_sku\" (string) and \"confidence_score\" (float)."
            )

            try:
                raw_response = self.call_llm(compiled_prompt)
                res = json.loads(raw_response)
                matched_sku = res.get("matched_sku")
                confidence = res.get("confidence_score", 0.0)

                prod = next((p for p in catalog_products if p["sku"] == matched_sku), None)
                
                if confidence >= 0.8 and prod:
                    standardized_items.append(StandardizedInventoryItem(
                        standard_sku=prod["sku"],
                        matched_product_id=prod["id"],
                        price=item.raw_price,
                        quantity=item.raw_quantity,
                        expiry_date=item.expiry_date
                    ))
                    save_mapping(shipment.supplier, raw_name, prod["sku"], confidence)
                    table_rows.append({
                        "Raw Description": raw_name,
                        "Matched SKU": prod["sku"],
                        "Product Name": prod["name"],
                        "Confidence %": f"{confidence * 100:.1f}% (Gemini)"
                    })
                    matched_count += 1
                    total_confidence_sum += confidence
                    step.add_log(LogLevel.SUCCESS, f"Gemini Match: matched \"{raw_name}\" -> {prod['sku']} ({confidence*100:.1f}%)")
                    
                elif 0.5 <= confidence < 0.8:
                    standardized_items.append(StandardizedInventoryItem(
                        standard_sku="NEEDS_REVIEW",
                        matched_product_id="REVIEW",
                        price=item.raw_price,
                        quantity=item.raw_quantity,
                        expiry_date=item.expiry_date
                    ))
                    table_rows.append({
                        "Raw Description": raw_name,
                        "Matched SKU": "NEEDS_REVIEW",
                        "Product Name": f"Potential Match: {prod['name'] if prod else 'None'}",
                        "Confidence %": f"{confidence * 100:.1f}% (Low)"
                    })
                    review_count += 1
                    total_confidence_sum += confidence
                    step.add_log(LogLevel.WARNING, f"Low Confidence: mapped \"{raw_name}\" -> NEEDS_REVIEW ({confidence*100:.1f}%)")
                    
                else:
                    standardized_items.append(StandardizedInventoryItem(
                        standard_sku="UNKNOWN_PRODUCT",
                        matched_product_id="UNKNOWN",
                        price=item.raw_price,
                        quantity=item.raw_quantity,
                        expiry_date=item.expiry_date
                    ))
                    table_rows.append({
                        "Raw Description": raw_name,
                        "Matched SKU": "UNKNOWN_PRODUCT",
                        "Product Name": "Unknown Item - Rejected from import",
                        "Confidence %": f"{confidence * 100:.1f}% (Unmapped)"
                    })
                    unknown_count += 1
                    total_confidence_sum += confidence
                    step.add_log(LogLevel.ERROR, f"Fuzzy Match failed for \"{raw_name}\" (confidence {confidence*100:.1f}%)")
                    
            except Exception as e:
                standardized_items.append(StandardizedInventoryItem(
                    standard_sku="UNKNOWN_PRODUCT",
                    matched_product_id="UNKNOWN",
                    price=item.raw_price,
                    quantity=item.raw_quantity,
                    expiry_date=item.expiry_date
                ))
                table_rows.append({
                    "Raw Description": raw_name,
                    "Matched SKU": "UNKNOWN_PRODUCT",
                    "Product Name": "Parsing Error Recovery",
                    "Confidence %": "0.0% (Failed)"
                })
                unknown_count += 1
                step.add_log(LogLevel.ERROR, f"Match Error for \"{raw_name}\": {str(e)}")

            step.metrics = {
                "matched": matched_count,
                "review": review_count,
                "unknown": unknown_count,
                "avg_confidence": round((total_confidence_sum / (i + 1)) * 100, 1)
            }
            step.table_data = list(table_rows)
            step.progress = (i + 1) / total_items
            yield step
            time.sleep(0.1)

        parsed_data = StandardizedInventory(supplier=shipment.supplier, items=standardized_items)
        execution_time = time.time() - start_time
        
        step.status = AgentStatus.SUCCESS
        step.current_activity = "SKU reconciliation finished."
        step.add_log(LogLevel.SUCCESS, "SKU Standardizer execution completed.")
        yield step

        self._log_run(
            shipment.dict(),
            "Executed item matches mapping loop.",
            raw_response,
            parsed_data.dict(),
            execution_time
        )
        return parsed_data
