from datetime import date, datetime, timedelta
from decimal import Decimal

from .extensions import db
from .models import (
    Customer, Device, DeviceIdentifier, Diagnosis, InventoryItem, Invoice,
    InvoiceItem, Payment, Repair, RepairAttempt, Solution, Transaction,
)


def seed_demo_data():
    if Customer.query.filter(Customer.name.like("Demo Customer %")).first():
        return
    customers = [
        Customer(name="Demo Customer One", phone="+620000000001", email="demo.one@example.invalid", notes="DEMO DATA — fictional evaluation record."),
        Customer(name="Demo Customer Two", phone="+620000000002", email="demo.two@example.invalid", notes="DEMO DATA — fictional evaluation record."),
        Customer(name="Demo Customer Three", phone="+620000000003", email="demo.three@example.invalid", notes="DEMO DATA — fictional evaluation record."),
    ]
    db.session.add_all(customers)
    db.session.flush()
    devices = [
        Device(owner=customers[0], brand="Samsung", model="SM-A525F", marketing_name="Galaxy A52", device_code="a52q", android_version="13"),
        Device(owner=customers[0], brand="Xiaomi", model="M2101K7AG", marketing_name="Redmi Note 10", device_code="mojito", android_version="12"),
        Device(owner=customers[1], brand="Redmi", model="Redmi Note 10", device_code="mojito"),
        Device(owner=customers[1], brand="Vivo", model="V2111", marketing_name="Y21", device_code="2021"),
        Device(owner=customers[2], brand="Oppo", model="CPH2239", marketing_name="A74"),
        Device(owner=customers[2], brand="Apple", model="iPhone 12", marketing_name="iPhone 12"),
    ]
    db.session.add_all(devices)
    db.session.flush()
    db.session.add(DeviceIdentifier(device_id=devices[0].id, type="Device code", value="SM-A525F", source="demo"))
    repairs_data = [
        ("Bootloop after update", "Bootloop", "Repeated restart after system update.", "REPAIRING"),
        ("Customer reports account lock", "FRP", "Setup asks for a previously used account.", "WAITING_CUSTOMER"),
        ("No mobile signal", "No signal", "Baseband appears unavailable.", "DIAGNOSING"),
        ("Intermittent charging", "Charging", "USB charging connects and disconnects.", "WAITING_PART"),
        ("Stuck on logo", "Stuck logo", "Device remains on the boot logo.", "TESTING"),
        ("Software update failure", "Update failure", "Update installation stops before boot.", "RECEIVED"),
    ]
    repairs = []
    for index, (problem, category, symptom, status) in enumerate(repairs_data):
        row = Repair(
            ticket_number=f"PENDING-DEMO-{index}",
            customer=customers[index % len(customers)],
            device=devices[index],
            customer_problem=f"DEMO — {problem}",
            initial_condition="DEMO DATA — condition recorded for evaluation only.",
            status=status,
            estimated_cost=Decimal(str(75 + (index * 25))),
            public_notes="DEMO status update. No real customer or repair.",
            private_notes="Fictional seeded example.",
            received_at=datetime.utcnow() - timedelta(days=12 - index),
        )
        db.session.add(row)
        db.session.flush()
        row.ticket_number = f"SRV-{datetime.utcnow():%Y}-{row.id:05d}"
        repairs.append(row)
        db.session.add(Diagnosis(repair_id=row.id, problem_category=category, symptoms=symptom, diagnosis=f"DEMO finding for {category.lower()}. Verify with appropriate bench checks.", confidence=65))
    db.session.flush()
    attempt_specs = [
        (0, "Odin", "3.14.4", "A525FXXU", "Full firmware flash", "FAILED", "SHA256 is invalid"),
        (0, "Odin", "3.14.4", "A525FXXU", "Re-download complete firmware package", "SUCCESS", ""),
        (1, "ADB", "platform-tools", "", "Read-only device identification", "PARTIAL", ""),
        (1, "Service tool", "Demo 1.0", "", "Authorized account-state check", "FAILED", "Customer approval required"),
        (1, "Service tool", "Demo 1.0", "", "Customer-approved account-state verification", "SUCCESS", ""),
        (2, "Service tool", "Demo 1.0", "", "Inspect baseband status", "PARTIAL", "Baseband unavailable"),
        (2, "Bench test", "1.0", "", "Connector inspection", "FAILED", "No signal after test"),
        (3, "USB meter", "1.0", "", "Measure charging current", "PARTIAL", "Connector unstable"),
        (3, "Parts catalog", "1.0", "", "Identify compatible flex cable", "UNKNOWN", ""),
        (4, "Odin", "3.14.4", "A525FXXU", "Reflash verified firmware", "SUCCESS", ""),
        (4, "Factory diagnostics", "1.0", "", "Post-repair functional test", "SUCCESS", ""),
        (5, "System recovery", "1.0", "", "Check update failure logs", "FAILED", "Update package verification failed"),
        (5, "Odin", "3.14.4", "A525FXXU", "Clean flash after approval", "SUCCESS", ""),
    ]
    attempts_by_repair = {}
    for repair_index, tool, version, firmware, method, result, error in attempt_specs:
        repair = repairs[repair_index]
        number = attempts_by_repair.get(repair_index, 0) + 1
        attempts_by_repair[repair_index] = number
        attempt = RepairAttempt(
            repair_id=repair.id, attempt_number=number, tool=tool, tool_version=version,
            firmware=firmware, method=method, procedure=f"DEMO procedure: {method}. Use only as fictional evaluation content.",
            error_message=error, result=result,
            notes="DEMO DATA — fictional repair history. Confirm device-specific compatibility.",
        )
        db.session.add(attempt)
        if result == "SUCCESS" and repair_index in {0, 1, 4, 5}:
            db.session.flush()
            db.session.add(Solution(
                source_repair_id=repair.id, source_attempt_id=attempt.id,
                title=f"DEMO — {repair.device.brand} {repair.device.model}: {repair.customer_problem}",
                device_model=repair.device.device_code or repair.device.model,
                problem=repair.customer_problem, symptoms=repair.customer_problem,
                solution=method, tool=tool, tool_version=version,
                firmware=firmware or None, procedure=attempt.procedure,
                warnings="DEMO only. Not a confirmed procedure for a real device.",
                success_count=3 if repair_index == 0 else 1, failure_count=1,
                verified=repair_index == 0,
            ))
    db.session.flush()

    stock = [
        ("USB-FLEX-DEMO", "USB flex cable (demo)", "Parts", 7, 3, "85", "145"),
        ("BAT-A52-DEMO", "Galaxy A52 battery (demo)", "Parts", 2, 2, "260", "390"),
        ("USB-METER-DEMO", "USB power meter (demo)", "Tools", 1, 1, "175", "0"),
        ("CABLE-C-DEMO", "USB-C data cable (demo)", "Cables", 5, 2, "35", "60"),
        ("LICENSE-DEMO", "Bench license (demo)", "Licenses", 1, 0, "0", "0"),
    ]
    items = []
    for sku, name, category, quantity, minimum, cost, price in stock:
        item = InventoryItem(sku=sku, name=name, category=category, quantity=quantity, minimum_quantity=minimum, unit_cost=Decimal(cost), selling_price=Decimal(price), notes="DEMO DATA — fictional inventory.")
        db.session.add(item)
        items.append(item)
    db.session.flush()
    invoices = []
    for index, repair_index in enumerate([0, 1, 2]):
        repair = repairs[repair_index]
        invoice = Invoice(
            invoice_number=f"PENDING-DEMO-{index}", customer_id=repair.customer_id,
            repair_id=repair.id, status="ISSUED", subtotal=Decimal("250.00"),
            discount=Decimal("0"), tax=Decimal("0"), total=Decimal("250.00"),
            due_date=date.today() + timedelta(days=7),
        )
        invoice.items.append(InvoiceItem(description="DEMO repair labor", quantity=1, unit_price=Decimal("150.00")))
        invoice.items.append(InvoiceItem(description="DEMO replacement part", quantity=1, unit_price=Decimal("100.00"), inventory_item_id=items[0].id))
        db.session.add(invoice)
        db.session.flush()
        invoice.invoice_number = f"INV-DEMO-{invoice.id:04d}"
        invoices.append(invoice)
    for invoice, amount in zip(invoices, [Decimal("250.00"), Decimal("75.00")]):
        payment = Payment(invoice=invoice, amount=amount, method="Cash", kind="PAYMENT", reference="DEMO payment", notes="Fictional seeded payment.")
        db.session.add(payment)
        db.session.flush()
        db.session.add(Transaction(
            type="INCOME", category="Repair payment", amount=amount,
            reference=f"PAYMENT:{payment.id}", description=f"DEMO {invoice.invoice_number}",
            date=date.today(), payment_method="Cash",
        ))
        invoice.status = "PAID" if amount == invoice.total else "PARTIALLY_PAID"
    db.session.commit()
