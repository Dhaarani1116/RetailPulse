import time
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import AgentStep, AgentStatus, LogLevel
from src.database.sqlite import get_connection
import config

class InventoryUpdateAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Inventory_Update", default_model=config.MODEL_FLASH, default_temp=0.1)

    def execute(self, placement_plan: dict, transaction_id: str) -> Generator[AgentStep, None, dict]:
        """
        Commit the finalized placement plan coordinates and item quantities directly to the active SQLite database tables.
        Yields AgentStep updates for real-time tracking.
        """
        start_time = time.time()
        
        step = AgentStep(
            transaction_id=transaction_id,
            agent="Inventory_Update",
            status=AgentStatus.RUNNING,
            current_activity="Acquiring SQLite write locks...",
            metrics={"rows_inserted": 0, "rows_updated": 0, "valuation_delta": 0.0},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Initiating transactional database commit sequence...")
        yield step

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            allocs = placement_plan.get("allocations", [])
            total_items = len(allocs)
            rows_inserted = 0
            rows_updated = 0
            valuation_delta = 0.0
            
            table_rows = []
            
            for i, item in enumerate(allocs):
                sku = item["sku"]
                qty = item["quantity"]
                loc_id = item["location_id"]
                rack = item["rack"]
                shelf = item["shelf"]
                expiry = item.get("expiry_date", "")
                batch_number = item["batch_number"]
                supplier = item.get("supplier_name", "")
                zone = item["zone"]
                category = item.get("category", "")
                
                step.current_activity = f"Writing record: {sku} -> Rack {rack} {shelf}"
                yield step

                # Retrieve product unit price to track transaction value additions
                cursor.execute("SELECT unit_price FROM products WHERE sku = ?", (sku,))
                prod_row = cursor.fetchone()
                unit_price = prod_row[0] if prod_row else 0.0
                valuation_delta += round(qty * unit_price, 2)
                
                # Check if item with this batch already exists in inventory
                cursor.execute("SELECT quantity FROM inventory WHERE sku = ? AND batch_number = ?", (sku, batch_number))
                existing = cursor.fetchone()
                
                if existing:
                    new_qty = existing[0] + qty
                    cursor.execute(
                        "UPDATE inventory SET quantity = ?, last_updated = CURRENT_TIMESTAMP WHERE sku = ? AND batch_number = ?",
                        (new_qty, sku, batch_number)
                    )
                    rows_updated += 1
                    table_rows.append({
                        "SKU": sku,
                        "Update Action": "UPDATE",
                        "Previous Qty": existing[0],
                        "Committed Qty": new_qty
                    })
                    step.add_log(LogLevel.SUCCESS, f"Updated SKU {sku}: quantity increased by {qty} (new: {new_qty})")
                else:
                    cursor.execute(
                        "INSERT INTO inventory (transaction_id, sku, quantity, rack, shelf, expiry_date, batch_number, supplier_name, status, zone, category) "
                        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (transaction_id, sku, qty, rack, shelf, expiry, batch_number, supplier, "ACTIVE", zone, category)
                    )
                    rows_inserted += 1
                    table_rows.append({
                        "SKU": sku,
                        "Update Action": "INSERT",
                        "Previous Qty": 0,
                        "Committed Qty": qty
                    })
                    step.add_log(LogLevel.SUCCESS, f"Inserted SKU {sku}: new batch {batch_number} added with qty {qty}")
                
                # Increment occupied level of the destination rack location in database
                cursor.execute(
                    "UPDATE warehouse_locations SET occupied = MIN(capacity, occupied + ?) WHERE location_id = ?",
                    (qty, loc_id)
                )

                step.metrics = {
                    "rows_inserted": rows_inserted,
                    "rows_updated": rows_updated,
                    "valuation_delta": round(valuation_delta, 2)
                }
                step.table_data = list(table_rows)
                step.progress = (i + 1) / total_items
                yield step
                time.sleep(0.1)
            
            # Compute current total inventory valuation
            cursor.execute(
                "SELECT SUM(i.quantity * p.unit_price) FROM inventory i JOIN products p ON i.sku = p.sku WHERE i.status = 'ACTIVE'"
            )
            total_value_row = cursor.fetchone()
            total_value = total_value_row[0] if (total_value_row and total_value_row[0]) else 0.0
            
            conn.commit()
            conn.close()
            
            step.status = AgentStatus.SUCCESS
            step.current_activity = "SQLite database updates committed."
            step.add_log(LogLevel.SUCCESS, f"Inventory transaction commit finalized. Active warehouse stock updated. Current Value: ${total_value:,.2f}")
            step.progress = 1.0
            yield step
            
            return {
                "status": "SUCCESS",
                "rows_inserted": rows_inserted,
                "rows_updated": rows_updated,
                "current_inventory_value": total_value
            }
            
        except Exception as e:
            step.status = AgentStatus.FAILED
            step.current_activity = "Database commit failed."
            step.add_log(LogLevel.ERROR, f"SQLite commit failed: {str(e)}")
            yield step
            raise e
