import time
import json
from typing import Generator
from src.agents.base_agent import BaseAgent
from src.models.schemas import UnifiedShipment, AgentStep, AgentStatus, LogLevel
from src.tools.excel_tools import read_excel, read_csv
from src.tools.pdf_tools import read_pdf
import config

class ReceivingAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Receiving", default_model=config.MODEL_FLASH, default_temp=0.1)

    def execute(self, file_path: str, supplier_name: str, file_type: str, transaction_id: str) -> Generator[AgentStep, None, UnifiedShipment]:
        """
        Ingest the supplier invoice document, extract its rows, and output a validated UnifiedShipment.
        Yields AgentStep events for visual control room tracking.
        """
        start_time = time.time()
        error_msg = None
        raw_response = ""
        parsed_data = None
        input_meta = {"file_path": file_path, "supplier_name": supplier_name, "file_type": file_type}

        step = AgentStep(
            transaction_id=transaction_id,
            agent="Receiving",
            status=AgentStatus.RUNNING,
            current_activity="Initializing invoice ingestion...",
            metrics={"processed": 0, "total": 0, "confidence": 0.0, "queue": 0},
            progress=0.0
        )
        step.add_log(LogLevel.INFO, f"Opening invoice document: {file_path.split('/')[-1] if '/' in file_path else file_path.split('\\')[-1]}")
        yield step

        # 1. Read files using python helpers
        try:
            if file_type.lower() in ("xlsx", "xls"):
                raw_data = read_excel(file_path)
                data_repr = json.dumps(raw_data, indent=2)
            elif file_type.lower() == "csv":
                raw_data = read_csv(file_path)
                data_repr = json.dumps(raw_data, indent=2)
            elif file_type.lower() == "pdf":
                raw_data = read_pdf(file_path)
                data_repr = raw_data
            else:
                raise ValueError(f"Unsupported file type: {file_type}")
            
            step.current_activity = "Parsing raw invoice document..."
            step.add_log(LogLevel.SUCCESS, "Deterministic file parse successful.")
            step.progress = 0.2
            yield step
        except Exception as e:
            error_msg = f"Deterministic file read failed: {str(e)}"
            self._log_run(input_meta, "", "", None, time.time() - start_time, error_msg)
            step.status = AgentStatus.FAILED
            step.current_activity = "Ingestion failed."
            step.add_log(LogLevel.ERROR, error_msg)
            yield step
            raise e

        # 2. Compile system prompt and feed in data
        system_prompt = self._load_prompt()
        compiled_prompt = (
            f"{system_prompt}\n\n"
            f"Supplier Name: {supplier_name}\n"
            f"Raw Invoiced Data:\n"
            f"{data_repr}\n\n"
            f"Return a JSON object matching the Output Schema requirements exactly."
        )

        step.current_activity = "Extracting billing entities via Gemini..."
        step.add_log(LogLevel.INFO, "Running LLM invoice extraction model...")
        step.progress = 0.3
        yield step

        # 3. Request LLM normalization
        try:
            raw_response = self.call_llm(compiled_prompt)
            parsed_json = json.loads(raw_response)
            
            if isinstance(parsed_json, list):
                parsed_json = {
                    "supplier": supplier_name,
                    "items": parsed_json
                }
            
            if isinstance(parsed_json, dict):
                if "supplier_name" in parsed_json and "supplier" not in parsed_json:
                    parsed_json["supplier"] = parsed_json["supplier_name"]
                if "supplier" not in parsed_json:
                    parsed_json["supplier"] = supplier_name
            else:
                raise ValueError("LLM response did not parse into a valid JSON object or list.")
                
            parsed_data = UnifiedShipment(**parsed_json)
            
            # Stream extraction of items one-by-one
            total_items = len(parsed_data.items)
            extracted_rows = []
            
            step.add_log(LogLevel.SUCCESS, f"Gemini parsing successful. Found {total_items} billing entries.")
            yield step
            
            for idx, item in enumerate(parsed_data.items):
                extracted_rows.append({
                    "Product Name": item.raw_name,
                    "Billed Qty": item.raw_quantity,
                    "Price Paid": f"${item.raw_price:.2f}",
                    "Expiry": item.expiry_date or "N/A"
                })
                
                step.current_activity = f"Extracting item {idx+1} of {total_items}: \"{item.raw_name}\""
                step.metrics = {
                    "processed": idx + 1,
                    "total": total_items,
                    "confidence": 0.99,
                    "queue": total_items - (idx + 1)
                }
                step.add_log(LogLevel.SUCCESS, f"Extracted product \"{item.raw_name}\" | Qty: {item.raw_quantity}")
                step.table_data = list(extracted_rows)
                step.progress = 0.3 + ((idx + 1) / total_items) * 0.7
                yield step
                time.sleep(0.1) # readable UI streaming interval

            # Mark complete
            step.status = AgentStatus.SUCCESS
            step.current_activity = "Ingestion processing finished."
            step.add_log(LogLevel.SUCCESS, f"Receiving Agent execution completed. Supplier detected: {parsed_data.supplier}")
            yield step
            
        except Exception as e:
            error_msg = f"Agent reasoning or parsing failed: {str(e)}"
            self._log_run(input_meta, compiled_prompt, raw_response, None, time.time() - start_time, error_msg)
            step.status = AgentStatus.FAILED
            step.current_activity = "Ingestion failed."
            step.add_log(LogLevel.ERROR, error_msg)
            yield step
            raise e

        execution_time = time.time() - start_time
        self._log_run(
            input_meta,
            compiled_prompt,
            raw_response,
            parsed_data.dict(),
            execution_time
        )
        return parsed_data
