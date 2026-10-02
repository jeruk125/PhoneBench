import os
import secrets
import mimetypes
import zipfile
from sqlalchemy import func
from datetime import datetime
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, current_app, flash, redirect, render_template, request, send_from_directory, url_for
from flask_login import current_user, login_required
from sqlalchemy import or_
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import (
    Attachment, AuditLog, Customer, Device, Diagnosis, InventoryItem, InventoryMovement, Invoice,
    Repair, RepairAttempt, Solution, User,
)
from ..security import ROLE_PERMISSIONS, allowed_upload, audit, permission_required

repairs = Blueprint("repairs", __name__)
REPAIR_STATUSES = ["RECEIVED", "DIAGNOSING", "WAITING_CUSTOMER", "WAITING_PART", "REPAIRING", "TESTING", "COMPLETED", "FAILED", "CANCELLED", "PICKED_UP"]
DIAGNOSIS_CATEGORIES = ["Bootloop", "Stuck logo", "Hardbrick", "Softbrick", "FRP", "Screen lock", "Account lock", "No signal", "IMEI/baseband", "Camera", "Audio", "Charging", "USB", "Wi-Fi", "Bluetooth", "Software corruption", "Update failure", "Application/system crash", "Other"]


def _visible_repair(repair_id):
    repair = db.get_or_404(Repair, repair_id)
    if current_user.role == "TECHNICIAN" and repair.assigned_technician_id != current_user.id:
        abort(403)
    return repair


@repairs.route("/repairs")
@login_required
@permission_required("repairs.read")
def repair_list():
    query = Repair.query
    if current_user.role == "TECHNICIAN":
        query = query.filter_by(assigned_technician_id=current_user.id)
    status = request.args.get("status", "")
    if status in REPAIR_STATUSES:
        query = query.filter_by(status=status)
    return render_template("repairs.html", repairs=query.order_by(Repair.created_at.desc()).all(), statuses=REPAIR_STATUSES, customers=Customer.query.order_by(Customer.name).all(), devices=Device.query.order_by(Device.brand, Device.model).all(), technicians=User.query.filter(User.role.in_(["OWNER", "ADMIN", "TECHNICIAN"])).order_by(User.display_name).all())


@repairs.post("/repairs/new")
@login_required
@permission_required("repairs.write")
def repair_new():
    if current_user.role not in {"OWNER", "ADMIN", "RECEPTIONIST"}:
        abort(403)
    customer = db.session.get(Customer, request.form.get("customer_id", type=int))
    device = db.session.get(Device, request.form.get("device_id", type=int))
    problem = request.form.get("customer_problem", "").strip()
    estimate = _decimal(request.form.get("estimated_cost"))
    priority = request.form.get("priority", "NORMAL")
    assigned_id = request.form.get("assigned_technician_id", type=int)
    assigned = db.session.get(User, assigned_id) if assigned_id else None
    if not customer or not device or not problem or len(problem) > 5000:
        flash("Choose a customer and device, and describe the reported problem.", "danger")
        return redirect(url_for("repairs.repair_list"))
    if device.owner_id and device.owner_id != customer.id:
        flash("This device is already linked to another customer. Select the device's owner or create a separate device record.", "danger")
        return redirect(url_for("repairs.repair_list"))
    if priority not in {"LOW", "NORMAL", "HIGH", "URGENT"} or estimate is None or (assigned_id and (not assigned or assigned.role not in {"OWNER", "ADMIN", "TECHNICIAN"})):
        flash("Priority, estimate, or assigned technician is invalid.", "danger")
        return redirect(url_for("repairs.repair_list"))
    if device.owner_id is None:
        device.owner_id = customer.id
    repair = Repair(
        ticket_number=f"PENDING-{secrets.token_hex(12)}",
        customer_id=customer.id,
        device_id=device.id,
        assigned_technician_id=assigned.id if assigned else None,
        customer_problem=problem,
        initial_condition=request.form.get("initial_condition", "").strip(),
        power_state=request.form.get("power_state", "").strip(),
        display_state=request.form.get("display_state", "").strip(),
        usb_state=request.form.get("usb_state", "").strip(),
        physical_condition=", ".join(request.form.getlist("physical_condition")),
        security_lock_state=", ".join(request.form.getlist("security_lock_state")),
        priority=request.form.get("priority", "NORMAL"),
        estimated_cost=estimate,
    )
    db.session.add(repair)
    db.session.flush()
    repair.ticket_number = f"SRV-{datetime.utcnow():%Y}-{repair.id:05d}"
    audit("create", "repair", repair.id, new_value=repair.ticket_number)
    db.session.commit()
    flash(f"Repair ticket {repair.ticket_number} created.", "success")
    return redirect(url_for("repairs.repair_detail", repair_id=repair.id))


