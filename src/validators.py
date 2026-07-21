# src/validators.py
import logging

logger = logging.getLogger(__name__)

def validate_record(record: dict, required_keys: list) -> bool:
    """
    Validates that a record contains non-empty values for required keys.
    Drops records containing placeholder text like 'N/A' or empty strings.
    """
    for key in required_keys:
        val = record.get(key)
        if not val or str(val).strip().upper() in ["N/A", "NONE", ""]:
            logger.debug(f"Validation failed for key '{key}' with value: {val}")
            return False
    return True