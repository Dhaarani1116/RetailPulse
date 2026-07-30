import time
import json
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import AgentStep, AgentStatus, LogLevel
from src.database.sqlite import get_connection
import config

class WarehouseAllocationAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Warehouse_Allocation", default_model=config.MODEL_FLASH, default_temp=0.1)

    def execute(self, accepted_items: list, warehouse_snapshot: dict, optimization_plan: dict, transaction_id: str) -> Generator[AgentStep, None, dict]:
        """
        Resolves exact coordinate storage locations matching the optimization plan against the warehouse_locations limits.
        Yields AgentStep updates for real-time tracking.
        """
        start_time = time.time()
        
        step = AgentStep(
            transaction_id=transaction_id,
            agent="Warehouse_Allocation",
            status=AgentStatus.RUNNING,
            current_activity="Querying warehouse locations schema...",
            metrics={"rack_searches": 0, "allocated": 0, "overflow": 0, "avg_search_time": 0.0},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Initiating physical slotting allocation process...")
        yield step

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            # Read locations
            cursor.execute("SELECT location_id, zone, rack, shelf, capacity, occupied, allowed_category FROM warehouse_locations")
            db_locations = cursor.fetchall()
            conn.close()
            
            # Convert db_locations to dictionary for tracking modifications
            locations = []
            for row in db_locations:
                locations.append({
                    "location_id": row[0],
                    "zone": row[1],
                    "rack": row[2],
                    "shelf": row[3],
                    "capacity": row[4],
                    "occupied": row[5],
                    "allowed_category": row[6]
                })

            total_items = len(accepted_items)
            allocations = []
            table_rows = []
            
            total_rack_searches = 0
            allocated_count = 0
            overflow_count = 0

            for i, item in enumerate(accepted_items):
                sku = item["sku"]
                qty = item["quantity"]
                price = item["price"]
                expiry = item.get("expiry_date", "")
                
                step.current_activity = f"Searching coordinates for \"{sku}\" ({qty} units)..."
                yield step

                # Determine zone based on catalog product category
                conn = get_connection()
                cursor = conn.cursor()
                cursor.execute("SELECT category FROM products WHERE sku = ?", (sku,))
                prod_row = cursor.fetchone()
                category = prod_row[0] if prod_row else "Others"
                conn.close()
                
                cat_lower = category.lower()
                is_cold = "dairy" in cat_lower or "beverage" in cat_lower
                target_zone = "Cold" if is_cold else "Dry"
                
                # Check candidate locations matching zone and category
                assigned = False
                searches_made = 0
                assigned_loc = None

                for loc in locations:
                    if loc["zone"] == target_zone and (loc["allowed_category"].lower() in cat_lower or loc["allowed_category"] == "Others"):
                        searches_made += 1
                        step.current_activity = f"Evaluating slot: {loc['location_id']} for {sku}..."
                        step.metrics = {
                            "rack_searches": total_rack_searches + searches_made,
                            "allocated": allocated_count,
                            "overflow": overflow_count,
                            "avg_search_time": round((time.time() - start_time) / (i + 1), 2)
                        }
                        yield step
                        time.sleep(0.05)
                        
                        if loc["occupied"] + qty <= loc["capacity"]:
                            loc["occupied"] += qty
                            assigned_loc = loc
                            assigned = True
                            allocated_count += 1
                            total_rack_searches += searches_made
                            step.add_log(LogLevel.SUCCESS, f"Slot Allocated: {sku} assigned to {loc['location_id']} (util: {loc['occupied']}/{loc['capacity']})")
                            break
                        else:
                            step.add_log(LogLevel.WARNING, f"Space check failed: {loc['location_id']} is FULL ({loc['occupied']}/{loc['capacity']} used)")
                            yield step

                # Fallback to general category / overflow if not assigned
                if not assigned:
                    for loc in locations:
                        if loc["zone"] == target_zone and loc["location_id"] in ("LOC_DRY_B2", "LOC_COLD_C2", "LOC_COLD_D2"):
                            searches_made += 1
                            step.current_activity = f"Checking overflow slot: {loc['location_id']} for {sku}..."
                            yield step
                            time.sleep(0.05)
                            
                            if loc["occupied"] + qty <= loc["capacity"]:
                                loc["occupied"] += qty
                                assigned_loc = loc
                                assigned = True
                                allocated_count += 1
                                total_rack_searches += searches_made
                                overflow_count += 1
                                step.add_log(LogLevel.WARNING, f"Overflow Assigned: {sku} routed to overflow slot {loc['location_id']} ({loc['occupied']}/{loc['capacity']} used)")
                                break

                if not assigned:
                    assigned_loc = next((l for l in locations if l["location_id"] == "LOC_DRY_B2"), locations[3])
                    assigned_loc["occupied"] += qty
                    overflow_count += 1
                    total_rack_searches += searches_made
                    step.add_log(LogLevel.ERROR, f"Overflow Alert: Capacity full. Force-routed {sku} to default zone overflow {assigned_loc['location_id']}")
                
                p_id_suffix = sku.split("_")[-1]
                batch_no = f"BAT-{p_id_suffix}-{expiry.replace('-', '')}" if expiry else f"BAT-{p_id_suffix}-20261231"
                
                allocations.append({
                    "sku": sku,
                    "quantity": qty,
                    "location_id": assigned_loc["location_id"],
                    "rack": assigned_loc["rack"],
                    "shelf": assigned_loc["shelf"],
                    "zone": assigned_loc["zone"],
                    "batch_number": batch_no,
                    "supplier_name": item.get("supplier_name", ""),
                    "category": category,
                    "price": price,
                    "expiry_date": expiry
                })
                
                table_rows.append({
                    "SKU": sku,
                    "Assigned Rack/Shelf": f"Rack {assigned_loc['rack']} {assigned_loc['shelf']}",
                    "Storage Zone": assigned_loc["zone"],
                    "Batch Number": batch_no
                })

                step.metrics = {
                    "rack_searches": total_rack_searches,
                    "allocated": allocated_count,
                    "overflow": overflow_count,
                    "avg_search_time": round((time.time() - start_time) / (i + 1), 2)
                }
                step.table_data = list(table_rows)
                step.progress = (i + 1) / total_items
                yield step
                time.sleep(0.1)

            step.status = AgentStatus.SUCCESS
            step.current_activity = "Warehouse allocation finished."
            step.add_log(LogLevel.SUCCESS, f"Coordinates allocation complete. Assigned slots for {total_items} item batches.")
            step.progress = 1.0
            yield step
            
            return {"allocations": allocations}
            
        except Exception as e:
            step.status = AgentStatus.FAILED
            step.current_activity = "Slotting failed."
            step.add_log(LogLevel.ERROR, f"Slotting allocation failed: {str(e)}")
            yield step
            raise e
