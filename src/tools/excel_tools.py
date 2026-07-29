import pandas as pd
from typing import List, Dict, Any

def read_excel(file_path: str) -> List[Dict[str, Any]]:
    """
    Read an Excel sheet and parse rows as a list of dictionaries.
    """
    df = pd.read_excel(file_path)
    # Replace NaN values with None so JSON serialization works seamlessly
    df = df.where(pd.notnull(df), None)
    return df.to_dict(orient="records")

def read_csv(file_path: str) -> List[Dict[str, Any]]:
    """
    Read a CSV file and parse rows as a list of dictionaries.
    """
    df = pd.read_csv(file_path)
    df = df.where(pd.notnull(df), None)
    return df.to_dict(orient="records")

def write_excel(data: List[Dict[str, Any]], output_path: str) -> None:
    """
    Write a list of dictionaries to an Excel sheet.
    """
    df = pd.DataFrame(data)
    df.to_excel(output_path, index=False)
