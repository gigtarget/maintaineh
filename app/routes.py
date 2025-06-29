from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, date, timedelta
from sqlalchemy import func
import io
import zipfile
import requests
import random
import string

from app import db
from app.utils import generate_and_store_qr_batch
from app.decorators import subuser_required, user_or_subuser_required   # <-- CHANGED
from app.models import (
    User, QRBatch, QRCode, Machine, QRTag,
    NeedleChange, ServiceLog, SubUser,
    SubUserAction, DailyMaintenance, ServiceRequest
)

routes = Blueprint("routes", __name__)

@routes.route("/")
def home():
    return render_template("index.html")
@routes.route("/scan/master/<int:batch_id>")
def scan_master(batch_id):
    # If a sub-user is logged in, go to sub-user dashboard
    if 'subuser_id' in session:
        return redirect(url_for("routes.subuser_dashboard"))
    # If not logged in as a user, redirect to user login and claim flow
    if not current_user.is_authenticated:
        session['pending_batch_id'] = batch_id
        return redirect(url_for("routes.user_login", next=url_for("routes.claim_batch", batch_id=batch_id)))
    # Otherwise, main user is logged in: proceed to claim batch
    return redirect(url_for("routes.claim_batch", batch_id=batch_id))

@routes.route("/scan/sub/<int:sub_tag_id>")
def scan_sub(sub_tag_id):
    # Publicly redirect anyone (logged in or not) to the sub options page
    return redirect(url_for("routes.sub_tag_options", sub_tag_id=sub_tag_id))

@routes.route("/sub/<int:sub_tag_id>/choose")
def sub_tag_options(sub_tag_id):
    sub_tag = QRTag.query.get_or_404(sub_tag_id)
    # Set correct back_url based on login type
    if hasattr(current_user, "is_authenticated") and current_user.is_authenticated and getattr(current_user, "role", None) == "user":
        back_url = url_for('routes.user_dashboard')
    elif 'subuser_id' in session:
        back_url = url_for('routes.subuser_dashboard')
    else:
        back_url = url_for('routes.home')
    return render_template("sub_options.html", sub_tag=sub_tag, back_url=back_url)


@routes.route("/sub/<int:sub_tag_id>/needle-change", methods=["GET", "POST"])
def sub_tag_view(sub_tag_id):
    sub_tag = QRTag.query.get_or_404(sub_tag_id)
    # --- Permission check REMOVED: all subusers can access all heads ---

    if not sub_tag.tag_type.startswith("sub"):
        flash("Invalid QR Tag. Only Sub QR tags represent machine heads.", "danger")
        if hasattr(current_user, "is_authenticated") and current_user.is_authenticated and getattr(current_user, "role", None) == "user":
            return redirect(url_for("routes.user_dashboard"))
        elif 'subuser_id' in session:
            return redirect(url_for("routes.subuser_dashboard"))
        return redirect(url_for("routes.home"))

    if request.method == "POST":
        needle_number = int(request.form["needle_number"])
        needle_type = int(request.form["needle_type"])

        change = NeedleChange(
            batch_id=sub_tag.batch.id,
            sub_tag_id=sub_tag.id,
            needle_number=needle_number,
            needle_type=needle_type,
            timestamp=datetime.utcnow()
        )
        db.session.add(change)
        db.session.commit()
        flash(f"Needle #{needle_number} updated successfully!", "success")
        return redirect(url_for("routes.sub_tag_view", sub_tag_id=sub_tag_id))

    logs = NeedleChange.query.filter_by(sub_tag_id=sub_tag.id).order_by(NeedleChange.timestamp.desc()).all()
    last_change_dict = {}
    for log in logs:
        if log.needle_number not in last_change_dict:
            last_change_dict[log.needle_number] = log

    # Back URL logic
    if hasattr(current_user, "is_authenticated") and current_user.is_authenticated and getattr(current_user, "role", None) == "user":
        back_url = url_for('routes.user_dashboard')
    elif 'subuser_id' in session:
        back_url = url_for('routes.subuser_dashboard')
    else:
        back_url = url_for('routes.home')

    return render_template(
        "sub_tag_view.html",
        sub_tag=sub_tag,
        last_change_dict=last_change_dict,
        now=datetime.utcnow(),
        back_url=back_url
    )

