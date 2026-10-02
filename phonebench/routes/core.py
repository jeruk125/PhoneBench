from datetime import date, datetime
import re

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, or_

from ..extensions import db
from ..models import (
    Attachment, Customer, Device, DeviceIdentifier, Diagnosis, Invoice, InventoryItem,
    Repair, RepairAttempt, Solution, Transaction, User,
)
from ..security import ROLE_PERMISSIONS, audit, permission_required

core = Blueprint("core", __name__)


@core.route("/")
@login_required
def dashboard():
    query = Repair.query
    if current_user.role == "TECHNICIAN":
        query = query.filter_by(assigned_technician_id=current_user.id)
    active_repairs = query.filter(~Repair.status.in_(["COMPLETED", "FAILED", "CANCELLED", "PICKED_UP"])).count()
    repairs = query.order_by(Repair.created_at.desc()).limit(8).all()
    paid_today = db.session.query(db.func.coalesce(db.func.sum(Transaction.amount), 0)).filter(
        Transaction.type == "INCOME", Transaction.date == date.today()
    ).scalar()
    permissions = ROLE_PERMISSIONS.get(current_user.role, set())
    can_see_repairs = "*" in permissions or "repairs.read" in permissions
    can_see_invoices = "*" in permissions or "invoices.read" in permissions
    if current_user.role == "TECHNICIAN":
        outstanding_query = Invoice.query.join(Repair, Invoice.repair_id == Repair.id).filter(Repair.assigned_technician_id == current_user.id)
    else:
        outstanding_query = Invoice.query
    outstanding = [invoice for invoice in outstanding_query.filter(Invoice.status.in_(["ISSUED", "PARTIALLY_PAID", "OVERDUE"])).all() if invoice.balance > 0] if can_see_invoices else []
    queue_counts = {status: query.filter_by(status=status).count() for status in ["RECEIVED", "WAITING_CUSTOMER", "WAITING_PART", "REPAIRING", "TESTING", "COMPLETED"]}
    return render_template(
        "dashboard.html",
        active_repairs=active_repairs,
        queue_counts=queue_counts,
        repairs=repairs if can_see_repairs else [],
        revenue_today=paid_today,
        outstanding=outstanding,
        low_stock=InventoryItem.query.filter(InventoryItem.quantity <= InventoryItem.minimum_quantity).order_by(InventoryItem.name).limit(8).all(),
        recent_customers=(Customer.query.join(Repair).filter(Repair.assigned_technician_id == current_user.id).distinct().order_by(Customer.created_at.desc()).limit(5).all() if current_user.role == "TECHNICIAN" else Customer.query.order_by(Customer.created_at.desc()).limit(5).all()) if "*" in permissions or "customers.read" in permissions else [],
        recent_attempts=(RepairAttempt.query.join(Repair).filter(Repair.assigned_technician_id == current_user.id).order_by(RepairAttempt.created_at.desc()).limit(5).all() if current_user.role == "TECHNICIAN" else RepairAttempt.query.order_by(RepairAttempt.created_at.desc()).limit(5).all()) if can_see_repairs else [],
        recent_solutions=Solution.query.order_by(Solution.created_at.desc()).limit(5).all() if "*" in permissions or "knowledge.read" in permissions else [],
        demo_mode=Customer.query.filter(Customer.name.like("Demo Customer %")).first() is not None,
    )


