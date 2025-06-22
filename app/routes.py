from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, date, timedelta
from sqlalchemy import desc
import io, zipfile, requests, random, string

from app import db
from app.utils import generate_and_store_qr_batch
from app.decorators import subuser_required
from app.models import (
    User, QRBatch, QRCode, Machine, QRTag,
    NeedleChange, ServiceLog, SubUser,
    SubUserAction, DailyMaintenance, ServiceRequest
)

routes = Blueprint("routes", __name__)

# ----------------------- PUBLIC / AUTH -----------------------

@routes.route("/")
def home():
    return render_template("index.html")

@routes.route("/signup", methods=["GET", "POST"], endpoint="user_signup")
def user_signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        name = request.form["name"]
        company_name = request.form.get("company_name")
        if User.query.filter_by(email=email).first():
            flash("Email already registered", "danger")
            return redirect(url_for("routes.user_signup"))
        new_user = User(email=email, password=password, name=name, company_name=company_name, role="user")
        db.session.add(new_user)
        db.session.commit()
        flash("Signup successful! Please login.", "success")
        return redirect(url_for("routes.user_login"))
    return render_template("signup.html")

@routes.route("/login", methods=["GET", "POST"], endpoint="user_login")
def user_login():
    next_url = request.args.get('next')
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email, role="user").first()
        if user and user.password == password:
            login_user(user)
            session['show_login_success'] = True
            return redirect(next_url or url_for("routes.user_dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("login.html", next=next_url)

@routes.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("routes.user_login"))

# ----------------------- QR SCANNING -----------------------

@routes.route("/scan/master/<int:batch_id>")
def scan_master(batch_id):
    if not current_user.is_authenticated:
        session['pending_batch_id'] = batch_id
        return redirect(url_for("routes.user_login", next=url_for("routes.claim_batch", batch_id=batch_id)))
    return redirect(url_for("routes.claim_batch", batch_id=batch_id))

@routes.route("/scan/sub/<int:sub_tag_id>")
def scan_sub(sub_tag_id):
    if not current_user.is_authenticated:
        session['pending_sub_tag_id'] = sub_tag_id
        return redirect(url_for("routes.user_login", next=url_for("routes.sub_tag_options", sub_tag_id=sub_tag_id)))
    return redirect(url_for("routes.sub_tag_options", sub_tag_id=sub_tag_id))

@routes.route("/claim/<int:batch_id>")
@login_required
def claim_batch(batch_id):
    if current_user.role != "user":
        flash("Only users can claim batches.", "danger")
        return redirect(url_for("routes.home"))
    batch = QRBatch.query.get(batch_id)
    if not batch:
        flash("Batch not found.", "danger")
        return redirect(url_for("routes.user_dashboard"))
    if batch.owner_id is None:
        batch.owner_id = current_user.id
        db.session.commit()
        flash("Batch successfully claimed!", "success")
    elif batch.owner_id == current_user.id:
        flash("You already claimed this batch.", "info")
    else:
        flash("This batch has already been claimed by another user.", "danger")
    return redirect(url_for("routes.user_dashboard"))

# ----------------------- USER SETTINGS -----------------------

@routes.route("/settings", methods=["GET", "POST"])
@login_required
def user_settings():
    if request.method == "POST":
        current_user.name = request.form.get("name") or current_user.name
        current_user.company_name = request.form.get("company_name") or current_user.company_name
        current_user.mobile = request.form.get("mobile") or current_user.mobile
        new_email = request.form.get("email")
        if new_email and new_email != current_user.email:
            current_user.email = new_email
        password = request.form.get("password")
        if password:
            current_user.password = password  # Hash in prod

        # Machines
        machine_ids = request.form.getlist("machine_ids")
        machine_names = []
        for mid in machine_ids:
            name = request.form.get(f"machine_name_{mid}", "").strip()
            if name.lower() in [n.lower() for n in machine_names]:
                flash(f"Machine name '{name}' is duplicated.", "danger")
                return redirect(url_for("routes.user_settings"))
            machine_names.append(name)

        for mid in machine_ids:
            m = Machine.query.get(int(mid))
            if m and m.batch.owner_id == current_user.id:
                m.name = request.form.get(f"machine_name_{mid}")
                m.type = request.form.get(f"machine_type_{mid}")

        db.session.commit()
        flash("Settings updated.", "success")
        return redirect(url_for("routes.user_settings"))

    user_batches = QRBatch.query.filter_by(owner_id=current_user.id).all()
    machines = [Machine.query.filter_by(batch_id=batch.id).first() for batch in user_batches if batch]
    return render_template("user_settings.html", machines=machines)

@routes.route("/user/dashboard", methods=["GET", "POST"])
@login_required
def user_dashboard():
    if current_user.role != "user":
        return redirect(url_for("routes.user_login"))
    show_toast = session.pop('show_login_success', False)

    if request.method == "POST":
        batch_id = request.form.get("batch_id")
        name = request.form.get("name") or "Unnamed Machine"
        mtype = request.form.get("type") or "General"
        existing = Machine.query.filter_by(batch_id=batch_id).first()
        if existing:
            existing.name = name
            existing.type = mtype
        else:
            db.session.add(Machine(batch_id=batch_id, name=name, type=mtype))
        db.session.commit()

    batches = QRBatch.query.filter_by(owner_id=current_user.id).all()
    batch_data = []
    for batch in batches:
        machine = Machine.query.filter_by(batch_id=batch.id).first()
        tags = QRTag.query.filter_by(batch_id=batch.id).all()
        subusers = SubUser.query.filter_by(assigned_machine_id=machine.id).all() if machine else []
        qr_codes = QRCode.query.filter_by(batch_id=batch.id).all()
        batch_data.append({"id": batch.id, "created_at": batch.created_at, "machine": machine, "tags": tags, "subusers": subusers, "qr_codes": qr_codes})

    return render_template("user_dashboard.html", batches=batch_data, show_toast=show_toast, now=datetime.utcnow(), timedelta=timedelta)

# ----------------------- ADMIN DASHBOARD -----------------------

@routes.route("/admin/login", methods=["GET", "POST"], endpoint="admin_login")
def admin_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email, role="admin").first()
        if user and user.password == password:
            login_user(user)
            return redirect(url_for("routes.admin_dashboard"))
        flash("Invalid credentials", "danger")
    return render_template("admin_login.html")