@routes.route("/sub/<int:sub_tag_id>/service-log", methods=["GET", "POST"])
def sub_tag_service_log(sub_tag_id):
    from datetime import datetime

    sub_tag = QRTag.query.get_or_404(sub_tag_id)
    batch_id = sub_tag.batch.id

    # Allow both "sub" and "service" tag types for service logging
    if not (sub_tag.tag_type.startswith("sub") or sub_tag.tag_type.startswith("service")):
        flash("Invalid QR Tag for service logging.", "danger")
        if current_user.is_authenticated and getattr(current_user, "role", None) == "user":
            return redirect(url_for("routes.user_dashboard"))
        elif 'subuser_id' in session:
            return redirect(url_for("routes.subuser_dashboard"))
        return redirect(url_for("routes.home"))

    # Find main service tag and all heads (sub tags) for this batch
    service_tag = QRTag.query.filter_by(batch_id=batch_id, tag_type='service').first()
    sub_tags = QRTag.query.filter(QRTag.batch_id == batch_id, QRTag.tag_type.startswith('sub')).all()

    if request.method == "POST":
        selected_tag_id = int(request.form.get("belongs_to"))
        part_name = request.form.get("part_name")
        description = request.form.get("description")
        warranty_str = request.form.get("warranty_till")

        warranty_till = None
        if warranty_str:
            try:
                warranty_till = datetime.strptime(warranty_str, "%Y-%m-%d").date()
                if warranty_till < datetime.utcnow().date():
                    flash("Warranty date cannot be in the past.", "danger")
                    return redirect(url_for("routes.sub_tag_service_log", sub_tag_id=sub_tag_id))
            except ValueError:
                flash("Invalid date format.", "danger")
                return redirect(url_for("routes.sub_tag_service_log", sub_tag_id=sub_tag_id))

        log = ServiceLog(
            batch_id=batch_id,
            sub_tag_id=selected_tag_id,  # <-- user's selection
            part_name=part_name,
            description=description,
            warranty_till=warranty_till,
            timestamp=datetime.utcnow()
        )
        db.session.add(log)
        db.session.commit()
        flash(f"Logged replacement for '{part_name}' successfully!", "success")
        return redirect(url_for("routes.sub_tag_service_log", sub_tag_id=sub_tag_id))

    # Logs for all tags (machine and heads) for this batch
    all_tags = [service_tag] + list(sub_tags) if service_tag else list(sub_tags)
    all_tag_ids = [t.id for t in all_tags]
    all_logs = (
        ServiceLog.query
        .filter(ServiceLog.sub_tag_id.in_(all_tag_ids))
        .order_by(ServiceLog.timestamp.desc())
        .all()
    )
    # Attach sub_tag for log label
    for log in all_logs:
        if not hasattr(log, "sub_tag") or log.sub_tag is None:
            log.sub_tag = QRTag.query.get(log.sub_tag_id)

    # Back URL logic
    if current_user.is_authenticated and getattr(current_user, "role", None) == "user":
        back_url = url_for('routes.user_dashboard')
    elif 'subuser_id' in session:
        back_url = url_for('routes.subuser_dashboard')
    else:
        back_url = url_for('routes.home')

    return render_template(
        "sub_service_log.html",
        sub_tag=sub_tag,
        service_tag=service_tag,
        sub_tags=sub_tags,
        all_logs=all_logs,
        now=datetime.utcnow(),
        back_url=back_url
    )

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

    if batch.owner_id is not None:
        if batch.owner_id == current_user.id:
            flash("You already claimed this batch.", "info")
        else:
            flash("This batch has already been claimed by another user.", "danger")
    else:
        batch.owner_id = current_user.id
        db.session.commit()
        flash("Batch successfully claimed!", "success")

    return redirect(url_for("routes.user_dashboard"))