def _decimal(value):
    try:
        amount = Decimal(value or "0")
        return amount if amount.is_finite() and amount >= 0 else None
    except (InvalidOperation, TypeError):
        return None


@repairs.route("/repairs/<int:repair_id>")
@login_required
@permission_required("repairs.read")
def repair_detail(repair_id):
    repair = _visible_repair(repair_id)
    can_read_knowledge = "*" in ROLE_PERMISSIONS.get(current_user.role, set()) or "knowledge.read" in ROLE_PERMISSIONS.get(current_user.role, set())
    related = Solution.query.filter(or_(
        Solution.device_model.ilike(f"%{repair.device.device_code or repair.device.model}%"),
        Solution.problem.ilike(f"%{repair.customer_problem[:60]}%"),
    )).order_by(Solution.verified.desc(), Solution.success_count.desc()).limit(8).all() if can_read_knowledge else []
    stock = InventoryItem.query.filter(InventoryItem.quantity > 0).order_by(InventoryItem.name).all()
    attempt_ids = [attempt.id for attempt in repair.attempts]
    attempt_attachments = Attachment.query.filter(Attachment.entity_type == "attempt", Attachment.entity_id.in_(attempt_ids)).all() if attempt_ids else []
    events = AuditLog.query.filter_by(entity_type="repair", entity_id=str(repair.id)).order_by(AuditLog.timestamp.desc()).limit(50).all()
    return render_template("repair_detail.html", repair=repair, statuses=REPAIR_STATUSES, categories=DIAGNOSIS_CATEGORIES, related=related, stock=stock, attachments=Attachment.query.filter_by(entity_type="repair", entity_id=repair.id).all(), attempt_attachments=attempt_attachments, events=events)


@repairs.post("/repairs/<int:repair_id>/status")
@login_required
@permission_required("repairs.write")
def repair_status(repair_id):
    repair = _visible_repair(repair_id)
    new_status = request.form.get("status")
    if new_status not in REPAIR_STATUSES:
        abort(400)
    old_status = repair.status
    repair.status = new_status
    repair.public_notes = request.form.get("public_notes", "").strip()
    repair.private_notes = request.form.get("private_notes", "").strip()
    if new_status == "REPAIRING" and not repair.started_at:
        repair.started_at = datetime.utcnow()
    if new_status == "COMPLETED":
        repair.completed_at = datetime.utcnow()
    if new_status == "PICKED_UP":
        repair.picked_up_at = datetime.utcnow()
    audit("status_changed", "repair", repair.id, old_status, new_status)
    db.session.commit()
    flash("Repair status updated.", "success")
    return redirect(url_for("repairs.repair_detail", repair_id=repair.id))


@repairs.post("/repairs/<int:repair_id>/diagnosis")
@login_required
@permission_required("repairs.write")
def diagnosis_add(repair_id):
    repair = _visible_repair(repair_id)
    category = request.form.get("custom_category", "").strip() or request.form.get("problem_category", "").strip()
    diagnosis_text = request.form.get("diagnosis", "").strip()
    confidence = request.form.get("confidence", type=int)
    if not category or not diagnosis_text or (confidence is not None and not 0 <= confidence <= 100):
        flash("A diagnosis and valid confidence (0–100) are required.", "danger")
    else:
        diagnosis = Diagnosis(repair_id=repair.id, problem_category=category, symptoms=request.form.get("symptoms", "").strip(), diagnosis=diagnosis_text, confidence=confidence, technician_id=current_user.id)
        db.session.add(diagnosis)
        db.session.flush()
        audit("create", "diagnosis", diagnosis.id)
        db.session.commit()
        flash("Diagnosis recorded.", "success")
    return redirect(url_for("repairs.repair_detail", repair_id=repair.id) + "#diagnosis")