@routes.route("/admin/dashboard")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        return redirect(url_for("routes.admin_login"))
    batches = QRBatch.query.order_by(QRBatch.created_at.desc()).all()
    for batch in batches:
        batch.qrcodes = QRCode.query.filter_by(batch_id=batch.id).all()
        batch.user = User.query.filter_by(id=batch.owner_id).first()
        batch.machine = Machine.query.filter_by(batch_id=batch.id).first()
    return render_template("admin_dashboard.html", batches=batches, total_batches=len(batches), total_qrcodes=QRCode.query.count())

@routes.route("/admin/create-batch")
@login_required
def create_batch():
    if current_user.role != "admin":
        return redirect(url_for("routes.admin_login"))
    generate_and_store_qr_batch()
    return redirect(url_for("routes.admin_dashboard"))

@routes.route("/admin/download-batch/<int:batch_id>")
@login_required
def download_batch(batch_id):
    if current_user.role != "admin":
        return redirect(url_for("routes.admin_login"))
    qrcodes = QRCode.query.filter_by(batch_id=batch_id).all()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as z:
        for qr in qrcodes:
            response = requests.get(qr.image_url)
            z.writestr(f"{qr.qr_type}.png", response.content)
    zip_buffer.seek(0)
    return send_file(zip_buffer, mimetype="application/zip", as_attachment=True, download_name=f"batch_{batch_id}.zip")

# ----------------------- SUB-USER -----------------------

