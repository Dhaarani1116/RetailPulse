from pydantic import BaseModel
from typing import List, Optional, Any

class RawShipmentItem(BaseModel):
    raw_name: str
    raw_price: float
    raw_quantity: int
    expiry_date: Optional[str] = None

class UnifiedShipment(BaseModel):
    supplier: str
    items: List[RawShipmentItem]

class StandardizedInventoryItem(BaseModel):
    standard_sku: str
    matched_product_id: str
    price: float
    quantity: int
    expiry_date: Optional[str] = None

class StandardizedInventory(BaseModel):
    supplier: str
    items: List[StandardizedInventoryItem]

class ViolationDetail(BaseModel):
    sku: str
    violation_type: str  # PRICE_VIOLATION | EXPIRY_VIOLATION | DUPLICATE_ENTRY | UNKNOWN_PRODUCT
    details: str
    expected_value: Any
    actual_value: Any

class AuditReport(BaseModel):
    supplier: str
    total_billed: float
    violations: List[ViolationDetail]

class DecisionAcceptedItem(BaseModel):
    sku: str
    quantity: int
    price: float

class DecisionRejectedItem(BaseModel):
    sku: str
    quantity: int
    reason: str

class DecisionReport(BaseModel):
    supplier: str
    disposition: str  # ACCEPT | REJECT | PARTIAL_ACCEPT | HUMAN_REVIEW
    risk_score: float
    reasoning: str
    items_accepted: List[DecisionAcceptedItem]
    items_rejected: List[DecisionRejectedItem]

class WorkerTaskItem(BaseModel):
    sku: str
    action: str
    zone: str

class WorkerTasks(BaseModel):
    pdf_path: str
    task_count: int
    tasks: List[WorkerTaskItem]

class PurchaseDocuments(BaseModel):
    po_path: Optional[str] = None
    dispute_email_path: Optional[str] = None
    notice_path: Optional[str] = None

class ManagerSummary(BaseModel):
    pdf_path: str
    accepted_items_count: int
    rejected_items_count: int
    pending_items_count: int
    total_value: float
    supplier_score: float
    executive_summary: str