@routes.route("/settings", methods=["GET", "POST"])
@login_required
def user_settings():
    if request.method == "POST":
        # --- User Account Fields ---
        name = request.form.get("name")
        company_name = request.form.get("company_name")
        mobile = request.form.get("mobile")
        email = request.form.get("email")
        password = request.form.get("password")

        if name:
            current_user.name = name
        if company_name:
            current_user.company_name = company_name
        if mobile:
            current_user.mobile = mobile
        if email and email != current_user.email:
            current_user.email = email
        if password:
            current_user.password = password  # ⚠️ Hash this in production

        # --- Machine Section ---
        machine_ids = request.form.getlist("machine_ids")
        machine_names = []
        duplicate_found = False

        for mid in machine_ids:
            name = request.form.get(f"machine_name_{mid}", "").strip()
            if name.lower() in [n.lower() for n in machine_names]:
                flash(f"Machine name '{name}' is duplicated. Please use unique names.", "danger")
                duplicate_found = True
                break
            machine_names.append(name)

        if duplicate_found:
            return redirect(url_for("routes.user_settings"))

        for mid in machine_ids:
            name = request.form.get(f"machine_name_{mid}")
            mtype = request.form.get(f"machine_type_{mid}")
            machine = Machine.query.filter_by(id=mid).first()
            if machine and machine.batch.owner_id == current_user.id:
                machine.name = name
                machine.type = mtype

        db.session.commit()
        flash("All settings updated successfully.", "success")
        return redirect(url_for("routes.user_settings"))

    # --- GET: Load machines ---
    user_batches = QRBatch.query.filter_by(owner_id=current_user.id).all()
    machines = []
    for batch in user_batches:
        m = Machine.query.filter_by(batch_id=batch.id).first()
        if m:
            machines.append(m)

    return render_template("user_settings.html", machines=machines)

@routes.route("/signup", methods=["GET", "POST"], endpoint="user_signup")
def user_signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        name = request.form["name"]
        company_name = request.form.get("company_name")

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Email already registered", "danger")
            return redirect(url_for("routes.user_signup"))

        new_user = User(
            email=email,
            password=password,  # In production, hash this!
            name=name,
            company_name=company_name,
            role="user"
        )
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
            session['show_login_success'] = True  # ✅ Trigger login toast
            return redirect(next_url or url_for("routes.user_dashboard"))
        else:
            flash("Invalid credentials", "danger")
    return render_template("login.html", next=next_url)



