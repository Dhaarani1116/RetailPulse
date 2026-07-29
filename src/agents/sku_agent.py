import time
import json
from src.agents.base_agent import BaseAgent
from src.models.schemas import UnifiedShipment, StandardizedInventory, StandardizedInventoryItem
from src.tools.sku_tools import lookup_product, get_known_mapping, save_mapping, get_all_products
import config

class SKUAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="SKU", default_model=config.MODEL_FLASH, default_temp=0.2)

    def execute(self, shipment: UnifiedShipment) -> StandardizedInventory:
        """
        Reconcile incoming raw names against catalog candidate list.
        Uses SQLite supplier_mapping memory first, then catalog check, then semantic LLM resolution.
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

        # Resolve each item in shipment
        for item in shipment.items:
            raw_name = item.raw_name

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
                continue

            # 3. Call LLM for semantic naming match
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

                # Check confidence score thresholds
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
                elif 0.5 <= confidence < 0.8:
                    standardized_items.append(StandardizedInventoryItem(
                        standard_sku="NEEDS_REVIEW",
                        matched_product_id="REVIEW",
                        price=item.raw_price,
                        quantity=item.raw_quantity,
                        expiry_date=item.expiry_date
                    ))
                else:
                    standardized_items.append(StandardizedInventoryItem(
                        standard_sku="UNKNOWN_PRODUCT",
                        matched_product_id="UNKNOWN",
                        price=item.raw_price,
                        quantity=item.raw_quantity,
                        expiry_date=item.expiry_date
                    ))
            except Exception:
                # Fail-safe assignment to UNKNOWN_PRODUCT
                standardized_items.append(StandardizedInventoryItem(
                    standard_sku="UNKNOWN_PRODUCT",
                    matched_product_id="UNKNOWN",
                    price=item.raw_price,
                    quantity=item.raw_quantity,
                    expiry_date=item.expiry_date
                ))

        parsed_data = StandardizedInventory(supplier=shipment.supplier, items=standardized_items)
        execution_time = time.time() - start_time
        
        self._log_run(
            shipment.dict(),
            "Executed item matches mapping loop.",
            raw_response,
            parsed_data.dict(),
            execution_time
        )
        return parsed_data
