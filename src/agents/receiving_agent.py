import time
import json
from src.agents.base_agent import BaseAgent
from src.models.schemas import UnifiedShipment
from src.tools.excel_tools import read_excel, read_csv
from src.tools.pdf_tools import read_pdf
import config

class ReceivingAgent(BaseAgent):
    def __init__(self):
        super().__init__(name="Receiving", default_model=config.MODEL_FLASH, default_temp=0.1)

    def execute(self, file_path: str, supplier_name: str, file_type: str) -> UnifiedShipment:
        """
        Ingest the supplier invoice document, extract its rows, and output a validated UnifiedShipment.
        """
        start_time = time.time()
        error_msg = None
        raw_response = ""
        parsed_data = None
        input_meta = {"file_path": file_path, "supplier_name": supplier_name, "file_type": file_type}

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
        except Exception as e:
            error_msg = f"Deterministic file read failed: {str(e)}"
            self._log_run(input_meta, "", "", None, time.time() - start_time, error_msg)
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

        # 3. Request LLM normalization
        try:
            raw_response = self.call_llm(compiled_prompt)
            parsed_json = json.loads(raw_response)
            
            # If the LLM returned a JSON list directly instead of wrapping it in an object
            if isinstance(parsed_json, list):
                parsed_json = {
                    "supplier": supplier_name,
                    "items": parsed_json
                }
            
            # Harmonize key differences
            if isinstance(parsed_json, dict):
                if "supplier_name" in parsed_json and "supplier" not in parsed_json:
                    parsed_json["supplier"] = parsed_json["supplier_name"]
                if "supplier" not in parsed_json:
                    parsed_json["supplier"] = supplier_name
            else:
                raise ValueError("LLM response did not parse into a valid JSON object or list.")
                
            parsed_data = UnifiedShipment(**parsed_json)
        except Exception as e:
            error_msg = f"Agent reasoning or parsing failed: {str(e)}"
            self._log_run(input_meta, compiled_prompt, raw_response, None, time.time() - start_time, error_msg)
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