@routes.route("/user/dashboard", methods=["GET", "POST"])
@login_required
def user_dashboard():
    if current_user.role != "user":
        return redirect(url_for("routes.user_login"))

    show_toast = session.pop('show_login_success', False)

    if request.method == "POST":
        batch_id = request.form.get("batch_id")
        name = request.form.get("name") or current_user.default_machine_name or "Unnamed Machine"
        mtype = request.form.get("type") or current_user.default_machine_location or "General"

        existing = Machine.query.filter_by(batch_id=batch_id).first()
        if existing:
            existing.name = name
            existing.type = mtype
            flash("Machine updated with your preferences.", "success")
        else:
            machine = Machine(batch_id=batch_id, name=name, type=mtype)
            db.session.add(machine)
            flash("Machine added successfully.", "success")
        db.session.commit()

    user_batches = QRBatch.query.filter_by(owner_id=current_user.id).all()
    batch_data = []
    for batch in user_batches:
        machine = Machine.query.filter_by(batch_id=batch.id).first()
        qr_codes = QRCode.query.filter_by(batch_id=batch.id).all()
        tags = QRTag.query.filter_by(batch_id=batch.id).all()
        subusers = SubUser.query.filter_by(assigned_machine_id=machine.id).all() if machine else []
        batch_data.append({
            "id": batch.id,
            "created_at": batch.created_at,
            "machine": machine,
            "qr_codes": qr_codes,
            "tags": tags,
            "subusers": subusers
        })

    machines = Machine.query.join(QRBatch).filter(QRBatch.owner_id == current_user.id).all()
    machines_data = []
    for machine in machines:
        batch = machine.batch
        subusers = SubUser.query.filter_by(assigned_machine_id=machine.id).all()
        qr_tags = QRTag.query.filter_by(batch_id=batch.id).filter(QRTag.tag_type.startswith("sub")).all()

        needle_logs = NeedleChange.query.filter_by(batch_id=batch.id).order_by(NeedleChange.timestamp.desc()).all()
        service_logs = ServiceLog.query.filter_by(batch_id=batch.id).order_by(ServiceLog.timestamp.desc()).all()
        last_service = service_logs[0] if service_logs else None

        warranty_warning = False
        stale_service_warning = False
        maintenance_ok = True
        if last_service and last_service.warranty_till:
            days_left = (last_service.warranty_till - datetime.utcnow().date()).days
            if days_left < 30:
                warranty_warning = True
                maintenance_ok = False
        if last_service and (datetime.utcnow() - last_service.timestamp).days > 60:
            stale_service_warning = True
            maintenance_ok = False

        grouped_logs = {tag.id: {"tag": tag, "needle_logs": [], "service_logs": []} for tag in qr_tags}
        for log in needle_logs:
            if log.sub_tag_id in grouped_logs:
                grouped_logs[log.sub_tag_id]["needle_logs"].append(log)
        for log in service_logs:
            if log.sub_tag_id in grouped_logs:
                grouped_logs[log.sub_tag_id]["service_logs"].append(log)

        machines_data.append({
            "machine": machine,
            "batch": batch,
            "subusers": subusers,
            "last_needle": needle_logs[0] if needle_logs else None,
            "last_service": last_service,
            "grouped_logs": grouped_logs,
            "total_needle_changes": len(needle_logs),
            "total_services_logged": len(service_logs),
            "maintenance_ok": maintenance_ok,
            "warranty_warning": warranty_warning,
            "stale_service_warning": stale_service_warning,
            "qr_codes": QRCode.query.filter_by(batch_id=batch.id).all()
        })

    # Quick Machine Overview with pending request details
    quick_overview = []
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())

    for machine in machines:
        sub = SubUser.query.filter_by(assigned_machine_id=machine.id).first()

        # Oil check
        oiled_today = SubUserAction.query.filter_by(
            subuser_id=sub.id if sub else None,
            machine_id=machine.id,
            action_type="oil",
            status="done"
        ).filter(func.date(SubUserAction.timestamp) == today).first() is not None

        # Lube check
        weekly_lube_done = SubUserAction.query.filter_by(
            subuser_id=sub.id if sub else None,
            machine_id=machine.id,
            action_type="lube",
            status="done"
        ).filter(SubUserAction.timestamp >= start_of_week).first() is not None

        # Service Requests
        pending_reqs = ServiceRequest.query.filter_by(machine_id=machine.id, resolved=False).all()
        pending_requests = []
        for req in pending_reqs:
            user = SubUser.query.get(req.subuser_id)
            pending_requests.append({
                'id': req.id,
                'subuser_name': user.name if user else None,
                'heads': getattr(req, 'heads', None),
                'issue': getattr(req, 'issue', None),
                'timestamp': req.timestamp
            })
        pending_count = len(pending_requests)

        # Overall status
        last_service_log = ServiceLog.query.filter_by(batch_id=machine.batch_id).order_by(ServiceLog.timestamp.desc()).first()
        status_ok = True
        if last_service_log and last_service_log.warranty_till:
            days_left = (last_service_log.warranty_till - today).days
            status_ok = days_left >= 30

        quick_overview.append({
            "name": machine.name,
            "assigned_subuser": sub.name if sub else None,
            "oiled_today": oiled_today,
            "weekly_lube_done": weekly_lube_done,
            "status_ok": status_ok,
            "pending_count": pending_count,
            "pending_requests": pending_requests
        })

    return render_template(
        "user_dashboard.html",
        batches=batch_data,
        machines_data=machines_data,
        quick_overview=quick_overview,
        now=datetime.utcnow(),
        timedelta=timedelta,
        show_toast=show_toast
    )
    
@routes.route("/admin/login", methods=["GET", "POST"], endpoint="admin_login")
def admin_login():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email, role="admin").first()
        if user and user.password == password:
            login_user(user)
            return redirect(url_for("routes.admin_dashboard"))
        else:
            flash("Invalid credentials", "danger")
    return render_template("admin_login.html")

@routes.route("/admin/dashboard")
@login_required
def admin_dashboard():
    if current_user.role != "admin":
        return redirect(url_for("routes.admin_login"))

    batches = QRBatch.query.order_by(QRBatch.created_at.desc()).all()
    total_batches = len(batches)
    total_qrcodes = QRCode.query.count()

    for batch in batches:
        batch.qrcodes = QRCode.query.filter_by(batch_id=batch.id).all()
        batch.user = User.query.filter_by(id=batch.owner_id).first()
        batch.machine = Machine.query.filter_by(batch_id=batch.id).first()

    return render_template("admin_dashboard.html", batches=batches, total_batches=total_batches, total_qrcodes=total_qrcodes)

@routes.route("/admin/create-batch")
@login_required
def create_batch():
    if current_user.role != "admin":
        return redirect(url_for("routes.admin_login"))
    batch_id = generate_and_store_qr_batch()
    return redirect(url_for("routes.admin_dashboard"))

