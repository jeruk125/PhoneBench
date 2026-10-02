import json
import os
import re
import csv
import io
from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation

from flask import Blueprint, abort, current_app, flash, jsonify, redirect, render_template, request, send_file, session, url_for
from flask_login import current_user, login_required
from sqlalchemy import case, func, or_
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import (
    AppSetting, AuditLog, CustomerMessage, Device, DeviceIdentifier, DeviceProperty,
    Diagnosis, Invoice, InventoryItem, InventoryMovement, NotificationTemplate, Payment,
    PendingDeviceScan, Repair, RepairAttempt, Solution, Transaction, User,
)
from ..security import audit, permission_required
from ..services.adb import ADBUnavailable, read_properties, scan_devices
from ..services.backup import create_database_backup, export_records, restore_attachments, restore_database
from ..services.ai import AIProviderError, OpenAICompatibleProvider
from ..money import parse_money

operations = Blueprint("operations", __name__)


def _owner_only():
    if current_user.role not in {"OWNER", "ADMIN"}:
        abort(403)


def _amount(value, currency="IDR"):
    try:
        amount = parse_money(value, currency)
        return amount.quantize(Decimal("0.01")) if amount.is_finite() and amount >= 0 else None
    except (InvalidOperation, TypeError):
        return None


@operations.route("/inventory", methods=["GET", "POST"])
@login_required
def inventory():
    if current_user.role not in {"OWNER", "ADMIN", "ACCOUNTING", "RECEPTIONIST"}:
        abort(403)
    if request.method == "POST":
        action = request.form.get("action", "create")
        if action == "movement":
            item = db.session.get(InventoryItem, request.form.get("item_id", type=int))
            quantity = request.form.get("quantity", type=int)
            movement_type = request.form.get("movement_type", "")
            if not item or movement_type not in {"STOCK_IN", "STOCK_OUT", "ADJUSTMENT", "TRANSFER"}:
                flash("Choose an item, valid positive quantity, and movement type.", "danger")
            else:
                if movement_type == "ADJUSTMENT":
                    delta = request.form.get("adjustment", type=int)
                    if delta is None or delta == 0:
                        flash("An adjustment must be a non-zero signed whole number.", "danger")
                        return redirect(url_for("operations.inventory"))
                else:
                    if not quantity or quantity < 1:
                        flash("Enter a positive whole-number quantity.", "danger")
                        return redirect(url_for("operations.inventory"))
                    if movement_type == "STOCK_OUT" and item.quantity < quantity:
                        flash("Stock cannot fall below zero.", "danger")
                        return redirect(url_for("operations.inventory"))
                    delta = quantity if movement_type == "STOCK_IN" else -quantity
                if item.quantity + delta < 0:
                    flash("This movement would make stock negative.", "danger")
                    return redirect(url_for("operations.inventory"))
                item.quantity += delta
                movement = InventoryMovement(item_id=item.id, user_id=current_user.id, movement_type=movement_type, quantity=delta, reference=request.form.get("reference", "").strip(), notes=request.form.get("notes", "").strip())
                db.session.add(movement)
                db.session.flush()
                audit("inventory_movement", "inventory_item", item.id, new_value=f"{movement_type} {delta}")
                db.session.commit()
                flash("Inventory movement recorded.", "success")
                return redirect(url_for("operations.inventory"))
        else:
            name = request.form.get("name", "").strip()
            quantity = request.form.get("quantity", 0, type=int)
            minimum = request.form.get("minimum_quantity", 0, type=int)
            setting = AppSetting.query.filter_by(key="currency").first()
            currency = setting.value if setting and setting.value in {"IDR", "USD"} else "IDR"
            unit_cost = _amount(request.form.get("unit_cost"), currency)
            selling_price = _amount(request.form.get("selling_price"), currency)
            sku = request.form.get("sku", "").strip() or None
            if not name or len(name) > 180 or quantity is None or quantity < 0 or minimum is None or minimum < 0 or unit_cost is None or selling_price is None:
                flash("Provide a valid item name, non-negative integer quantities, and valid non-negative prices.", "danger")
            elif sku and InventoryItem.query.filter_by(sku=sku).first():
                flash("That SKU is already in use.", "danger")
            else:
                item = InventoryItem(sku=sku, name=name, category=request.form.get("category", "Other"), brand=request.form.get("brand", "").strip(), model=request.form.get("model", "").strip(), quantity=quantity, minimum_quantity=minimum, unit_cost=unit_cost, selling_price=selling_price, supplier=request.form.get("supplier", "").strip(), location=request.form.get("location", "").strip(), description=request.form.get("description", "").strip())
                db.session.add(item)
                db.session.flush()
                audit("create", "inventory_item", item.id)
                if quantity:
                    db.session.add(InventoryMovement(item_id=item.id, user_id=current_user.id, movement_type="STOCK_IN", quantity=quantity, reference="opening stock"))
                db.session.commit()
                flash("Inventory item created.", "success")
                return redirect(url_for("operations.inventory"))
    return render_template("inventory.html", items=InventoryItem.query.order_by(InventoryItem.name).all(), movements=InventoryMovement.query.order_by(InventoryMovement.created_at.desc()).limit(100).all())