@repairs.post("/repairs/<int:repair_id>/attempts")
@login_required
@permission_required("repairs.write")
def attempt_add(repair_id):
    repair = _visible_repair(repair_id)
    result = request.form.get("result", "UNKNOWN")
    if result not in {"UNKNOWN", "FAILED", "PARTIAL", "SUCCESS"}:
        abort(400)
    attempt = RepairAttempt(
        repair_id=repair.id,
        attempt_number=(repair.attempts[-1].attempt_number + 1) if repair.attempts else 1,
        technician_id=current_user.id,
        tool=request.form.get("tool", "").strip(),
        tool_version=request.form.get("tool_version", "").strip(),
        firmware=request.form.get("firmware", "").strip(),
        firmware_version=request.form.get("firmware_version", "").strip(),
        method=request.form.get("method", "").strip(),
        procedure=request.form.get("procedure", "").strip(),
        command_or_output=request.form.get("command_or_output", "").strip(),
        error_message=request.form.get("error_message", "").strip(),
        result=result,
        notes=request.form.get("notes", "").strip(),
    )
    db.session.add(attempt)
    db.session.flush()
    audit("create", "repair_attempt", attempt.id, new_value=result)
    db.session.commit()
    flash(f"Attempt #{attempt.attempt_number} recorded.", "success")
    return redirect(url_for("repairs.repair_detail", repair_id=repair.id) + "#attempts")


@repairs.post("/repairs/<int:repair_id>/attempts/<int:attempt_id>/solution")
@login_required
@permission_required("knowledge.write")
def solution_from_attempt(repair_id, attempt_id):
    repair = _visible_repair(repair_id)
    attempt = db.session.get(RepairAttempt, attempt_id)
    if not attempt or attempt.repair_id != repair.id or attempt.result != "SUCCESS":
        abort(400)
    if Solution.query.filter_by(source_attempt_id=attempt.id).first():
        flash("This successful attempt already has a knowledge article.", "warning")
        return redirect(url_for("repairs.repair_detail", repair_id=repair.id) + "#attempts")
    solution = Solution(
        source_repair_id=repair.id, source_attempt_id=attempt.id,
        title=request.form.get("title", "").strip() or f"{repair.device.brand} {repair.device.model} — {repair.customer_problem[:70]}",
        device_model=repair.device.device_code or repair.device.model,
        problem=repair.customer_problem, symptoms=request.form.get("symptoms", "").strip(),
        solution=attempt.notes or attempt.method or "See the recorded procedure.",
        tool=attempt.tool, tool_version=attempt.tool_version, firmware=attempt.firmware,
        firmware_version=attempt.firmware_version, procedure=attempt.procedure,
        warnings=request.form.get("warnings", "").strip(), verified=False, created_by=current_user.id,
    )
    related_repairs = Repair.query.join(Device, Repair.device_id == Device.id).filter(
        or_(Device.device_code == repair.device.device_code, Device.model == repair.device.model)
    ).with_entities(Repair.id).all()
    related_ids = [row[0] for row in related_repairs]
    if related_ids:
        counts = db.session.query(RepairAttempt.result, func.count(RepairAttempt.id)).filter(
            RepairAttempt.repair_id.in_(related_ids)
        ).group_by(RepairAttempt.result).all()
        result_counts = dict(counts)
        solution.success_count = result_counts.get("SUCCESS", 0)
        solution.failure_count = result_counts.get("FAILED", 0)
    db.session.add(solution)
    db.session.flush()
    audit("create", "solution", solution.id)
    db.session.commit()
    flash("Historical solution added to the knowledge base as unverified.", "success")
    return redirect(url_for("repairs.knowledge"))