@routes.route("/admin/download-batch/<int:batch_id>")
@login_required
def download_batch(batch_id):
    if current_user.role != "admin":
        return redirect(url_for("routes.admin_login"))

    qrcodes = QRCode.query.filter_by(batch_id=batch_id).all()
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zip_file:
        for qr in qrcodes:
            response = requests.get(qr.image_url)
            file_name = f"{qr.qr_type}.png"
            zip_file.writestr(file_name, response.content)

    zip_buffer.seek(0)
    return send_file(
        zip_buffer,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"batch_{batch_id}.zip"
    )


# ---- Sub-User Creation (by main user) ----
# ---- Sub-User Creation (by main user) ----
@routes.route("/create-subuser", methods=["GET", "POST"])
@login_required
def create_subuser():
    if current_user.role != "user":
        abort(403)

    machines = Machine.query.join(QRBatch).filter(QRBatch.owner_id == current_user.id).all()
    subusers = SubUser.query.filter_by(parent_id=current_user.id).all()

    if request.method == "POST":
        name = request.form.get("name", "").strip()
        machine_id = request.form.get("machine_id")

        if not name or not machine_id:
            flash("Please provide both sub-user name and machine.", "danger")
            return render_template("create_subuser.html", machines=machines, subusers=subusers)

        # Check for duplicate
        existing = SubUser.query.filter_by(
            parent_id=current_user.id,
            name=name,
            assigned_machine_id=machine_id
        ).first()
        if existing:
            flash(f"⚠️ Sub-user already exists for this machine. Code: {existing.static_id}", "info")
            return render_template("create_subuser.html", machines=machines, subusers=subusers)

        # Generate unique static ID
        while True:
            static_id = ''.join(random.choices(string.digits, k=7))
            if not SubUser.query.filter_by(static_id=static_id).first():
                break

        sub = SubUser(
            parent_id=current_user.id,
            name=name,
            assigned_machine_id=machine_id,
            static_id=static_id
        )
        db.session.add(sub)
        db.session.commit()
        flash(f"✅ Sub-user created successfully! Code: {static_id}", "success")

        # Refresh subusers list after creation
        subusers = SubUser.query.filter_by(parent_id=current_user.id).all()
        return render_template("create_subuser.html", machines=machines, subusers=subusers)

    return render_template("create_subuser.html", machines=machines, subusers=subusers)

# ---- Sub-User Login ----
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

from sqlalchemy import desc


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

    # ✅ Pass `now` for countdown display
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
        lube_alert=lube_alert,
        now=datetime.utcnow()  # ✅ This is the fix
    )
# ---- Manage Sub-Users (Settings Page for Main User) ----
@routes.route("/settings/subusers", methods=["GET", "POST"])
@login_required
def manage_subusers():
    if current_user.role != "user":
        abort(403)

    if request.method == "POST":
        action = request.form.get("action")
        sub_id = request.form.get("sub_id")

        subuser = SubUser.query.filter_by(id=sub_id, parent_id=current_user.id).first_or_404()

        if action == "delete":
            db.session.delete(subuser)
            db.session.commit()
            flash("Sub-user deleted successfully.", "success")
            return redirect(url_for("routes.create_subuser"))  # ✅ Redirect after delete

        elif action == "update":
            subuser.name = request.form.get("name")
            subuser.assigned_machine_id = request.form.get("machine_id")
            db.session.commit()
            flash("Sub-user updated successfully.", "success")
            return redirect(url_for("routes.manage_subusers"))  # ✅ Stay here after update

    subusers = SubUser.query.filter_by(parent_id=current_user.id).all()
    machines = Machine.query.join(QRBatch).filter(QRBatch.owner_id == current_user.id).all()

    return render_template("manage_subusers.html", subusers=subusers, machines=machines)
    

@routes.route("/machine/<int:machine_id>/update", methods=["POST"])
@login_required
def update_machine(machine_id):
    machine = Machine.query.get_or_404(machine_id)
    if machine.batch.owner_id != current_user.id:
        flash("Unauthorized", "danger")
        return redirect(url_for("routes.user_dashboard"))

    machine.name = request.form.get("name")
    machine.type = request.form.get("type")
    db.session.commit()
    flash("Machine updated successfully!", "success")
    return redirect(url_for("routes.user_settings"))

