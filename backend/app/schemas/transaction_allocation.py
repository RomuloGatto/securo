import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator

AllocationKind = Literal["category", "transfer"]


class TransactionAllocationInput(BaseModel):
    kind: AllocationKind
    amount: Decimal = Field(gt=0)
    category_id: Optional[uuid.UUID] = None
    transfer_account_id: Optional[uuid.UUID] = None
    counterpart_transaction_id: Optional[uuid.UUID] = None
    notes: Optional[str] = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def validate_shape(self):
        if self.kind == "category":
            if self.category_id is None:
                raise ValueError("category_id is required for category allocations")
            if self.transfer_account_id is not None or self.counterpart_transaction_id is not None:
                raise ValueError("category allocations cannot include transfer fields")
        else:
            if self.transfer_account_id is None:
                raise ValueError("transfer_account_id is required for transfer allocations")
            if self.category_id is not None:
                raise ValueError("transfer allocations cannot include category_id")
        return self


class TransactionAllocationRead(BaseModel):
    id: uuid.UUID
    transaction_id: uuid.UUID
    workspace_id: uuid.UUID
    kind: str
    amount: Decimal
    category_id: Optional[uuid.UUID] = None
    transfer_account_id: Optional[uuid.UUID] = None
    counterpart_transaction_id: Optional[uuid.UUID] = None
    counterpart_created: bool = False
    notes: Optional[str] = None
    sort_order: int = 0
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)
