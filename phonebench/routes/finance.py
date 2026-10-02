import secrets
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from io import BytesIO

from flask import Blueprint, abort, flash, make_response, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas
from sqlalchemy import func
from ..extensions import db
from ..models import (
    Customer, InventoryItem, InventoryMovement, Invoice, InvoiceItem, Payment, Repair, Transaction,
)
from ..security import audit, permission_required

finance = Blueprint("finance", __name__)


def money(value):
    try:
        amount = Decimal(value or "0")
        if not amount.is_finite() or amount < 0:
            return None
        return amount.quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError):
        return None


@finance.route("/invoices")
@login_required
@permission_required("invoices.read")
def invoice_list():
    invoices = Invoice.query.order_by(Invoice.created_at.desc()).all()
    today = date.today()
    for invoice in invoices:
        if invoice.status in {"ISSUED", "PARTIALLY_PAID"} and invoice.due_date and invoice.due_date < today and invoice.balance > 0:
            old_status = invoice.status
            invoice.status = "OVERDUE"
            audit("status_changed", "invoice", invoice.id, old_status, "OVERDUE")
    db.session.commit()
    return render_template("invoices.html", invoices=invoices)


@finance.post("/repairs/<int:repair_id>/invoices")
@login_required
@permission_required("invoices.write")
def invoice_create(repair_id):
    repair = db.get_or_404(Repair, repair_id)
    if Invoice.query.filter_by(repair_id=repair.id).filter(Invoice.status != "VOID").first():
        flash("This repair already has an active invoice. Edit it or void it before creating another.", "warning")
        return redirect(url_for("repairs.repair_detail", repair_id=repair.id))
    labor = money(request.form.get("labor", "0"))
    discount = money(request.form.get("discount", "0"))
    tax = money(request.form.get("tax", "0"))
    service_amount = money(request.form.get("service_amount", "0"))
    service_description = request.form.get("service_description", "").strip()
    if None in (labor, discount, tax, service_amount):
        flash("Invoice amounts must be valid non-negative numbers.", "danger")
        return redirect(url_for("repairs.repair_detail", repair_id=repair.id))
    invoice = Invoice(
        invoice_number=f"PENDING-{secrets.token_hex(12)}",
        customer_id=repair.customer_id, repair_id=repair.id, status="DRAFT",
        discount=discount, tax=tax,
    )
    if labor > 0:
        invoice.items.append(InvoiceItem(description="Repair labor", quantity=1, unit_price=labor))
    if service_amount > 0:
        invoice.items.append(InvoiceItem(description=service_description or "Additional service", quantity=1, unit_price=service_amount))
    consumed = db.session.query(InventoryItem, func.sum(-InventoryMovement.quantity)).join(
        InventoryMovement, InventoryMovement.item_id == InventoryItem.id
    ).filter(InventoryMovement.repair_id == repair.id, InventoryMovement.movement_type == "REPAIR_USE").group_by(InventoryItem.id).all()
    for item, quantity in consumed:
        invoice.items.append(InvoiceItem(description=item.name, quantity=quantity, unit_price=item.selling_price, inventory_item_id=item.id))
    invoice.subtotal = sum((line.line_total for line in invoice.items), Decimal("0"))
    if discount > invoice.subtotal:
        flash("Discount cannot exceed the invoice subtotal.", "danger")
        return redirect(url_for("repairs.repair_detail", repair_id=repair.id))
    invoice.total = max(Decimal("0"), invoice.subtotal - discount + tax)
    due_text = request.form.get("due_date", "")
    if due_text:
        try:
            invoice.due_date = date.fromisoformat(due_text)
        except ValueError:
            flash("Due date must be a valid date.", "danger")
            return redirect(url_for("repairs.repair_detail", repair_id=repair.id))
    db.session.add(invoice)
    db.session.flush()
    invoice.invoice_number = f"INV-{datetime.utcnow():%Y%m%d}-{invoice.id:04d}"
    audit("create", "invoice", invoice.id, new_value=invoice.invoice_number)
    db.session.commit()
    flash(f"Draft invoice {invoice.invoice_number} created.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))


@finance.route("/invoices/<int:invoice_id>")
@login_required
@permission_required("invoices.read")
def invoice_detail(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    from ..models import Attachment
    return render_template("invoice_detail.html", invoice=invoice, attachments=Attachment.query.filter_by(entity_type="invoice", entity_id=invoice.id).all())


@finance.post("/invoices/<int:invoice_id>/issue")
@login_required
@permission_required("invoices.write")
def invoice_issue(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    if invoice.status != "DRAFT" or invoice.total < 0:
        abort(400)
    invoice.status = "ISSUED"
    audit("issue", "invoice", invoice.id)
    db.session.commit()
    flash("Invoice issued.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))


@finance.post("/invoices/<int:invoice_id>/void")
@login_required
@permission_required("invoices.write")
def invoice_void(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    if invoice.status not in {"DRAFT", "ISSUED", "OVERDUE"} or invoice.payments:
        flash("Only unpaid invoices can be voided. Refund any payments first and retain the payment history.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))
    old_status = invoice.status
    invoice.status = "VOID"
    audit("void", "invoice", invoice.id, old_value=old_status, new_value="VOID")
    db.session.commit()
    flash("Invoice voided.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))


@finance.get("/invoices/<int:invoice_id>/pdf")
@login_required
@permission_required("invoices.read")
def invoice_pdf(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    stream = BytesIO()
    pdf = canvas.Canvas(stream, pagesize=letter)
    text = pdf.beginText(50, 745)
    text.setFont("Helvetica-Bold", 18)
    text.textLine("PhoneBench Invoice")
    text.setFont("Helvetica", 11)
    for line in [
        invoice.invoice_number,
        f"Customer: {invoice.customer.name}",
        f"Repair: {invoice.repair.ticket_number if invoice.repair else 'Service'}",
        "",
    ]:
        text.textLine(line)
    for item in invoice.items:
        text.textLine(f"{item.description}  x{item.quantity}   {item.line_total:.2f}")
    text.textLine("")
    text.textLine(f"Subtotal: {invoice.subtotal:.2f}")
    text.textLine(f"Discount: {invoice.discount:.2f}    Tax: {invoice.tax:.2f}")
    text.textLine(f"TOTAL: {invoice.total:.2f}    Paid: {invoice.paid:.2f}    Balance: {invoice.balance:.2f}")
    pdf.drawText(text)
    pdf.save()
    response = make_response(stream.getvalue())
    response.headers["Content-Type"] = "application/pdf"
    response.headers["Content-Disposition"] = f'attachment; filename="{invoice.invoice_number}.pdf"'
    return response


@finance.post("/invoices/<int:invoice_id>/payments")
@login_required
@permission_required("payments.write")
def payment_add(invoice_id):
    invoice = db.get_or_404(Invoice, invoice_id)
    amount = money(request.form.get("amount"))
    kind = request.form.get("kind", "PAYMENT")
    method = request.form.get("method", "Cash")
    if kind not in {"PAYMENT", "REFUND"} or method not in {"Cash", "Bank transfer", "QRIS", "E-wallet", "Other"} or amount is None or amount <= 0:
        flash("Enter a valid amount, payment type, and method.", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))
    if invoice.status in {"DRAFT", "VOID"}:
        flash("Payments are allowed only after an invoice is issued.", "warning")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))
    if kind == "PAYMENT" and amount > invoice.balance:
        flash("Payment cannot exceed the invoice balance.", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))
    if kind == "REFUND" and amount > invoice.paid:
        flash("Refund cannot exceed the net amount paid.", "danger")
        return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))
    payment = Payment(invoice=invoice, amount=amount, method=method, kind=kind, reference=request.form.get("reference", "").strip(), notes=request.form.get("notes", "").strip(), created_by=current_user.id)
    db.session.add(payment)
    db.session.flush()
    transaction_type = "INCOME" if kind == "PAYMENT" else "EXPENSE"
    db.session.add(Transaction(
        type=transaction_type, category="Repair payment" if kind == "PAYMENT" else "Customer refund",
        amount=amount, reference=f"PAYMENT:{payment.id}", description=f"{invoice.invoice_number} — {kind.lower()}",
        date=date.today(), payment_method=method, created_by=current_user.id,
    ))
    if kind == "PAYMENT":
        invoice.status = "PAID" if invoice.balance == 0 else "PARTIALLY_PAID"
    else:
        invoice.status = "PARTIALLY_PAID" if invoice.balance else "ISSUED"
    audit("payment_recorded", "payment", payment.id, new_value=f"{kind} {amount}")
    db.session.commit()
    flash("Payment recorded and linked accounting entry created.", "success")
    return redirect(url_for("finance.invoice_detail", invoice_id=invoice.id))


@finance.route("/accounting", methods=["GET", "POST"])
@login_required
@permission_required("accounting.read")
def accounting():
    if request.method == "POST":
        transaction_type = request.form.get("type")
        amount = money(request.form.get("amount"))
        if transaction_type not in {"INCOME", "EXPENSE"} or amount is None or amount <= 0:
            flash("Choose a transaction type and enter a valid positive amount.", "danger")
        else:
            reference = request.form.get("reference", "").strip() or None
            if reference and Transaction.query.filter_by(reference=reference).first():
                flash("That reference is already in use.", "danger")
            else:
                row = Transaction(type=transaction_type, category=request.form.get("category", "Other").strip(), amount=amount, reference=reference, description=request.form.get("description", "").strip(), date=date.today(), payment_method=request.form.get("payment_method", "Other"), created_by=current_user.id)
                db.session.add(row)
                db.session.flush()
                audit("create", "transaction", row.id)
                db.session.commit()
                flash("Accounting transaction recorded.", "success")
                return redirect(url_for("finance.accounting"))
    today = date.today()
    month_start = today.replace(day=1)
    income = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(Transaction.type == "INCOME", Transaction.date >= month_start, Transaction.date <= today).scalar()
    expenses = db.session.query(func.coalesce(func.sum(Transaction.amount), 0)).filter(Transaction.type == "EXPENSE", Transaction.date >= month_start, Transaction.date <= today).scalar()
    return render_template("accounting.html", transactions=Transaction.query.order_by(Transaction.date.desc(), Transaction.id.desc()).limit(200).all(), income=income, expenses=expenses)