@core.route("/search")
@login_required
def search():
    term = request.args.get("q", "").strip()
    customers, devices, repairs, diagnoses, attempts, solutions, invoices, inventory = [], [], [], [], [], [], [], []
    if term:
        pattern = f"%{term}%"
        permissions = ROLE_PERMISSIONS.get(current_user.role, set())
        can = lambda permission: "*" in permissions or permission in permissions
        customer_query = Customer.query.filter(or_(Customer.name.ilike(pattern), Customer.phone.ilike(pattern), Customer.email.ilike(pattern))) if can("customers.read") else Customer.query.filter(False)
        device_query = Device.query.outerjoin(DeviceIdentifier).filter(or_(
            Device.brand.ilike(pattern), Device.model.ilike(pattern), Device.marketing_name.ilike(pattern),
            Device.device_code.ilike(pattern), DeviceIdentifier.value.ilike(pattern)
        )).distinct().order_by(case((Device.model.ilike(term), 0), (Device.device_code.ilike(term), 0), else_=1), Device.brand, Device.model)
        if not can("devices.read"):
            device_query = Device.query.filter(False)
        repair_query = Repair.query.filter(or_(
            Repair.ticket_number.ilike(pattern), Repair.customer_problem.ilike(pattern),
            Repair.public_notes.ilike(pattern), Repair.private_notes.ilike(pattern)
        )).order_by(case((Repair.ticket_number.ilike(term), 0), else_=1), Repair.created_at.desc())
        diagnosis_query = Diagnosis.query.filter(or_(Diagnosis.problem_category.ilike(pattern), Diagnosis.symptoms.ilike(pattern), Diagnosis.diagnosis.ilike(pattern))).order_by(Diagnosis.created_at.desc())
        attempt_query = RepairAttempt.query.filter(or_(
            RepairAttempt.tool.ilike(pattern), RepairAttempt.firmware.ilike(pattern),
            RepairAttempt.method.ilike(pattern), RepairAttempt.procedure.ilike(pattern),
            RepairAttempt.command_or_output.ilike(pattern), RepairAttempt.error_message.ilike(pattern),
            RepairAttempt.notes.ilike(pattern),
        )).order_by(case((RepairAttempt.error_message.ilike(term), 0), else_=1), RepairAttempt.created_at.desc())
        solution_query = Solution.query.filter(or_(
            Solution.title.ilike(pattern), Solution.device_model.ilike(pattern), Solution.problem.ilike(pattern),
            Solution.symptoms.ilike(pattern), Solution.solution.ilike(pattern), Solution.procedure.ilike(pattern),
            Solution.tool.ilike(pattern), Solution.firmware.ilike(pattern), Solution.warnings.ilike(pattern)
        )).order_by(case((Solution.device_model.ilike(term), 0), (Solution.problem.ilike(term), 0), else_=1), Solution.verified.desc(), Solution.success_count.desc())
        if current_user.role == "TECHNICIAN":
            assigned = Repair.assigned_technician_id == current_user.id
            customer_query = customer_query.join(Repair).filter(assigned)
            device_query = device_query.join(Repair, Repair.device_id == Device.id).filter(assigned)
            repair_query = repair_query.filter(assigned)
            diagnosis_query = diagnosis_query.join(Repair).filter(assigned)
            attempt_query = attempt_query.join(Repair).filter(assigned)
        customers = customer_query.limit(10).all()
        devices = device_query.limit(15).all()
        repairs = repair_query.limit(15).all()
        diagnoses = diagnosis_query.limit(10).all() if can("repairs.read") else []
        attempts = attempt_query.limit(15).all() if can("repairs.read") else []
        repairs = repairs if can("repairs.read") else []
        solutions = solution_query.limit(15).all() if can("knowledge.read") else []
        if can("invoices.read"):
            invoices = Invoice.query.filter(Invoice.invoice_number.ilike(pattern)).limit(10).all()
        if can("inventory.read"):
            inventory = InventoryItem.query.filter(or_(InventoryItem.name.ilike(pattern), InventoryItem.sku.ilike(pattern))).limit(10).all()
    return render_template("search.html", term=term, customers=customers, devices=devices, repairs=repairs, diagnoses=diagnoses, attempts=attempts, solutions=solutions, invoices=invoices, inventory=inventory)


@core.route("/customers")
@login_required
@permission_required("customers.read")
def customers():
    term = request.args.get("q", "").strip()
    query = Customer.query
    if term:
        pattern = f"%{term}%"
        query = query.filter(or_(Customer.name.ilike(pattern), Customer.phone.ilike(pattern), Customer.email.ilike(pattern)))
    if current_user.role == "TECHNICIAN":
        query = query.join(Repair).filter(Repair.assigned_technician_id == current_user.id).distinct()
    return render_template("customers.html", customers=query.order_by(Customer.name).all())


@core.route("/customers/new", methods=["GET", "POST"])
@login_required
@permission_required("customers.write")
def customer_new():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        if not name or len(name) > 160:
            flash("A customer name of 1–160 characters is required.", "danger")
        elif phone and not re.fullmatch(r"[0-9+(). -]{1,40}", phone):
            flash("Enter a valid phone number using digits and common phone punctuation.", "danger")
        elif email and (len(email) > 255 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)):
            flash("Enter a valid email address.", "danger")
        else:
            customer = Customer(name=name, phone=phone, email=email, address=request.form.get("address", "").strip(), notes=request.form.get("notes", "").strip())
            db.session.add(customer)
            db.session.flush()
            audit("create", "customer", customer.id)
            db.session.commit()
            flash("Customer created.", "success")
            return redirect(url_for("core.customer_detail", customer_id=customer.id))
    return render_template("customer_form.html")


@core.route("/customers/<int:customer_id>")
@login_required
@permission_required("customers.read")
def customer_detail(customer_id):
    customer = db.get_or_404(Customer, customer_id)
    if current_user.role == "TECHNICIAN" and not Repair.query.filter_by(customer_id=customer.id, assigned_technician_id=current_user.id).first():
        abort(403)
    return render_template("customer_detail.html", customer=customer, attachments=Attachment.query.filter_by(entity_type="customer", entity_id=customer.id).all())