@operations.route("/scanner", methods=["GET", "POST"])
@login_required
def scanner():
    devices = []
    selected = None
    error = None
    pending_scan = PendingDeviceScan.query.filter_by(user_id=current_user.id).order_by(PendingDeviceScan.created_at.desc()).first()
    scanned = json.loads(pending_scan.properties_json) if pending_scan else None
    if request.method == "POST" and request.form.get("action") == "scan":
        try:
            devices = scan_devices()
            session["phonebench_adb_devices"] = devices
            if not devices:
                flash("ADB is ready, but no authorized Android device is connected.", "info")
        except (ADBUnavailable, RuntimeError) as exc:
            error = str(exc)
    elif request.method == "POST" and request.form.get("action") == "read":
        serial = request.form.get("serial", "")
        known_devices = session.get("phonebench_adb_devices", [])
        if serial not in known_devices or not re.fullmatch(r"[A-Za-z0-9._:-]{1,100}", serial):
            abort(400)
        try:
            scanned = read_properties(serial)
            if pending_scan:
                pending_scan.serial = serial
                pending_scan.properties_json = json.dumps(scanned)
            else:
                pending_scan = PendingDeviceScan(user_id=current_user.id, serial=serial, properties_json=json.dumps(scanned))
                db.session.add(pending_scan)
            db.session.commit()
        except (ADBUnavailable, RuntimeError) as exc:
            error = str(exc)
    elif request.method == "POST" and request.form.get("action") == "import":
        pending_scan = PendingDeviceScan.query.filter_by(user_id=current_user.id).order_by(PendingDeviceScan.created_at.desc()).first()
        scanned = json.loads(pending_scan.properties_json) if pending_scan else None
        if not scanned:
            abort(400)
        device = Device(
            brand=request.form.get("brand", "").strip() or scanned.get("brand") or scanned.get("manufacturer") or "Unknown",
            model=request.form.get("model", "").strip() or scanned.get("model") or "Unknown",
            marketing_name=request.form.get("marketing_name", "").strip(),
            device_code=scanned.get("device", ""), board=scanned.get("board", ""), hardware=scanned.get("hardware", ""),
            android_version=scanned.get("android_version", ""), android_build=scanned.get("build", ""),
            security_patch=scanned.get("security_patch", ""),
        )
        db.session.add(device)
        db.session.flush()
        db.session.add(DeviceIdentifier(device_id=device.id, type="Serial", value=scanned["serial"], source="ADB", verified=True))
        db.session.add(DeviceIdentifier(device_id=device.id, type="Build fingerprint", value=scanned.get("fingerprint", ""), source="ADB", verified=True))
        for property_name, property_value in scanned.get("properties", {}).items():
            db.session.add(DeviceProperty(device_id=device.id, property_name=property_name, property_value=property_value, source="ADB"))
        audit("adb_import", "device", device.id)
        db.session.delete(pending_scan)
        db.session.commit()
        flash("Device identification imported, including raw ADB properties.", "success")
        return redirect(url_for("core.device_detail", device_id=device.id))
    devices = devices or session.get("phonebench_adb_devices", [])
    return render_template("scanner.html", devices=devices, scanned=scanned, error=error)


