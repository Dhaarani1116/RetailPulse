import time
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import AgentStep, AgentStatus, LogLevel
from src.database.sqlite import get_connection
import config

class WarehouseHealthAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Warehouse_Health", default_model=config.MODEL_FLASH, default_temp=0.1)

    def execute(self, transaction_id: str) -> Generator[AgentStep, None, dict]:
        """
        Audits the warehouse post-update to extract overall metrics (Utilization %, near-expiry alerts, reorder warnings).
        Yields AgentStep updates for real-time tracking.
        """
        start_time = time.time()
        
        step = AgentStep(
            transaction_id=transaction_id,
            agent="Warehouse_Health",
            status=AgentStatus.RUNNING,
            current_activity="Scanning database occupancy status...",
            metrics={"total_utilization": 0.0, "expired_counts": 0, "warning_flags": 0},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, "Initiating warehouse operations safety inspection...")
        yield step

        try:
            conn = get_connection()
            cursor = conn.cursor()
            
            # 1. Compute total occupancy rate
            cursor.execute("SELECT SUM(capacity), SUM(occupied) FROM warehouse_locations")
            cap_row = cursor.fetchone()
            tot_cap = cap_row[0] if (cap_row and cap_row[0]) else 1
            tot_occ = cap_row[1] if (cap_row and cap_row[1]) else 0
            util_pct = round((tot_occ / tot_cap * 100.0), 1)

            # 2. Count expired / near-expiry items
            cursor.execute(
                "SELECT COUNT(*) FROM inventory WHERE expiry_date <= DATE('now', '+7 days') AND status = 'ACTIVE'"
            )
            near_expiry_count = cursor.fetchone()[0]

            step.metrics = {
                "total_utilization": util_pct,
                "expired_counts": near_expiry_count,
                "warning_flags": 0
            }
            step.add_log(LogLevel.INFO, f"Global warehouse occupancy level calculated: {util_pct}% ({tot_occ}/{tot_cap} occupied).")
            if near_expiry_count > 0:
                step.add_log(LogLevel.WARNING, f"Found {near_expiry_count} items expiring or near expiry within 7 days.")
            else:
                step.add_log(LogLevel.SUCCESS, "Zero near-expiry inventory batches located in dry/cold racks.")
            step.progress = 0.4
            yield step
            time.sleep(0.1)

            # 3. Identify reorder alerts
            cursor.execute("SELECT sku, SUM(quantity) FROM inventory WHERE status = 'ACTIVE' GROUP BY sku")
            stock_levels = cursor.fetchall()
            
            reorder_alerts = []
            table_rows = []
            
            total_levels = len(stock_levels)
            for idx, row in enumerate(stock_levels):
                sku = row[0]
                qty = row[1]
                
                step.current_activity = f"Auditing threshold for {sku}..."
                
                # Check category from products table
                cursor.execute("SELECT category FROM products WHERE sku = ?", (sku,))
                prod_row = cursor.fetchone()
                category = prod_row[0] if prod_row else "Others"
                
                cat_lower = category.lower()
                min_stock = 40
                if "grain" in cat_lower or "pulse" in cat_lower:
                    min_stock = 80
                elif "dairy" in cat_lower:
                    min_stock = 50
                elif "beverage" in cat_lower:
                    min_stock = 60
                    
                is_low = qty < min_stock
                if is_low:
                    reorder_alerts.append({
                        "sku": sku,
                        "current_stock": qty,
                        "reorder_threshold": min_stock
                    })
                    step.add_log(LogLevel.WARNING, f"Low Stock Warn: SKU {sku} quantity below safe reorder level ({qty}/{min_stock})")
                
                table_rows.append({
                    "SKU": sku,
                    "Active Inventory Stock": qty,
                    "Aisle Safety Status": "BELOW_MIN" if is_low else "SAFE"
                })

                step.metrics = {
                    "total_utilization": util_pct,
                    "expired_counts": near_expiry_count,
                    "warning_flags": len(reorder_alerts)
                }
                step.table_data = list(table_rows)
                step.progress = 0.4 + ((idx + 1) / total_levels) * 0.6
                yield step
                time.sleep(0.05)
            
            conn.close()

            snapshot = {
                "utilization_pct": util_pct,
                "near_expiry_count": near_expiry_count,
                "reorder_alerts": reorder_alerts
            }

            if not table_rows:
                table_rows.append({
                    "SKU": "All Stocks OK",
                    "Active Inventory Stock": 0,
                    "Aisle Safety Status": "SAFE"
                })
                step.table_data = list(table_rows)

            step.status = AgentStatus.SUCCESS
            step.current_activity = "Warehouse safety health audit completed."
            step.add_log(LogLevel.SUCCESS, f"Audit complete. Occupancy utilization: {util_pct}%. Low stock warnings: {len(reorder_alerts)}")
            step.progress = 1.0
            yield step
            return snapshot

        except Exception as e:
            step.status = AgentStatus.FAILED
            step.current_activity = "Health audit failed."
            step.add_log(LogLevel.ERROR, f"Health scan failed: {str(e)}")
            yield step
            raise e