@core.route("/customers/<int:customer_id>/edit", methods=["GET", "POST"])
@login_required
@permission_required("customers.write")
def customer_edit(customer_id):
    customer = db.get_or_404(Customer, customer_id)
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        if not name or len(name) > 160:
            flash("A customer name of 1–160 characters is required.", "danger")
        elif phone and not re.fullmatch(r"[0-9+(). -]{1,40}", phone):
            flash("Enter a valid phone number using digits and common phone punctuation.", "danger")
        elif email and (len(email) > 255 or not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", email)):
            flash("Enter a valid email address.", "danger")
        else:
            customer.name = name
            customer.phone = phone
            customer.email = email
            customer.address = request.form.get("address", "").strip()
            customer.notes = request.form.get("notes", "").strip()
            audit("update", "customer", customer.id)
            db.session.commit()
            flash("Customer updated.", "success")
            return redirect(url_for("core.customer_detail", customer_id=customer.id))
    return render_template("customer_form.html", customer=customer)


@core.route("/devices")
@login_required
@permission_required("devices.read")
def devices():
    term = request.args.get("q", "").strip()
    query = Device.query
    if term:
        pattern = f"%{term}%"
        query = query.filter(or_(Device.brand.ilike(pattern), Device.model.ilike(pattern), Device.device_code.ilike(pattern)))
    return render_template("devices.html", devices=query.order_by(Device.brand, Device.model).all(), customers=Customer.query.order_by(Customer.name).all())


@core.route("/devices/new", methods=["POST"])
@login_required
@permission_required("devices.write")
def device_new():
    brand = request.form.get("brand", "").strip()
    model = request.form.get("model", "").strip()
    owner_id = request.form.get("owner_id", type=int)
    owner = db.session.get(Customer, owner_id) if owner_id else None
    if not brand or not model or len(brand) > 100 or len(model) > 160 or (owner_id and not owner):
        flash("Brand and model are required.", "danger")
        return redirect(url_for("core.devices"))
    device = Device(
        brand=brand, model=model, marketing_name=request.form.get("marketing_name", "").strip(),
        device_code=request.form.get("device_code", "").strip(), android_version=request.form.get("android_version", "").strip(),
        android_build=request.form.get("android_build", "").strip(), security_patch=request.form.get("security_patch", "").strip(),
        owner_id=owner.id if owner else None, notes=request.form.get("notes", "").strip(),
    )
    db.session.add(device)
    db.session.flush()
    identifier = request.form.get("identifier", "").strip()
    if identifier:
        identifier_type = request.form.get("identifier_type", "Serial")
        db.session.add(DeviceIdentifier(device_id=device.id, type=identifier_type, value=identifier, source="manual"))
    audit("create", "device", device.id)
    db.session.commit()
    flash("Device created.", "success")
    return redirect(url_for("core.devices"))


@core.route("/devices/<int:device_id>")
@login_required
@permission_required("devices.read")
def device_detail(device_id):
    device = db.get_or_404(Device, device_id)
    if current_user.role == "TECHNICIAN" and not Repair.query.filter_by(device_id=device.id, assigned_technician_id=current_user.id).first():
        abort(403)
    repairs = Repair.query.filter_by(device_id=device.id).order_by(Repair.created_at.desc()).all()
    solutions = Solution.query.filter(Solution.device_model.in_([device.model, device.device_code])).order_by(Solution.success_count.desc()).all()
    return render_template("device_detail.html", device=device, repairs=repairs, solutions=solutions, attachments=Attachment.query.filter_by(entity_type="device", entity_id=device.id).all())


@core.post("/devices/<int:device_id>/identifiers")
@login_required
@permission_required("devices.write")
def device_identifier_add(device_id):
    device = db.get_or_404(Device, device_id)
    identifier_type = request.form.get("type", "").strip()
    value = request.form.get("value", "").strip()
    allowed = {"IMEI 1", "IMEI 2", "Serial", "Model", "Product", "Device code", "Board", "Hardware", "Build fingerprint", "Android ID", "USB VID", "USB PID", "Other"}
    if identifier_type not in allowed or not value:
        flash("Choose a supported identifier type and provide its value.", "danger")
    else:
        identifier = DeviceIdentifier(device_id=device.id, type=identifier_type, value=value, source=request.form.get("source", "manual").strip(), verified=bool(request.form.get("verified")))
        db.session.add(identifier)
        db.session.flush()
        audit("create", "device_identifier", identifier.id)
        db.session.commit()
        flash("Device identifier added.", "success")
    return redirect(url_for("core.device_detail", device_id=device.id))


@core.route("/users", methods=["GET", "POST"])
@login_required
def users():
    if current_user.role not in {"OWNER", "ADMIN"}:
        abort(403)
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        display_name = request.form.get("display_name", "").strip()
        role = request.form.get("role", "TECHNICIAN")
        password = request.form.get("password", "")
        if role not in {"ADMIN", "TECHNICIAN", "RECEPTIONIST", "ACCOUNTING"} or len(password) < 12 or not username or not display_name:
            flash("Provide a name, username, supported role, and password of at least 12 characters.", "danger")
        elif User.query.filter_by(username=username).first():
            flash("That username already exists.", "danger")
        else:
            user = User(username=username, display_name=display_name, role=role)
            user.set_password(password)
            db.session.add(user)
            db.session.flush()
            audit("create", "user", user.id)
            db.session.commit()
            flash("User account created.", "success")
            return redirect(url_for("core.users"))
    return render_template("users.html", users=User.query.order_by(User.display_name).all())