@operations.route("/ai", methods=["GET", "POST"])
@login_required
@permission_required("knowledge.read")
def ai_assistant():
    if request.method == "POST":
        prompt = request.form.get("question", "").strip()
        if not prompt or len(prompt) > 2000:
            flash("Enter a question of at most 2,000 characters.", "danger")
            return redirect(url_for("operations.ai_assistant"))
        stopwords = {"what", "have", "been", "done", "for", "the", "with", "previously", "about", "how", "does", "did", "can", "you", "find", "my"}
        terms = [word for word in re.findall(r"[A-Za-z0-9._-]{2,}", prompt) if word.lower() not in stopwords][:10]
        solution_fields = [Solution.device_model, Solution.title, Solution.problem, Solution.symptoms, Solution.solution, Solution.tool, Solution.firmware]
        attempt_fields = [RepairAttempt.tool, RepairAttempt.firmware, RepairAttempt.method, RepairAttempt.procedure, RepairAttempt.command_or_output, RepairAttempt.error_message, RepairAttempt.notes]
        evidence_filter = or_(*(field.ilike(f"%{word}%") for word in terms for field in solution_fields)) if terms else False
        attempt_filter = or_(*(field.ilike(f"%{word}%") for word in terms for field in attempt_fields)) if terms else False
        evidence_rows = Solution.query.filter(evidence_filter).order_by(Solution.verified.desc(), Solution.success_count.desc()).limit(8).all()
        attempt_rows = RepairAttempt.query.filter(attempt_filter).order_by(case((RepairAttempt.result == "SUCCESS", 0), else_=1), RepairAttempt.created_at.desc()).limit(8).all()
        evidence_parts = [
            f"[{ 'TECHNICIAN VERIFIED' if row.verified else 'UNVERIFIED HISTORICAL CASE' }] {row.device_model}: {row.problem or row.title}; solution={row.solution}; tool={row.tool or 'not recorded'}; firmware={row.firmware or 'not recorded'}; success count={row.success_count}; failures={row.failure_count}; source ticket={row.source_repair.ticket_number}"
            for row in evidence_rows
        ]
        evidence_parts.extend(
            f"[HISTORICAL ATTEMPT: {row.result}] {row.repair.device.device_code or row.repair.device.model}: {row.repair.customer_problem}; method={row.method or 'not recorded'}; tool={row.tool or 'not recorded'}; firmware={row.firmware or 'not recorded'}; error={row.error_message or 'none recorded'}; source ticket={row.repair.ticket_number}"
            for row in attempt_rows
        )
        evidence = "\n".join(evidence_parts)
        answer = None
        error = None
        if evidence and current_app.config.get("AI_BASE_URL") and current_app.config.get("AI_API_KEY") and current_app.config.get("AI_MODEL"):
            provider = OpenAICompatibleProvider(current_app.config["AI_BASE_URL"], current_app.config["AI_API_KEY"], current_app.config["AI_MODEL"])
            try:
                answer = provider.generate(prompt, evidence)
            except AIProviderError as exc:
                error = str(exc)
        elif not evidence:
            error = "No relevant PhoneBench history matched this question, so the AI provider was not called. Record diagnoses and repair attempts to build evidence."
        else:
            error = "AI provider is not configured. Historical database evidence is shown below; set PHONEBENCH_AI_BASE_URL, PHONEBENCH_AI_API_KEY, and PHONEBENCH_AI_MODEL locally to enable interpretation."
        configured = bool(current_app.config.get("AI_BASE_URL") and current_app.config.get("AI_API_KEY") and current_app.config.get("AI_MODEL"))
        return render_template("ai.html", configured=configured, question=prompt, evidence_rows=evidence_rows, attempt_rows=attempt_rows, answer=answer, error=error)
    configured = bool(current_app.config.get("AI_BASE_URL") and current_app.config.get("AI_API_KEY") and current_app.config.get("AI_MODEL"))
    return render_template("ai.html", configured=configured)