@routes.route("/admin/delete-batch/<int:batch_id>", methods=["POST"])
@login_required
def delete_batch(batch_id):
    if current_user.role != "admin":
        return redirect(url_for("routes.admin_login"))

    batch = QRBatch.query.get_or_404(batch_id)

    QRCode.query.filter_by(batch_id=batch.id).delete()
    QRTag.query.filter_by(batch_id=batch.id).delete()
    Machine.query.filter_by(batch_id=batch.id).delete()
    db.session.delete(batch)
    db.session.commit()

    flash(f"Batch #{batch_id} deleted successfully.", "success")
    return redirect(url_for("routes.admin_dashboard"))

@routes.route("/machine/<int:machine_id>/view")
@login_required
def view_machine_dashboard(machine_id):
    machine = Machine.query.get_or_404(machine_id)
    if machine.batch.owner_id != current_user.id:
        abort(403)

    batch = machine.batch
    subusers = SubUser.query.filter_by(assigned_machine_id=machine.id).all()
    tags = QRTag.query.filter_by(batch_id=batch.id).filter(QRTag.tag_type.startswith("sub")).all()
    needle_logs = NeedleChange.query.filter_by(batch_id=batch.id).order_by(NeedleChange.timestamp.desc()).all()
    service_logs = ServiceLog.query.filter_by(batch_id=batch.id).order_by(ServiceLog.timestamp.desc()).all()

    # Last entries
    last_needle = needle_logs[0] if needle_logs else None
    last_service = service_logs[0] if service_logs else None

    return render_template("machine_overview.html",
        machine=machine,
        batch=batch,
        subusers=subusers,
        tags=tags,
        needle_logs=needle_logs,
        service_logs=service_logs,
        last_needle=last_needle,
        last_service=last_service
    )

@routes.route("/machine/dashboard")
@login_required
def machine_dashboard():
    if current_user.role != "user":
        abort(403)

    machines = Machine.query.join(QRBatch).filter(QRBatch.owner_id == current_user.id).all()
    machine_data = []

    for machine in machines:
        batch = machine.batch
        subusers = SubUser.query.filter_by(assigned_machine_id=machine.id).all()
        qr_tags = QRTag.query.filter_by(batch_id=batch.id).filter(QRTag.tag_type.startswith("sub")).all()

        needle_logs = NeedleChange.query.filter_by(batch_id=batch.id).order_by(NeedleChange.timestamp.desc()).all()
        service_logs = ServiceLog.query.filter_by(batch_id=batch.id).order_by(ServiceLog.timestamp.desc()).all()

        last_needle = needle_logs[0] if needle_logs else None
        last_service = service_logs[0] if service_logs else None

        grouped_logs = {}
        for tag in qr_tags:
            grouped_logs[tag.id] = {
                "tag": tag,
                "needle_logs": [],
                "service_logs": []
            }

        for log in needle_logs:
            if log.sub_tag_id in grouped_logs:
                grouped_logs[log.sub_tag_id]["needle_logs"].append(log)

        for log in service_logs:
            if log.sub_tag_id in grouped_logs:
                grouped_logs[log.sub_tag_id]["service_logs"].append(log)

        # Status warnings
        warranty_warning = False
        stale_service_warning = False
        maintenance_ok = True

        if last_service and last_service.warranty_till:
            days_left = (last_service.warranty_till - datetime.utcnow().date()).days
            if days_left < 30:
                warranty_warning = True
                maintenance_ok = False

        if last_service and (datetime.utcnow() - last_service.timestamp).days > 60:
            stale_service_warning = True
            maintenance_ok = False

        machine_data.append({
            "machine": machine,
            "batch": batch,
            "subusers": subusers,
            "last_needle": last_needle,
            "last_service": last_service,
            "grouped_logs": grouped_logs,
            "total_needle_changes": len(needle_logs),
            "total_services_logged": len(service_logs),
            "maintenance_ok": maintenance_ok,
            "warranty_warning": warranty_warning,
            "stale_service_warning": stale_service_warning
        })

    return render_template("machine_dashboard.html", machines_data=machine_data)