@repairs.route("/knowledge")
@login_required
@permission_required("knowledge.read")
def knowledge():
    query = Solution.query.join(Repair, Solution.source_repair_id == Repair.id).join(Device, Repair.device_id == Device.id)
    term = request.args.get("q", "").strip()
    if term:
        pattern = f"%{term}%"
        query = query.filter(or_(
            Solution.title.ilike(pattern), Solution.device_model.ilike(pattern),
            Solution.problem.ilike(pattern), Solution.symptoms.ilike(pattern),
            Solution.solution.ilike(pattern), Solution.tool.ilike(pattern),
            Solution.firmware.ilike(pattern), Solution.procedure.ilike(pattern),
            Solution.warnings.ilike(pattern),
        ))
    model = request.args.get("model", "").strip()
    if model:
        query = query.filter(Solution.device_model.ilike(f"%{model}%"))
    for field, column in [
        ("brand", Device.brand), ("problem", Solution.problem),
        ("tool", Solution.tool), ("firmware", Solution.firmware),
        ("android", Device.android_version),
    ]:
        value = request.args.get(field, "").strip()
        if value:
            query = query.filter(column.ilike(f"%{value}%"))
    if request.args.get("success") == "true":
        query = query.filter(Solution.success_count > 0)
    elif request.args.get("success") == "false":
        query = query.filter(Solution.failure_count > 0)
    verified = request.args.get("verified", "")
    if verified in {"true", "false"}:
        query = query.filter_by(verified=verified == "true")
    solutions = query.order_by(Solution.verified.desc(), Solution.success_count.desc(), Solution.created_at.desc()).all()
    brands = [value[0] for value in db.session.query(Device.brand).distinct().order_by(Device.brand).all()]
    attachments = Attachment.query.filter_by(entity_type="solution").all()
    return render_template("knowledge.html", solutions=solutions, term=term, brands=brands, attachments=attachments)


@repairs.post("/knowledge/<int:solution_id>/verify")
@login_required
@permission_required("knowledge.write")
def solution_verify(solution_id):
    solution = db.get_or_404(Solution, solution_id)
    solution.verified = request.form.get("verified") == "true"
    audit("verification_changed", "solution", solution.id, new_value=str(solution.verified))
    db.session.commit()
    flash("Knowledge verification updated.", "success")
    return redirect(url_for("repairs.knowledge"))


@repairs.post("/repairs/<int:repair_id>/parts")
@login_required
@permission_required("inventory.read")
def consume_part(repair_id):
    repair = _visible_repair(repair_id)
    item = db.session.get(InventoryItem, request.form.get("item_id", type=int))
    quantity = request.form.get("quantity", 1, type=int)
    if not item or quantity < 1 or item.quantity < quantity:
        flash("Choose an available part and a valid quantity.", "danger")
    else:
        item.quantity -= quantity
        movement = InventoryMovement(item_id=item.id, repair_id=repair.id, user_id=current_user.id, movement_type="REPAIR_USE", quantity=-quantity, reference=repair.ticket_number, notes="Consumed on repair ticket")
        db.session.add(movement)
        audit("inventory_consumed", "repair", repair.id, new_value=f"{item.name} x{quantity}")
        db.session.commit()
        flash("Stock reduced and linked to this repair.", "success")
    return redirect(url_for("repairs.repair_detail", repair_id=repair.id) + "#parts")


@repairs.post("/attachments/<entity_type>/<int:entity_id>")
@login_required
def attachment_upload(entity_type, entity_id):
    if entity_type not in {"customer", "device", "repair", "attempt", "invoice", "solution"}:
        abort(400)
    model_map = {"customer": Customer, "device": Device, "repair": Repair, "attempt": RepairAttempt, "invoice": Invoice, "solution": Solution}
    entity = db.session.get(model_map[entity_type], entity_id)
    if not entity:
        abort(404)
    permission = {
        "customer": "customers.write", "device": "devices.write", "repair": "repairs.write",
        "attempt": "repairs.write", "invoice": "invoices.write", "solution": "knowledge.write",
    }[entity_type]
    if permission not in ROLE_PERMISSIONS.get(current_user.role, set()) and "*" not in ROLE_PERMISSIONS.get(current_user.role, set()):
        abort(403)
    if entity_type == "repair":
        _visible_repair(entity_id)
    elif entity_type == "attempt":
        _visible_repair(entity.repair_id)
    elif entity_type == "invoice" and entity.repair_id:
        if current_user.role == "TECHNICIAN":
            abort(403)
    uploaded = request.files.get("file")
    if not uploaded or not uploaded.filename or not allowed_upload(uploaded.filename):
        flash("Choose an allowed image, document, or log file.", "danger")
        return redirect(request.referrer or url_for("core.dashboard"))
    original_name = secure_filename(uploaded.filename)[:255]
    extension = original_name.rsplit(".", 1)[-1].lower()
    stored_name = f"{secrets.token_hex(20)}.{extension}"
    os.makedirs(current_app.config["UPLOAD_FOLDER"], exist_ok=True)
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored_name)
    uploaded.save(path)
    size = os.path.getsize(path)
    if size > current_app.config["ATTACHMENT_MAX_BYTES"]:
        os.remove(path)
        abort(413)
    with open(path, "rb") as content_file:
        header = content_file.read(16)
    signatures = {
        "png": header.startswith(b"\x89PNG\r\n\x1a\n"),
        "jpg": header.startswith(b"\xff\xd8\xff"),
        "jpeg": header.startswith(b"\xff\xd8\xff"),
        "gif": header.startswith((b"GIF87a", b"GIF89a")),
        "webp": header.startswith(b"RIFF") and header[8:12] == b"WEBP",
        "pdf": header.startswith(b"%PDF-"),
        "docx": header.startswith(b"PK\x03\x04"),
        "doc": header.startswith(bytes.fromhex("D0CF11E0A1B11AE1")),
    }
    if extension in signatures and not signatures[extension]:
        os.remove(path)
        flash("The uploaded file content does not match its file type.", "danger")
        return redirect(request.referrer or url_for("core.dashboard"))
    if extension in {"txt", "log", "csv"} and b"\x00" in header:
        os.remove(path)
        flash("Text and log files must not contain binary data.", "danger")
        return redirect(request.referrer or url_for("core.dashboard"))
    mime_type = mimetypes.guess_type(original_name)[0] or "application/octet-stream"
    attachment = Attachment(entity_type=entity_type, entity_id=entity_id, original_name=original_name, stored_name=stored_name, mime_type=mime_type, size=size, uploaded_by=current_user.id)
    db.session.add(attachment)
    db.session.flush()
    audit("upload", "attachment", attachment.id, new_value=entity_type)
    db.session.commit()
    flash("Attachment uploaded.", "success")
    return redirect(request.referrer or url_for("core.dashboard"))