@operations.route("/reports")
@login_required
def reports():
    _owner_only()
    monthly_totals = {}
    for entry in Transaction.query.order_by(Transaction.date.desc()).limit(10000).all():
        key = (entry.date.strftime("%Y-%m"), entry.type)
        monthly_totals[key] = monthly_totals.get(key, 0) + float(entry.amount)
    monthly = [(month, kind, amount) for (month, kind), amount in sorted(monthly_totals.items(), reverse=True)[:24]]
    model_counts = db.session.query(Device.brand, Device.model, func.count(Repair.id)).join(Repair, Repair.device_id == Device.id).group_by(Device.brand, Device.model).order_by(func.count(Repair.id).desc()).limit(15).all()
    problem_counts = db.session.query(Diagnosis.problem_category, func.count(Diagnosis.id)).group_by(Diagnosis.problem_category).order_by(func.count(Diagnosis.id).desc()).limit(15).all()
    attempts = RepairAttempt.query.all()
    errors = Counter(attempt.error_message.strip() for attempt in attempts if attempt.error_message.strip())
    tools = Counter(attempt.tool for attempt in attempts if attempt.tool)
    successful = [attempt for attempt in attempts if attempt.result == "SUCCESS"]
    success_rate = (len(successful) / len(attempts) * 100) if attempts else 0
    firmware = Counter(attempt.firmware for attempt in successful if attempt.firmware).most_common(10)
    solutions = Solution.query.order_by(Solution.success_count.desc()).limit(15).all()
    workload = db.session.query(User.display_name, func.count(Repair.id)).outerjoin(Repair, Repair.assigned_technician_id == User.id).group_by(User.id).order_by(func.count(Repair.id).desc()).all()
    revenue_by_service = db.session.query(Transaction.category, func.sum(Transaction.amount)).filter(Transaction.type == "INCOME").group_by(Transaction.category).order_by(func.sum(Transaction.amount).desc()).all()
    net_collected = func.sum(case((Payment.kind == "REFUND", -Payment.amount), else_=Payment.amount))
    revenue_by_technician = db.session.query(User.display_name, net_collected).join(Repair, Repair.assigned_technician_id == User.id).join(Invoice, Invoice.repair_id == Repair.id).join(Payment, Payment.invoice_id == Invoice.id).group_by(User.id).order_by(net_collected.desc()).all()
    return render_template("reports.html", monthly=monthly, model_counts=model_counts, problem_counts=problem_counts, errors=errors.most_common(10), tools=tools.most_common(10), solutions=solutions, workload=workload, success_rate=success_rate, failed_attempts=sum(attempt.result == "FAILED" for attempt in attempts), firmware=firmware, revenue_by_service=revenue_by_service, revenue_by_technician=revenue_by_technician)


