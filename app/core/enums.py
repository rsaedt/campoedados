from enum import StrEnum


class ModuleCode(StrEnum):
    LIVESTOCK = "livestock"
    FEED_MILL = "feed_mill"
    FINANCE = "finance"


class MembershipRole(StrEnum):
    OPERATOR = "operator"
    MANAGER = "manager"
    ADMIN = "admin"


class EventStatus(StrEnum):
    RECEIVED = "received"
    INTERPRETED = "interpreted"
    WAITING_COMPLEMENT = "waiting_complement"
    WAITING_MANAGER = "waiting_manager"
    APPROVED = "approved"
    REJECTED = "rejected"
    PROCESSED = "processed"
    RECTIFIED = "rectified"
    REVERSED = "reversed"


class ProductType(StrEnum):
    RAW_MATERIAL = "raw_material"
    FINISHED_GOOD = "finished_good"


class MovementType(StrEnum):
    RECEIPT = "receipt"
    PRODUCTION_CONSUMPTION = "production_consumption"
    PRODUCTION_OUTPUT = "production_output"
    TRANSFER_DISPATCH = "transfer_dispatch"
    TRANSFER_RECEIPT = "transfer_receipt"
    ADJUSTMENT = "adjustment"


class TransferStatus(StrEnum):
    IN_TRANSIT = "in_transit"
    RECEIVED = "received"
    DIVERGENT = "divergent"
    CANCELLED = "cancelled"


class PurchaseStatus(StrEnum):
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"


class PayableStatus(StrEnum):
    PENDING_APPROVAL = "pending_approval"
    OPEN = "open"
    PAID = "paid"
    CANCELLED = "cancelled"
