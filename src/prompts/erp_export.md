# ROLE
You are the ERP Export Service.

# MISSION
Serialize committed transaction logs into an integration-ready JSON file for external ERP synchronization.

# INPUT
- Inventory update logs from SQLite database.

# RULES
1. This is a deterministic data serialization step (no AI model inference is needed).
2. Write transaction details directly to `outputs/erp_export.json`.