@operations.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    _owner_only()
    if request.method == "POST":
        if request.form.get("action") == "set_currency":
            currency = request.form.get("currency", "")
            if currency not in {"IDR", "USD"}:
                flash("Choose a supported currency.", "danger")
            else:
                row = AppSetting.query.filter_by(key="currency").first()
                if not row:
                    row = AppSetting(key="currency", value=currency)
                    db.session.add(row)
                else:
                    row.value = currency
                audit("update", "settings", new_value=f"currency={currency}")
                db.session.commit()
                flash("Display currency updated. Existing amounts are not converted.", "success")
            return redirect(url_for("operations.settings"))
        allowed_placeholders = {"customer_name", "device_name", "ticket_number", "status", "public_note"}
        submitted = {
            event: request.form.get(f"template_{event}", "").strip()
            for event in ["repair_received", "diagnosis_update", "waiting_approval", "repair_completed", "invoice_generated", "payment_received", "ready_pickup"]
        }
        invalid_templates = []
        for event, template in submitted.items():
            placeholders = set(re.findall(r"{{\s*([A-Za-z_][A-Za-z0-9_]*)\s*}}", template))
            unmatched_braces = re.sub(r"{{\s*[A-Za-z_][A-Za-z0-9_]*\s*}}", "", template)
            if len(template) > 4000 or placeholders - allowed_placeholders or "{{" in unmatched_braces or "}}" in unmatched_braces:
                invalid_templates.append(event)
        if invalid_templates:
            flash("Templates must be at most 4,000 characters and use only the documented placeholders. No templates were saved.", "danger")
            templates = {row.event: row.template for row in NotificationTemplate.query.all()}
            ai_configured = bool(current_app.config.get("AI_BASE_URL") and current_app.config.get("AI_API_KEY") and current_app.config.get("AI_MODEL"))
            whatsapp_configured = bool(current_app.config.get("WHATSAPP_TOKEN") and current_app.config.get("WHATSAPP_PHONE_NUMBER_ID"))
            currency_setting = AppSetting.query.filter_by(key="currency").first()
            currency = currency_setting.value if currency_setting and currency_setting.value in {"IDR", "USD"} else "IDR"
            return render_template("settings.html", templates=templates, ai_configured=ai_configured, whatsapp_configured=whatsapp_configured, upload_path=current_app.config["UPLOAD_FOLDER"], currency=currency)
        for event, template in submitted.items():
            if template:
                row = NotificationTemplate.query.filter_by(event=event).first()
                if not row:
                    row = NotificationTemplate(event=event, template=template)
                    db.session.add(row)
                else:
                    row.template = template
        audit("update", "settings", new_value="notification_templates")
        db.session.commit()
        flash("Notification templates saved.", "success")
    templates = {row.event: row.template for row in NotificationTemplate.query.all()}
    ai_configured = bool(current_app.config.get("AI_BASE_URL") and current_app.config.get("AI_API_KEY") and current_app.config.get("AI_MODEL"))
    whatsapp_configured = bool(current_app.config.get("WHATSAPP_TOKEN") and current_app.config.get("WHATSAPP_PHONE_NUMBER_ID"))
    currency_setting = AppSetting.query.filter_by(key="currency").first()
    currency = currency_setting.value if currency_setting and currency_setting.value in {"IDR", "USD"} else "IDR"
    return render_template("settings.html", templates=templates, ai_configured=ai_configured, whatsapp_configured=whatsapp_configured, upload_path=current_app.config["UPLOAD_FOLDER"], currency=currency)


@operations.route("/audit")
@login_required
def audit_log():
    _owner_only()
    return render_template("audit.html", entries=AuditLog.query.order_by(AuditLog.timestamp.desc()).limit(300).all())


@operations.route("/backups", methods=["GET", "POST"])
@login_required
def backups():
    _owner_only()
    if request.method == "POST" and request.form.get("action") == "create":
        try:
            created = create_database_backup()
            flash(f"Backup created: {created['database']}" + (f" and {created['attachments']}" if created["attachments"] else ""), "success")
        except (OSError, RuntimeError) as exc:
            flash(f"Backup failed: {exc}", "danger")
        return redirect(url_for("operations.backups"))
    if request.method == "POST" and request.form.get("action") == "restore":
        uploaded = request.files.get("backup")
        if not uploaded:
            flash("Select a database backup.", "danger")
        else:
            try:
                restore_database(uploaded)
                flash("Database restored. The previous database was preserved beside it.", "success")
            except (OSError, RuntimeError, ValueError) as exc:
                flash(f"Restore failed: {exc}", "danger")
        return redirect(url_for("operations.backups"))
    if request.method == "POST" and request.form.get("action") == "restore-attachments":
        uploaded = request.files.get("attachments")
        if not uploaded:
            flash("Select an attachments ZIP backup.", "danger")
        else:
            try:
                restore_attachments(uploaded)
                flash("Attachments restored. The previous uploads folder was preserved.", "success")
            except (OSError, RuntimeError, ValueError) as exc:
                flash(f"Attachment restore failed: {exc}", "danger")
        return redirect(url_for("operations.backups"))
    os.makedirs(current_app.config["BACKUP_FOLDER"], exist_ok=True)
    files = sorted(os.listdir(current_app.config["BACKUP_FOLDER"]), reverse=True)
    return render_template("backups.html", files=files)


@operations.get("/backups/<path:filename>")
@login_required
def backup_download(filename):
    _owner_only()
    safe_name = secure_filename(filename)
    if safe_name != filename:
        abort(404)
    return send_file(os.path.join(current_app.config["BACKUP_FOLDER"], safe_name), as_attachment=True)


@operations.get("/exports/json")
@login_required
def export_json():
    _owner_only()
    return current_app.response_class(export_records(), mimetype="application/json", headers={"Content-Disposition": "attachment; filename=phonebench-export.json"})


