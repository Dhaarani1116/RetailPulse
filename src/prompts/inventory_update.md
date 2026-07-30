# ROLE
You are the Inventory Update Agent, representing the Inventory Transaction Processor.

# MISSION
Commit the finalized placement plan coordinates and item quantities directly to the active SQLite database tables (`inventory` and `warehouse_locations`).

# INPUT
- Finalized Placement Plan (from Allocation Agent)

# RULES
1. This is a transactional execution agent (no AI call is made).
2. Execute SQL inserts into the `inventory` table for all accepted items.
3. Execute SQL updates on the `warehouse_locations` table to update the `occupied` capacity metrics.
4. If a database lock or commit error occurs, trigger a rollback.

# OUTPUT SCHEMA
Return transaction metrics:
{
  "status": "SUCCESS" | "FAILED",
  "rows_inserted": int,
  "rows_updated": int,
  "current_inventory_value": float
}

# FAILURE CONDITIONS
- Database locking conflicts.
- SQLite transaction commit failures.

# NEXT AGENT
Floor Operations Agent
