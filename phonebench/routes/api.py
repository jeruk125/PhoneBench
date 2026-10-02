from flask import Blueprint, abort, jsonify, request
from flask_login import current_user, login_required
from sqlalchemy import or_

from ..extensions import db
from ..models import Repair, Solution
from ..security import ROLE_PERMISSIONS

api = Blueprint("api", __name__, url_prefix="/api/v1")


@api.get("/health")
def health():
    return jsonify({"status": "ok", "service": "PhoneBench"})


@api.get("/repairs")
@login_required
def repair_list():
    query = Repair.query
    if current_user.role == "TECHNICIAN":
        query = query.filter_by(assigned_technician_id=current_user.id)
    status = request.args.get("status")
    if status:
        query = query.filter_by(status=status)
    results = query.order_by(Repair.created_at.desc()).limit(100).all()
    return jsonify([{
        "id": repair.id,
        "ticket_number": repair.ticket_number,
        "customer_id": repair.customer_id,
        "device_id": repair.device_id,
        "device": f"{repair.device.brand} {repair.device.model}",
        "customer_problem": repair.customer_problem,
        "status": repair.status,
        "received_at": repair.received_at.isoformat(),
    } for repair in results])


@api.get("/repairs/<int:repair_id>")
@login_required
def repair_detail(repair_id):
    repair = db.get_or_404(Repair, repair_id)
    if current_user.role == "TECHNICIAN" and repair.assigned_technician_id != current_user.id:
        abort(403)
    return jsonify({
        "id": repair.id,
        "ticket_number": repair.ticket_number,
        "status": repair.status,
        "customer_problem": repair.customer_problem,
        "initial_condition": repair.initial_condition,
        "device": {"brand": repair.device.brand, "model": repair.device.model, "device_code": repair.device.device_code},
        "diagnoses": [{"category": row.problem_category, "diagnosis": row.diagnosis, "confidence": row.confidence} for row in repair.diagnoses],
        "attempts": [{
            "attempt_number": row.attempt_number, "tool": row.tool, "firmware": row.firmware,
            "method": row.method, "result": row.result, "error_message": row.error_message,
        } for row in repair.attempts],
    })


@api.get("/knowledge")
@login_required
def knowledge_search():
    permissions = ROLE_PERMISSIONS.get(current_user.role, set())
    if "*" not in permissions and "knowledge.read" not in permissions:
        abort(403)
    term = request.args.get("q", "").strip()
    if not term:
        return jsonify({"error": "A non-empty q parameter is required."}), 400
    pattern = f"%{term}%"
    rows = Solution.query.filter(or_(
        Solution.device_model.ilike(pattern), Solution.title.ilike(pattern),
        Solution.problem.ilike(pattern), Solution.symptoms.ilike(pattern),
        Solution.solution.ilike(pattern), Solution.tool.ilike(pattern),
        Solution.firmware.ilike(pattern),
    )).order_by(Solution.verified.desc(), Solution.success_count.desc()).limit(25).all()
    return jsonify([{
        "id": row.id, "title": row.title, "device_model": row.device_model,
        "problem": row.problem, "solution": row.solution, "tool": row.tool,
        "firmware": row.firmware, "verified": row.verified,
        "success_count": row.success_count, "failure_count": row.failure_count,
        "source_ticket": row.source_repair.ticket_number,
        "evidence_label": "TECHNICIAN VERIFIED" if row.verified else "UNVERIFIED HISTORICAL CASE",
    } for row in rows])