@routes.route("/subuser/action/<string:type>", methods=["POST"])
@subuser_required
def subuser_action(type):
    sub_id = session.get("subuser_id")
    if not sub_id:
        return redirect(url_for("routes.subuser_login"))

    sub = SubUser.query.get(sub_id)
    machine = Machine.query.get(sub.assigned_machine_id)

    if not sub or not machine:
        flash("Machine access error", "danger")
        return redirect(url_for("routes.subuser_dashboard"))

    if type == "oil":
        today = date.today()
        existing = SubUserAction.query.filter_by(
            subuser_id=sub.id,
            machine_id=machine.id,
            action_type="oil",
            status="done"
        ).filter(db.func.date(SubUserAction.timestamp) == today).first()

        if not existing:
            action = SubUserAction(
                subuser_id=sub.id,
                machine_id=machine.id,
                action_type="oil",
                status="done"
            )
            db.session.add(action)

            log = DailyMaintenance(
                machine_id=machine.id,
                date=today,
                oiled=True
            )
            db.session.add(log)

        flash("Marked as oiled for today!", "success")
        db.session.commit()

    elif type == "lube":
        action = SubUserAction(
            subuser_id=sub.id,
            machine_id=machine.id,
            action_type="lube",
            status="done"
        )
        db.session.add(action)
        db.session.commit()
        flash("Lube completed!", "success")

    elif type == "service":
        heads = request.form.get("heads")
        issue = request.form.get("message")  # from textarea

        sr = ServiceRequest(
            machine_id=machine.id,
            subuser_id=sub.id,
            heads=int(heads),
            issue=issue
        )
        db.session.add(sr)
        db.session.commit()
        flash("Service request sent!", "success")

    return redirect(url_for("routes.subuser_dashboard"))

@routes.route("/subuser/raise-service", methods=["POST"])
@subuser_required
def raise_service_request():
    sub_id = session.get("subuser_id")
    sub = SubUser.query.get_or_404(sub_id)
    machine_id = request.form.get("machine_id")
    heads = request.form.get("heads")
    issue = request.form.get("issue")

    if not machine_id or not heads or not issue:
        flash("Please fill in all required fields.", "danger")
        return redirect(url_for("routes.subuser_dashboard"))

    try:
        new_request = ServiceRequest(
            machine_id=machine_id,
            subuser_id=sub.id,
            message=f"[{heads} heads] {issue}",
            timestamp=datetime.utcnow(),
            resolved=False
        )
        db.session.add(new_request)
        db.session.commit()
        flash("✅ Service request submitted successfully.", "success")
    except Exception as e:
        print("Error creating request:", e)
        flash("Something went wrong. Please try again.", "danger")

    return redirect(url_for("routes.subuser_dashboard"))

@routes.route("/resolve_service/<int:request_id>", methods=["POST"])
@login_required
def resolve_service_request(request_id):
    req = ServiceRequest.query.get_or_404(request_id)
    req.resolved = True
    req.resolved_at = date.today()
    db.session.commit()
    flash("Service request marked as resolved.", "success")
    return redirect(url_for("routes.user_dashboard"))



@routes.route("/scan/service/<int:service_tag_id>")
def scan_service(service_tag_id):
    service_tag = QRTag.query.get_or_404(service_tag_id)
    # Determine who is logged in for proper back URL
    if 'subuser_id' in session:
        back_url = url_for('routes.subuser_dashboard')
    elif current_user.is_authenticated:
        back_url = url_for('routes.user_dashboard')
    else:
        back_url = url_for('routes.home')
    return render_template(
        "service_options.html",
        service_tag=service_tag,
        back_url=back_url
    )

@routes.route("/service/<int:service_tag_id>/logs")
def service_log_view(service_tag_id):
    service_tag = QRTag.query.get_or_404(service_tag_id)
    # Fetch all service logs for this service tag
    logs = ServiceLog.query.filter_by(sub_tag_id=service_tag_id).order_by(ServiceLog.timestamp.desc()).all()
    return render_template("service_logs.html", service_tag=service_tag, logs=logs)


# ---- Main User Logout ----
@routes.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    flash("You have been logged out.", "info")
    return redirect(url_for("routes.user_login"))

# ---- Sub-User Logout ----
@routes.route("/subuser/logout")
def subuser_logout():
    session.pop('subuser_id', None)
    flash("Sub-user logged out.", "info")
    return redirect(url_for("routes.subuser_login"))

@routes.route("/debug/session")
def debug_session():
    return f"""
    current_user.is_authenticated: {getattr(current_user, 'is_authenticated', None)}<br>
    session['subuser_id']: {session.get('subuser_id')}<br>
    session: {dict(session)}
    """
