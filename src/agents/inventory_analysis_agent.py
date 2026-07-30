import time
import json
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import AgentStep, AgentStatus, LogLevel
from src.database.sqlite import get_connection
import config

class InventoryAnalysisAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Inventory_Analysis", default_model=config.MODEL_FLASH, default_temp=0.1)

    def execute(self, accepted_items: list, transaction_id: str) -> Generator[AgentStep, None, dict]:
        """
        Inspect today's warehouse capacities and active stock before changes.
        Yields AgentStep updates for real-time tracking.
        """
        start_time = time.time()
        
        step = AgentStep(
            transaction_id=transaction_id,
            agent="Inventory_Analysis",
            status=AgentStatus.RUNNING,
            current_activity="Connecting to SQLite database...",
            metrics={"dry_occupancy": 0.0, "cold_occupancy": 0.0, "matched_batches": 0},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Initiating warehouse capacity audit scan...")
        yield step

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            # Read capacities
            cursor.execute("SELECT location_id, zone, rack, shelf, capacity, occupied, allowed_category FROM warehouse_locations")
            locs = cursor.fetchall()
            
            step.current_activity = "Scanning storage location structures..."
            step.add_log(LogLevel.INFO, f"Scanning {len(locs)} rack shelf structures in SQLite...")
            step.progress = 0.2
            yield step

            # Compute dry and cold occupancy percentages
            dry_cap = dry_occ = cold_cap = cold_occ = 0
            for row in locs:
                zone = row[1]
                cap = row[4]
                occ = row[5]
                if zone.lower() == "dry":
                    dry_cap += cap
                    dry_occ += occ
                elif zone.lower() == "cold":
                    cold_cap += cap
                    cold_occ += occ
            
            dry_pct = round((dry_occ / dry_cap * 100.0), 1) if dry_cap > 0 else 0.0
            cold_pct = round((cold_occ / cold_cap * 100.0), 1) if cold_cap > 0 else 0.0
            
            step.metrics = {
                "dry_occupancy": dry_pct,
                "cold_occupancy": cold_pct,
                "matched_batches": 0
            }
            step.add_log(LogLevel.SUCCESS, f"Dry Zone occupancy: {dry_pct}% capacity occupied.")
            step.add_log(LogLevel.SUCCESS, f"Cold Zone occupancy: {cold_pct}% capacity occupied.")
            step.progress = 0.4
            yield step
            time.sleep(0.1)

            # Scan matching SKU batches one-by-one to visualize database reads
            skus_to_check = [item["sku"] for item in accepted_items]
            existing_stock = []
            table_rows = []
            
            total_skus = len(skus_to_check)
            for idx, sku in enumerate(skus_to_check):
                step.current_activity = f"Retrieving stock layout for {sku}..."
                
                cursor.execute(
                    "SELECT sku, quantity, rack, shelf, expiry_date FROM inventory WHERE sku = ? AND status = 'ACTIVE'",
                    (sku,)
                )
                stock_rows = cursor.fetchall()
                
                for row in stock_rows:
                    existing_stock.append({
                        "sku": row[0],
                        "quantity": row[1],
                        "location": f"Rack {row[2]} {row[3]}",
                        "earliest_expiry": row[4]
                    })
                    table_rows.append({
                        "SKU": row[0],
                        "Location (Rack/Shelf)": f"Rack {row[2]} {row[3]}",
                        "Active Stock": row[1],
                        "Oldest Expiry": row[4]
                    })
                    
                    step.add_log(LogLevel.INFO, f"Stock Found: {row[0]} -> Rack {row[2]} Shelf {row[3]} ({row[1]} units)")
                
                step.metrics = {
                    "dry_occupancy": dry_pct,
                    "cold_occupancy": cold_pct,
                    "matched_batches": len(existing_stock)
                }
                step.table_data = list(table_rows)
                step.progress = 0.4 + ((idx + 1) / total_skus) * 0.6
                yield step
                time.sleep(0.1)
            
            conn.close()
            
            snapshot = {
                "dry_rack_occupancy_pct": dry_pct,
                "cold_rack_occupancy_pct": cold_pct,
                "existing_stock": existing_stock
            }
            
            if not table_rows:
                table_rows.append({
                    "SKU": "None Found",
                    "Location (Rack/Shelf)": "N/A",
                    "Active Stock": 0,
                    "Oldest Expiry": "N/A"
                })
                step.table_data = list(table_rows)

            step.status = AgentStatus.SUCCESS
            step.current_activity = "Warehouse snapshot compiled."
            step.add_log(LogLevel.SUCCESS, f"Inventory Analysis completed. Found {len(existing_stock)} existing SKU records.")
            step.progress = 1.0
            yield step
            return snapshot

        except Exception as e:
            step.status = AgentStatus.FAILED
            step.current_activity = "Inventory scan failed."
            step.add_log(LogLevel.ERROR, f"Database scan error: {str(e)}")
            yield step
            raise e