@repairs.post("/attachments/<int:attachment_id>/delete")
@login_required
def attachment_delete(attachment_id):
    attachment = db.get_or_404(Attachment, attachment_id)
    required = {
        "customer": "customers.write", "device": "devices.write", "repair": "repairs.write",
        "attempt": "repairs.write", "invoice": "invoices.write", "solution": "knowledge.write",
    }.get(attachment.entity_type)
    permissions = ROLE_PERMISSIONS.get(current_user.role, set())
    if required not in permissions and "*" not in permissions:
        abort(403)
    if attachment.entity_type == "repair":
        _visible_repair(attachment.entity_id)
    elif attachment.entity_type == "attempt":
        attempt = db.get_or_404(RepairAttempt, attachment.entity_id)
        _visible_repair(attempt.repair_id)
    stored_name = attachment.stored_name
    entity_type, entity_id = attachment.entity_type, attachment.entity_id
    db.session.delete(attachment)
    audit("delete", "attachment", attachment.id, old_value=entity_type)
    db.session.commit()
    path = os.path.join(current_app.config["UPLOAD_FOLDER"], stored_name)
    if os.path.isfile(path):
        os.remove(path)
    flash("Attachment removed.", "success")
    if entity_type == "repair":
        return redirect(url_for("repairs.repair_detail", repair_id=entity_id) + "#attachments")
    return redirect(request.referrer or url_for("core.dashboard"))


@repairs.get("/attachments/<int:attachment_id>")
@login_required
def attachment_download(attachment_id):
    attachment = db.get_or_404(Attachment, attachment_id)
    required = {
        "customer": "customers.read", "device": "devices.read", "repair": "repairs.read",
        "attempt": "repairs.read", "invoice": "invoices.read", "solution": "knowledge.read",
    }.get(attachment.entity_type)
    permissions = ROLE_PERMISSIONS.get(current_user.role, set())
    if required not in permissions and "*" not in permissions:
        abort(403)
    if attachment.entity_type == "repair":
        _visible_repair(attachment.entity_id)
    elif attachment.entity_type == "attempt":
        attempt = db.get_or_404(RepairAttempt, attachment.entity_id)
        _visible_repair(attempt.repair_id)
    elif attachment.entity_type == "invoice" and current_user.role == "TECHNICIAN":
        abort(403)
    inline_types = {"image/png", "image/jpeg", "image/webp", "image/gif"}
    return send_from_directory(current_app.config["UPLOAD_FOLDER"], attachment.stored_name, as_attachment=attachment.mime_type not in inline_types, download_name=attachment.original_name)
