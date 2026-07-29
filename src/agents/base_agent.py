import os
import json
import time
import logging
from datetime import datetime
from typing import Any, Dict, Optional
import google.generativeai as genai
import config

logger = logging.getLogger("RetailPulse")
logger.setLevel(logging.INFO)

# Configure Gemini
if config.GEMINI_API_KEY:
    genai.configure(api_key=config.GEMINI_API_KEY)
else:
    logger.warning("GEMINI_API_KEY is not configured in .env file or environment.")

class BaseAgent:
    def __init__(self, name: str, default_model: str = config.MODEL_FLASH, default_temp: float = 0.2):
        self.name = name
        self.model_name = default_model
        self.temperature = default_temp
        self.prompt_path = config.PROMPTS_DIR / f"{name.lower()}.md"
        self.log_path = config.LOGS_DIR / f"{name.lower()}.log"
        self.model = None
        if config.GEMINI_API_KEY:
            self.model = genai.GenerativeModel(self.model_name)

    def _load_prompt(self) -> str:
        """
        Load the system prompt markdown template file.
        """
        if not self.prompt_path.exists():
            raise FileNotFoundError(f"Prompt template for agent '{self.name}' not found at: {self.prompt_path}")
        with open(self.prompt_path, 'r', encoding='utf-8') as f:
            return f.read().strip()

    def _log_run(self, input_data: Any, prompt: str, raw_response: str, parsed_output: Any, execution_time: float, error: Optional[str] = None) -> None:
        """
        Append details of the current execution trace to the logs folder.
        """
        log_entry = {
            "timestamp": datetime.now().isoformat(),
            "agent": self.name,
            "model": self.model_name,
            "temperature": self.temperature,
            "execution_time_seconds": round(execution_time, 3),
            "input": input_data,
            "compiled_prompt": prompt,
            "raw_response": raw_response,
            "parsed_output": parsed_output,
            "error": error
        }
        with open(self.log_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(log_entry, indent=2) + "\n\n")

    def call_llm(self, prompt: str) -> str:
        """
        Call the Gemini model with a structured JSON request constraint.
        Includes a 3-attempt retry loop with a 2-second delay.
        """
        if not config.GEMINI_API_KEY:
            raise ValueError("GEMINI_API_KEY is not configured. Please check your .env configuration.")

        # Hash of prompt and model to lookup in cache
        import hashlib
        prompt_hash = hashlib.md5((self.model_name + prompt).encode("utf-8")).hexdigest()
        cache_file = config.BASE_DIR / "database" / "llm_cache.json"
        
        # Load cache
        cache = {}
        if cache_file.exists():
            try:
                with open(cache_file, "r", encoding="utf-8") as f:
                    cache = json.load(f)
            except Exception:
                pass
                
        # If cache hit, return immediately
        if prompt_hash in cache:
            logger.info(f"Agent '{self.name}' - Prompt cache hit.")
            return cache[prompt_hash].strip()

        if self.model is None:
            self.model = genai.GenerativeModel(self.model_name)
        
        # Enforce JSON output and apply temperature config
        generation_config = {
            "response_mime_type": "application/json",
            "temperature": self.temperature
        }
        
        retries = 5
        delay = 3.0
        last_error = None
        
        for attempt in range(retries):
            try:
                response = self.model.generate_content(
                    prompt,
                    generation_config=generation_config
                )
                if not response.text:
                    raise RuntimeError("Empty text response received from Gemini API.")
                
                result_text = response.text.strip()
                
                # Write to cache on success
                cache[prompt_hash] = result_text
                try:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(cache, f, indent=2)
                except Exception:
                    pass
                    
                return result_text
            except Exception as e:
                last_error = e
                err_str = str(e)
                if "429" in err_str or "Quota exceeded" in err_str or "RESOURCE_EXHAUSTED" in err_str:
                    sleep_time = 15.0
                    logger.warning(
                        f"Agent '{self.name}' hit rate limit (429). "
                        f"Attempt {attempt + 1} failed. Sleeping for {sleep_time} seconds before retrying..."
                    )
                    time.sleep(sleep_time)
                else:
                    logger.warning(
                        f"Agent '{self.name}' API call attempt {attempt + 1} failed: {err_str}. "
                        f"Retrying in {delay} seconds..."
                    )
                    time.sleep(delay)
                    
        raise RuntimeError(
            f"Agent '{self.name}' failed to retrieve LLM response after {retries} attempts. "
            f"Last error: {str(last_error)}"
        )
