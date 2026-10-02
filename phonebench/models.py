from datetime import datetime
from decimal import Decimal

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    display_name = db.Column(db.String(120), nullable=False)
    role = db.Column(db.String(24), nullable=False, default="TECHNICIAN")
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class Customer(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(160), nullable=False, index=True)
    phone = db.Column(db.String(40), index=True)
    email = db.Column(db.String(255))
    address = db.Column(db.Text)
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    devices = db.relationship("Device", back_populates="owner")
    repairs = db.relationship("Repair", back_populates="customer")
    messages = db.relationship("CustomerMessage", back_populates="customer", cascade="all, delete-orphan")


class CustomerMessage(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False, index=True)
    repair_id = db.Column(db.Integer, db.ForeignKey("repair.id"), index=True)
    channel = db.Column(db.String(32), nullable=False)
    direction = db.Column(db.String(16), nullable=False, default="OUTBOUND")
    event = db.Column(db.String(80))
    body = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(24), nullable=False, default="SENT")
    provider_reference = db.Column(db.String(160))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    customer = db.relationship("Customer", back_populates="messages")
    repair = db.relationship("Repair")


class Device(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    owner_id = db.Column(db.Integer, db.ForeignKey("customer.id"))
    brand = db.Column(db.String(100), nullable=False, index=True)
    model = db.Column(db.String(160), nullable=False, index=True)
    marketing_name = db.Column(db.String(160))
    device_code = db.Column(db.String(120), index=True)
    board = db.Column(db.String(120))
    hardware = db.Column(db.String(120))
    soc = db.Column(db.String(120))
    cpu = db.Column(db.String(120))
    gpu = db.Column(db.String(120))
    ram = db.Column(db.String(60))
    storage = db.Column(db.String(60))
    display = db.Column(db.String(120))
    android_version = db.Column(db.String(60))
    android_build = db.Column(db.String(180))
    security_patch = db.Column(db.String(40))
    camera = db.Column(db.String(120))
    battery = db.Column(db.String(120))
    network = db.Column(db.String(120))
    region = db.Column(db.String(80))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    owner = db.relationship("Customer", back_populates="devices")
    identifiers = db.relationship("DeviceIdentifier", back_populates="device", cascade="all, delete-orphan")
    properties = db.relationship("DeviceProperty", back_populates="device", cascade="all, delete-orphan")
    repairs = db.relationship("Repair", back_populates="device")


class DeviceIdentifier(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("device.id"), nullable=False, index=True)
    type = db.Column(db.String(40), nullable=False)
    value = db.Column(db.String(255), nullable=False)
    source = db.Column(db.String(80))
    verified = db.Column(db.Boolean, nullable=False, default=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    device = db.relationship("Device", back_populates="identifiers")


class DeviceProperty(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    device_id = db.Column(db.Integer, db.ForeignKey("device.id"), nullable=False, index=True)
    property_name = db.Column(db.String(180), nullable=False)
    property_value = db.Column(db.Text)
    source = db.Column(db.String(80), nullable=False, default="manual")
    captured_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    device = db.relationship("Device", back_populates="properties")


class PendingDeviceScan(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False, index=True)
    serial = db.Column(db.String(120), nullable=False)
    properties_json = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class Repair(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(32), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False, index=True)
    device_id = db.Column(db.Integer, db.ForeignKey("device.id"), nullable=False, index=True)
    assigned_technician_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    status = db.Column(db.String(32), nullable=False, default="RECEIVED", index=True)
    priority = db.Column(db.String(20), nullable=False, default="NORMAL")
    customer_problem = db.Column(db.Text, nullable=False)
    initial_condition = db.Column(db.Text)
    power_state = db.Column(db.String(32))
    display_state = db.Column(db.String(32))
    usb_state = db.Column(db.String(32))
    physical_condition = db.Column(db.Text)
    security_lock_state = db.Column(db.Text)
    estimated_cost = db.Column(db.Numeric(12, 2), default=Decimal("0"))
    final_cost = db.Column(db.Numeric(12, 2), default=Decimal("0"))
    received_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    started_at = db.Column(db.DateTime)
    completed_at = db.Column(db.DateTime)
    picked_up_at = db.Column(db.DateTime)
    public_notes = db.Column(db.Text)
    private_notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    customer = db.relationship("Customer", back_populates="repairs")
    device = db.relationship("Device")
    technician = db.relationship("User", foreign_keys=[assigned_technician_id])
    diagnoses = db.relationship("Diagnosis", back_populates="repair", cascade="all, delete-orphan")
    attempts = db.relationship("RepairAttempt", back_populates="repair", cascade="all, delete-orphan", order_by="RepairAttempt.attempt_number")
    invoices = db.relationship("Invoice", back_populates="repair")
    movements = db.relationship("InventoryMovement", back_populates="repair")
    portal_tokens = db.relationship("PortalToken", back_populates="repair", cascade="all, delete-orphan")


class Diagnosis(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    repair_id = db.Column(db.Integer, db.ForeignKey("repair.id"), nullable=False, index=True)
    problem_category = db.Column(db.String(100), nullable=False)
    symptoms = db.Column(db.Text)
    diagnosis = db.Column(db.Text, nullable=False)
    confidence = db.Column(db.Integer)
    technician_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    repair = db.relationship("Repair", back_populates="diagnoses")
    technician = db.relationship("User")


class RepairAttempt(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    repair_id = db.Column(db.Integer, db.ForeignKey("repair.id"), nullable=False, index=True)
    attempt_number = db.Column(db.Integer, nullable=False)
    technician_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    tool = db.Column(db.String(160))
    tool_version = db.Column(db.String(80))
    firmware = db.Column(db.String(180))
    firmware_version = db.Column(db.String(120))
    method = db.Column(db.String(180))
    procedure = db.Column(db.Text)
    command_or_output = db.Column(db.Text)
    error_message = db.Column(db.Text)
    result = db.Column(db.String(20), nullable=False, default="UNKNOWN")
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    repair = db.relationship("Repair", back_populates="attempts")
    technician = db.relationship("User")
    __table_args__ = (db.UniqueConstraint("repair_id", "attempt_number"),)


class Solution(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    source_repair_id = db.Column(db.Integer, db.ForeignKey("repair.id"), nullable=False)
    source_attempt_id = db.Column(db.Integer, db.ForeignKey("repair_attempt.id"), nullable=False, unique=True)
    title = db.Column(db.String(180), nullable=False)
    device_model = db.Column(db.String(180), index=True)
    problem = db.Column(db.Text)
    symptoms = db.Column(db.Text)
    solution = db.Column(db.Text, nullable=False)
    tool = db.Column(db.String(160))
    tool_version = db.Column(db.String(80))
    firmware = db.Column(db.String(180))
    firmware_version = db.Column(db.String(120))
    procedure = db.Column(db.Text)
    warnings = db.Column(db.Text)
    success_count = db.Column(db.Integer, nullable=False, default=1)
    failure_count = db.Column(db.Integer, nullable=False, default=0)
    verified = db.Column(db.Boolean, nullable=False, default=False)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    source_repair = db.relationship("Repair")
    source_attempt = db.relationship("RepairAttempt")
    author = db.relationship("User")


class ManualGuide(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    category = db.Column(db.String(32), nullable=False, default="GUIDE", index=True)
    title = db.Column(db.String(180), nullable=False, index=True)
    device_model = db.Column(db.String(180), index=True)
    problem = db.Column(db.Text)
    tool = db.Column(db.String(160), index=True)
    software = db.Column(db.String(180), index=True)
    content = db.Column(db.Text, nullable=False)
    procedure = db.Column(db.Text)
    warnings = db.Column(db.Text)
    reference_url = db.Column(db.String(1000))
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)
    author = db.relationship("User")


class InventoryItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    sku = db.Column(db.String(80), unique=True, index=True)
    name = db.Column(db.String(180), nullable=False, index=True)
    category = db.Column(db.String(60), nullable=False, default="Other")
    brand = db.Column(db.String(100))
    model = db.Column(db.String(160))
    description = db.Column(db.Text)
    quantity = db.Column(db.Integer, nullable=False, default=0)
    minimum_quantity = db.Column(db.Integer, nullable=False, default=0)
    unit_cost = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    selling_price = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    supplier = db.Column(db.String(160))
    location = db.Column(db.String(120))
    serial_number = db.Column(db.String(120))
    notes = db.Column(db.Text)


class InventoryMovement(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    item_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"), nullable=False, index=True)
    repair_id = db.Column(db.Integer, db.ForeignKey("repair.id"), index=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    movement_type = db.Column(db.String(24), nullable=False)
    quantity = db.Column(db.Integer, nullable=False)
    reference = db.Column(db.String(160))
    notes = db.Column(db.Text)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    item = db.relationship("InventoryItem")
    repair = db.relationship("Repair", back_populates="movements")


class Invoice(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_number = db.Column(db.String(32), unique=True, nullable=False, index=True)
    customer_id = db.Column(db.Integer, db.ForeignKey("customer.id"), nullable=False, index=True)
    repair_id = db.Column(db.Integer, db.ForeignKey("repair.id"), index=True)
    status = db.Column(db.String(24), nullable=False, default="DRAFT", index=True)
    subtotal = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    discount = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    tax = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    total = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    due_date = db.Column(db.Date)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    customer = db.relationship("Customer")
    repair = db.relationship("Repair", back_populates="invoices")
    items = db.relationship("InvoiceItem", back_populates="invoice", cascade="all, delete-orphan")
    payments = db.relationship("Payment", back_populates="invoice", cascade="all, delete-orphan")

    @property
    def paid(self):
        return sum((payment.amount for payment in self.payments if payment.kind != "REFUND"), Decimal("0")) - sum(
            (payment.amount for payment in self.payments if payment.kind == "REFUND"), Decimal("0")
        )

    @property
    def balance(self):
        return max(Decimal("0"), Decimal(self.total or 0) - self.paid)


class InvoiceItem(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False)
    description = db.Column(db.String(240), nullable=False)
    quantity = db.Column(db.Numeric(10, 2), nullable=False, default=Decimal("1"))
    unit_price = db.Column(db.Numeric(12, 2), nullable=False, default=Decimal("0"))
    inventory_item_id = db.Column(db.Integer, db.ForeignKey("inventory_item.id"))
    invoice = db.relationship("Invoice", back_populates="items")

    @property
    def line_total(self):
        return Decimal(self.quantity or 0) * Decimal(self.unit_price or 0)


class Payment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    invoice_id = db.Column(db.Integer, db.ForeignKey("invoice.id"), nullable=False, index=True)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    method = db.Column(db.String(32), nullable=False)
    kind = db.Column(db.String(16), nullable=False, default="PAYMENT")
    reference = db.Column(db.String(160))
    notes = db.Column(db.Text)
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    invoice = db.relationship("Invoice", back_populates="payments")


class Transaction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    type = db.Column(db.String(16), nullable=False)
    category = db.Column(db.String(80), nullable=False)
    amount = db.Column(db.Numeric(12, 2), nullable=False)
    reference = db.Column(db.String(160), unique=True)
    description = db.Column(db.Text)
    date = db.Column(db.Date, nullable=False, default=datetime.utcnow)
    payment_method = db.Column(db.String(32))
    created_by = db.Column(db.Integer, db.ForeignKey("user.id"))


class PortalToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    token_hash = db.Column(db.String(64), unique=True, nullable=False, index=True)
    repair_id = db.Column(db.Integer, db.ForeignKey("repair.id"), nullable=False, index=True)
    active = db.Column(db.Boolean, nullable=False, default=True)
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)
    repair = db.relationship("Repair", back_populates="portal_tokens")


class Attachment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    entity_type = db.Column(db.String(32), nullable=False, index=True)
    entity_id = db.Column(db.Integer, nullable=False, index=True)
    original_name = db.Column(db.String(255), nullable=False)
    stored_name = db.Column(db.String(255), nullable=False, unique=True)
    mime_type = db.Column(db.String(120))
    size = db.Column(db.Integer, nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey("user.id"))
    created_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)


class AuditLog(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"))
    action = db.Column(db.String(100), nullable=False)
    entity_type = db.Column(db.String(60), nullable=False)
    entity_id = db.Column(db.String(80))
    old_value = db.Column(db.Text)
    new_value = db.Column(db.Text)
    ip_address = db.Column(db.String(64))
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, index=True)


class AppSetting(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    key = db.Column(db.String(100), unique=True, nullable=False)
    value = db.Column(db.Text)
    updated_at = db.Column(db.DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)


class NotificationTemplate(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    event = db.Column(db.String(80), unique=True, nullable=False)
    template = db.Column(db.Text, nullable=False)
    enabled = db.Column(db.Boolean, nullable=False, default=True)