@operations.get("/exports/<kind>.csv")
@login_required
def export_csv(kind):
    _owner_only()
    if kind not in {"repairs", "knowledge", "inventory"}:
        abort(404)
    output = io.StringIO()
    writer = csv.writer(output)
    if kind == "repairs":
        writer.writerow(["ticket_number", "customer_id", "device_id", "status", "problem", "received_at"])
        for row in Repair.query.order_by(Repair.created_at.desc()).all():
            writer.writerow([row.ticket_number, row.customer_id, row.device_id, row.status, row.customer_problem, row.received_at.isoformat()])
    elif kind == "knowledge":
        writer.writerow(["title", "device_model", "problem", "solution", "tool", "firmware", "verified", "success_count", "failure_count", "source_ticket"])
        for row in Solution.query.order_by(Solution.created_at.desc()).all():
            writer.writerow([row.title, row.device_model, row.problem, row.solution, row.tool, row.firmware, row.verified, row.success_count, row.failure_count, row.source_repair.ticket_number])
    else:
        writer.writerow(["sku", "name", "category", "quantity", "minimum_quantity", "unit_cost", "selling_price", "location"])
        for row in InventoryItem.query.order_by(InventoryItem.name).all():
            writer.writerow([row.sku, row.name, row.category, row.quantity, row.minimum_quantity, row.unit_cost, row.selling_price, row.location])
    return current_app.response_class(output.getvalue(), mimetype="text/csv", headers={"Content-Disposition": f"attachment; filename=phonebench-{kind}.csv"})


@operations.post("/repairs/<int:repair_id>/whatsapp")
@login_required
def whatsapp_notify(repair_id):
    if current_user.role not in {"OWNER", "ADMIN", "RECEPTIONIST"}:
        abort(403)
    from ..services.whatsapp import CloudAPIProvider, WhatsAppProviderError
    repair = db.get_or_404(Repair, repair_id)
    event = request.form.get("event", "")
    template = NotificationTemplate.query.filter_by(event=event, enabled=True).first()
    if not template:
        flash("No enabled template is configured for this update.", "warning")
        return redirect(url_for("repairs.repair_detail", repair_id=repair.id))
    if not repair.customer.phone:
        flash("This customer has no phone number on file.", "danger")
        return redirect(url_for("repairs.repair_detail", repair_id=repair.id))
    if not current_app.config.get("WHATSAPP_TOKEN") or not current_app.config.get("WHATSAPP_PHONE_NUMBER_ID"):
        flash("WhatsApp is not configured. Set PHONEBENCH_WHATSAPP_TOKEN and PHONEBENCH_WHATSAPP_PHONE_NUMBER_ID in the local environment.", "warning")
        return redirect(url_for("repairs.repair_detail", repair_id=repair.id))
    replacements = {
        "customer_name": repair.customer.name,
        "device_name": f"{repair.device.brand} {repair.device.model}",
        "ticket_number": repair.ticket_number,
        "status": repair.status.replace("_", " ").title(),
        "public_note": repair.public_notes or "No additional public note.",
    }
    message = template.template
    for key, value in replacements.items():
        message = message.replace("{{" + key + "}}", value)
    try:
        provider = CloudAPIProvider(current_app.config["WHATSAPP_TOKEN"], current_app.config["WHATSAPP_PHONE_NUMBER_ID"], current_app.config["WHATSAPP_API_VERSION"])
        result = provider.send_message(repair.customer.phone, message)
    except WhatsAppProviderError as exc:
        flash(f"WhatsApp send failed: {exc}", "danger")
        return redirect(url_for("repairs.repair_detail", repair_id=repair.id))
    audit("whatsapp_sent", "repair", repair.id, new_value=event)
    result_messages = result.get("messages", []) if isinstance(result, dict) else []
    db.session.add(CustomerMessage(
        customer_id=repair.customer_id, repair_id=repair.id, channel="WHATSAPP",
        direction="OUTBOUND", event=event, body=message, status="SENT",
        provider_reference=(result_messages[0].get("id") if result_messages else None),
    ))
    db.session.commit()
    flash("WhatsApp update sent.", "success")
    return redirect(url_for("repairs.repair_detail", repair_id=repair.id))
