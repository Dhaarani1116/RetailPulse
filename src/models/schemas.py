from enum import Enum
from pydantic import BaseModel, Field, field_validator
from typing import List, Optional, Any, Dict
from datetime import datetime

class LogLevel(str, Enum):
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"

class MissionLogEntry(BaseModel):
    timestamp: datetime = Field(default_factory=lambda: datetime.now().astimezone())
    level: LogLevel
    message: str

class AgentStatus(str, Enum):
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    COMPLETE = "COMPLETE"
    SKIPPED = "SKIPPED"
    RUNNING = "RUNNING"
    INFO = "INFO"
    SUCCESS = "SUCCESS"
    WARNING = "WARNING"
    FAILED = "FAILED"
    WAITING_APPROVAL = "WAITING_APPROVAL"

class AgentStep(BaseModel):
    transaction_id: str
    agent: str
    status: AgentStatus
    current_activity: str = ""
    metrics: Dict[str, int | float | str] = Field(default_factory=dict)
    mission_log: List[MissionLogEntry] = Field(default_factory=list)
    table_data: Optional[List[Dict[str, Any]]] = None
    progress: float = 0.0

    @field_validator("progress")
    @classmethod
    def validate_progress(cls, v: float) -> float:
        if not (0.0 <= v <= 1.0):
            # Clip value to avoid strict crashes in validation from rounding errors
            return max(0.0, min(1.0, v))
        return v

    def add_log(self, level: LogLevel, message: str):
        self.mission_log.append(MissionLogEntry(level=level, message=message))
        self.mission_log = self.mission_log[-20:]




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