@routes.route("/subuser/login", methods=["GET", "POST"])
def subuser_login():
    if request.method == "POST":
        code = request.form.get("subuser_code")
        sub = SubUser.query.filter_by(static_id=code).first()
        if sub:
            session['subuser_id'] = sub.id
            return redirect(url_for("routes.subuser_dashboard"))
        flash("Invalid code", "danger")
    return render_template("subuser_login.html")

@routes.route("/subuser/logout")
def subuser_logout():
    session.pop('subuser_id', None)
    flash("Sub-user logged out.", "info")
    return redirect(url_for("routes.subuser_login"))

@routes.route("/subuser/dashboard")
@subuser_required
def subuser_dashboard():
    sub_id = session.get('subuser_id')
    sub = SubUser.query.get_or_404(sub_id)
    machine = Machine.query.get_or_404(sub.assigned_machine_id)
    batch = QRBatch.query.get_or_404(machine.batch_id)
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())

    # ✅ Check if today's oiling and this week's lube are done
    oil_done = SubUserAction.query.filter_by(
        subuser_id=sub.id,
        machine_id=machine.id,
        action_type="oil",
        status="done"
    ).filter(db.func.date(SubUserAction.timestamp) == today).first() is not None

    lube_done = SubUserAction.query.filter_by(
        subuser_id=sub.id,
        machine_id=machine.id,
        action_type="lube",
        status="done"
    ).filter(SubUserAction.timestamp >= start_of_week).first() is not None

    # ✅ Get latest timestamps
    last_oil = SubUserAction.query.filter_by(
        subuser_id=sub.id,
        machine_id=machine.id,
        action_type="oil",
        status="done"
    ).order_by(SubUserAction.timestamp.desc()).first()

    last_lube = SubUserAction.query.filter_by(
        subuser_id=sub.id,
        machine_id=machine.id,
        action_type="lube",
        status="done"
    ).order_by(SubUserAction.timestamp.desc()).first()

    # ✅ Alerts (overdue)
    oil_alert = True
    if last_oil and (datetime.utcnow() - last_oil.timestamp).total_seconds() < 86400:
        oil_alert = False

    lube_alert = True
    if last_lube and (datetime.utcnow() - last_lube.timestamp).days < 6:
        lube_alert = False

    return render_template(
        "subuser_dashboard.html",
        subuser=sub,
        machine=machine,
        batch=batch,
        qr_codes=QRCode.query.filter_by(batch_id=batch.id).all(),
        tags=QRTag.query.filter_by(batch_id=batch.id).all(),
        oil_done=oil_done,
        lube_done=lube_done,
        last_oil_time=last_oil.timestamp if last_oil else None,
        last_lube_time=last_lube.timestamp if last_lube else None,
        oil_alert=oil_alert,
        lube_alert=lube_alert
    )

@routes.route("/subuser/action/<string:type>", methods=["POST"])
@subuser_required
def subuser_action(type):
    sub_id = session.get("subuser_id")
    sub = SubUser.query.get(sub_id)
    machine = Machine.query.get(sub.assigned_machine_id)
    today = date.today()

    if type == "oil":
        if not SubUserAction.query.filter_by(subuser_id=sub.id, machine_id=machine.id, action_type="oil", status="done").filter(db.func.date(SubUserAction.timestamp) == today).first():
            db.session.add(SubUserAction(subuser_id=sub.id, machine_id=machine.id, action_type="oil", status="done"))
            db.session.add(DailyMaintenance(machine_id=machine.id, date=today, oiled=True))
        flash("Marked as oiled for today!", "success")
    elif type == "lube":
        db.session.add(SubUserAction(subuser_id=sub.id, machine_id=machine.id, action_type="lube", status="done"))
        flash("Lube completed!", "success")
    elif type == "service":
        heads = request.form.get("heads")
        issue = request.form.get("message")
        db.session.add(ServiceRequest(machine_id=machine.id, subuser_id=sub.id, heads=int(heads), issue=issue))
        flash("Service request sent!", "success")
    db.session.commit()
    return redirect(url_for("routes.subuser_dashboard"))

