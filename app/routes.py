from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from datetime import datetime, date, timedelta
from sqlalchemy import func, or_
from sqlalchemy.exc import IntegrityError
import io
import zipfile
import requests
from PIL import Image, ImageDraw, ImageFont
import random
import string

def time_until(dt):
    """Return human friendly time until dt (UTC)."""
    if not dt:
        return None
    delta = dt - datetime.utcnow()
    if delta.total_seconds() <= 0:
        return "Overdue"
    days = delta.days
    hours, rem = divmod(delta.seconds, 3600)
    minutes = rem // 60
    if days > 0:
        return f"in {days}d {hours}h" if hours else f"in {days}d"
    if hours > 0:
        return f"in {hours}h" if minutes == 0 else f"in {hours}h {minutes}m"
    return f"in {minutes}m"

from app import db
from app.utils import generate_and_store_qr_batch, sync_qr_heads
from app.decorators import subuser_required, user_or_subuser_required   # <-- CHANGED
from app.models import (
    User, QRBatch, QRCode, Machine, QRTag,
    NeedleChange, ServiceLog, SubUser,
    SubUserAction, DailyMaintenance, ServiceRequest,
    PasswordResetToken
)

routes = Blueprint("routes", __name__)

@routes.route("/")
def home():
    return render_template("index.html")

@routes.route("/setup-guide")
def setup_guide_page():
    return render_template("setup_guide.html")

@routes.route("/faq")
def faq_page():
    return render_template("faq.html")
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
    # Get the machine from the batch_id
    machine = Machine.query.filter_by(batch_id=sub_tag.batch_id).first()
    # Set correct back_url based on login type
    if hasattr(current_user, "is_authenticated") and current_user.is_authenticated and getattr(current_user, "role", None) == "user":
        back_url = url_for('routes.user_dashboard')
    elif 'subuser_id' in session:
        back_url = url_for('routes.subuser_dashboard')
    else:
        back_url = url_for('routes.home')
    # Pass machine to template
    return render_template("sub_options.html", sub_tag=sub_tag, machine=machine, back_url=back_url)

@routes.route("/scan-qr", methods=["GET", "POST"])
@login_required
def scan_qr_page():
    if request.method == "POST":
        batch_id = request.form.get("batch_id")
        if not batch_id or not batch_id.isdigit():
            flash("Invalid batch code. Please enter a valid numeric code.", "danger")
            return redirect(url_for("routes.scan_qr_page"))

        return redirect(url_for("routes.claim_batch", batch_id=int(batch_id)))

    return render_template("scan_qr.html")


@routes.route("/user/create-batch", methods=["POST"])
@login_required
def user_create_batch():
    batch_id = generate_and_store_qr_batch(user_id=current_user.id)
    flash("QR batch generated! You can now set up your machine.", "success")

    next_url = request.args.get("next")
    if next_url:
        return redirect(next_url)
    # Always fallback to machines tab!
    return redirect(url_for("routes.user_settings", tab="machines"))


@routes.route("/machine/<int:machine_id>/mark/<action>")
@login_required
def mark_action_done(machine_id, action):
    # Fetch machine and validate existence
    machine = Machine.query.get_or_404(machine_id)

    # If user is logged in, ensure it's their machine
    owner_id = getattr(current_user, "id", None)
    if owner_id and machine.batch.owner_id != owner_id:
        abort(403)

    # Determine if a sub-user is currently logged in
    sub_id = session.get("subuser_id")

    # Set up logging for oil, lube or grease
    if action in ["oil", "lube", "grease"]:
        if sub_id:
            new_action = SubUserAction(
                subuser_id=sub_id,
                user_id=None,
                machine_id=machine.id,
                action_type=action,
                status="done",
                timestamp=datetime.utcnow(),
            )
        else:
            new_action = SubUserAction(
                subuser_id=None,
                user_id=current_user.id,
                machine_id=machine.id,
                action_type=action,
                status="done",
                timestamp=datetime.utcnow(),
            )
        db.session.add(new_action)
        db.session.commit()
        if action == "oil":
            msg = "✅ Oiling marked as done."
        elif action == "lube":
            msg = "✅ Lubrication marked as done."
        else:
            msg = "✅ Quarterly greasing marked as done."
        flash(msg, "success")
    else:
        flash("Invalid action.", "danger")

    return redirect(url_for("routes.user_dashboard"))


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

@routes.route("/user/log/<type>/<int:machine_id>", methods=["POST"])
@login_required
def user_action_log(type, machine_id):
    # Basic logging logic for oil/lube
    if type not in ['oil', 'lube']:
        flash("Invalid action type.", "danger")
        return redirect(url_for("routes.user_dashboard"))

    sub = SubUser.query.filter_by(assigned_machine_id=machine_id).first()

    try:
        action = SubUserAction(
            subuser_id=sub.id if sub else None,
            machine_id=machine_id,
            action_type=type,
            status="done",
            timestamp=datetime.utcnow()
        )
        db.session.add(action)
        db.session.commit()
        flash(f"✅ {type.capitalize()} logged successfully.", "success")
    except Exception as e:
        print("Error logging action:", e)
        flash("Something went wrong. Please try again.", "danger")

    return redirect(url_for("routes.user_dashboard"))

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
        back_url = request.form.get("back_url") or request.referrer
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
        return redirect(url_for("routes.sub_tag_service_log", sub_tag_id=sub_tag_id, back=back_url))

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
    back_url = request.args.get('back') or request.referrer
    if not back_url or back_url == request.url:
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
    # Only allow users to claim
    if current_user.role != "user":
        flash("Only users can claim batches.", "danger")
        return redirect(url_for("routes.home"))

    # Fetch batch by ID
    batch = QRBatch.query.get(batch_id)
    if not batch:
        flash("Batch not found.", "danger")
        return redirect(url_for("routes.user_dashboard"))

    # Batch already claimed
    if batch.owner_id is not None:
        if batch.owner_id == current_user.id:
            flash("You already claimed this batch.", "info")
        else:
            flash("This batch has already been claimed by another user.", "danger")
    else:
        # Claim the batch
        batch.owner_id = current_user.id
        db.session.commit()
        flash("Batch successfully claimed!", "success")

    # Always redirect to dashboard
    return redirect(url_for("routes.user_dashboard"))


@routes.route("/settings", methods=["GET", "POST"])
@login_required
def user_settings():
    if request.method == "POST":
        # --- Adding a machine for an unregistered batch ---
        if request.form.get("batch_id") and request.form.get("name"):
            batch_id = request.form.get("batch_id")
            name = request.form.get("name") or current_user.default_machine_name or "Unnamed Machine"
            mtype = request.form.get("type") or current_user.default_machine_location or "General"
            num_heads = int(request.form.get("num_heads") or 8)
            needles = int(request.form.get("needles_per_head") or 15)

            existing = Machine.query.filter_by(batch_id=batch_id).first()
            if existing:
                existing.name = name
                existing.type = mtype
                existing.num_heads = num_heads
                existing.needles_per_head = needles
                flash("Machine updated with your preferences.", "success")
                sync_qr_heads(existing.batch_id, num_heads)
            else:
                machine = Machine(batch_id=batch_id, name=name, type=mtype, num_heads=num_heads, needles_per_head=needles)
                db.session.add(machine)
                db.session.commit()
                sync_qr_heads(machine.batch_id, num_heads)
                flash("Machine added successfully.", "success")
            db.session.commit()
            return redirect(url_for("routes.user_settings", tab="machines"))

        # --- Update Profile ---
        if request.form.get("update_profile"):
            name = request.form.get("name")
            company_name = request.form.get("company_name")
            mobile = request.form.get("mobile")
            email = request.form.get("email")
            password = request.form.get("password")
            security_question = request.form.get("security_question")
            security_answer = request.form.get("security_answer")

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
            if security_question:
                current_user.security_question = security_question
            if security_answer:
                current_user.security_answer = security_answer

            db.session.commit()
            flash("Profile updated successfully.", "success")
            return redirect(url_for("routes.user_settings", tab="profile"))

        # --- Update Single Machine ---
        if request.form.get("update_machine_id"):
            mid = request.form.get("update_machine_id")
            name = request.form.get(f"machine_name_{mid}")
            mtype = request.form.get(f"machine_type_{mid}")
            heads_val = request.form.get(f"num_heads_{mid}")
            needles_val = request.form.get(f"needles_per_head_{mid}")
            oil_int = request.form.get(f"oil_interval_{mid}")
            lube_int = request.form.get(f"lube_interval_{mid}")
            grease_int = request.form.get(f"grease_interval_{mid}")
            machine = Machine.query.filter_by(id=mid).first()
            if machine and machine.batch.owner_id == current_user.id:
                machine.name = name
                machine.type = mtype
                old_heads = machine.num_heads
                if heads_val:
                    machine.num_heads = int(heads_val)
                if needles_val:
                    machine.needles_per_head = int(needles_val)
                if oil_int:
                    machine.oil_interval_hours = int(oil_int)
                if lube_int:
                    machine.lube_interval_days = int(lube_int)
                if grease_int:
                    machine.grease_interval_months = int(grease_int)
                db.session.commit()
                if heads_val and int(heads_val) != old_heads:
                    sync_qr_heads(machine.batch_id, int(heads_val))
                flash("Machine settings updated successfully.", "success")
            return redirect(url_for("routes.user_settings", tab="machines"))

    # --- GET: Load machines and batches ---
    user_batches = QRBatch.query.filter_by(owner_id=current_user.id).all()
    machines = []
    for batch in user_batches:
        m = Machine.query.filter_by(batch_id=batch.id).first()
        if m:
            machines.append(m)
        # Attach machine reference for template convenience
        batch.machine = m

    # Determine which tab should be active when the page loads
    default_tab = request.args.get("tab")
    if not default_tab:
        default_tab = "machines" if any(not b.machine for b in user_batches) else "profile"

    return render_template(
        "user_settings.html",
        machines=machines,
        batches=user_batches,
        default_tab=default_tab,
    )

@routes.route("/signup", methods=["GET", "POST"], endpoint="user_signup")
def user_signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        name = request.form["name"]
        company_name = request.form.get("company_name")
        security_question = request.form.get("security_question")
        security_answer = request.form.get("security_answer")

        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Email already registered", "danger")
            return redirect(url_for("routes.user_signup"))

        new_user = User(
            email=email,
            password=password,  # Hash in production!
            name=name,
            company_name=company_name,
            security_question=security_question,
            security_answer=security_answer,
            role="user"
        )
        db.session.add(new_user)
        db.session.commit()

        # Log the user in right after signup
        login_user(new_user)

        # ❌ REMOVE: Do NOT auto-generate a batch here

        flash("Signup successful! Please scan a QR code from admin or generate your own batch.", "success")
        return redirect(url_for("routes.user_dashboard"))

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


@routes.route("/forgot-password", methods=["GET", "POST"], endpoint="forgot_password")
def forgot_password():
    if request.method == "POST":
        step = request.form.get('step')
        if step == 'email':
            email = request.form.get('email')
            user = User.query.filter_by(email=email).first()
            if not user or not user.security_question:
                flash('No account found with that email.', 'danger')
                return render_template('forgot_password_email.html')
            return render_template('forgot_password_question.html', user_id=user.id, question=user.security_question)
        elif step == 'question':
            user_id = request.form.get('user_id')
            answer = request.form.get('answer')
            user = User.query.get(int(user_id)) if user_id else None
            if user and user.security_answer and user.security_answer.strip() == answer.strip():
                expires_at = datetime.utcnow() + timedelta(minutes=10)
                for _ in range(5):
                    token = ''.join(random.choices(string.ascii_letters + string.digits, k=32))
                    prt = PasswordResetToken(user_id=user.id, token=token, expires_at=expires_at)
                    db.session.add(prt)
                    try:
                        db.session.commit()
                        reset_link = url_for('routes.reset_password', token=token, _external=True)
                        return render_template('show_reset_link.html', reset_link=reset_link)
                    except IntegrityError:
                        db.session.rollback()
                flash('Unable to generate reset token. Please try again later.', 'danger')
                return render_template('forgot_password_email.html')
            else:
                flash('Incorrect answer.', 'danger')
                if user:
                    return render_template('forgot_password_question.html', user_id=user.id, question=user.security_question)
                flash('Invalid request.', 'danger')
                return render_template('forgot_password_email.html')
    return render_template('forgot_password_email.html')


@routes.route("/reset-password/<token>", methods=["GET", "POST"], endpoint="reset_password")
def reset_password(token):
    token_obj = PasswordResetToken.query.filter_by(token=token, used=False).first()
    if not token_obj or token_obj.expires_at < datetime.utcnow().date():
        flash('Invalid or expired token.', 'danger')
        return redirect(url_for('routes.user_login'))
    if request.method == 'POST':
        new_password = request.form.get('password')
        if new_password:
            user = User.query.get(token_obj.user_id)
            user.password = new_password  # hash in production
            token_obj.used = True
            db.session.commit()
            flash('Password reset successful. Please log in.', 'success')
            return redirect(url_for('routes.user_login'))
    return render_template('reset_password.html', token=token)



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

    # ✅ Quick Machine Overview with required ID
    quick_overview = []
    today = date.today()
    start_of_week = today - timedelta(days=today.weekday())
    # Determine first day of current quarter
    start_month = 3 * ((today.month - 1) // 3) + 1
    start_of_quarter = date(today.year, start_month, 1)

    for machine in machines:
        sub = SubUser.query.filter_by(assigned_machine_id=machine.id).first()

        # --- UPDATED: Oil done today (either subuser or main user) ---
        oiled_today = SubUserAction.query.filter(
            SubUserAction.machine_id == machine.id,
            SubUserAction.action_type == "oil",
            SubUserAction.status == "done",
            or_(
                SubUserAction.subuser_id == (sub.id if sub else None),
                SubUserAction.user_id == current_user.id
            ),
            func.date(SubUserAction.timestamp) == today
        ).first() is not None

        # --- UPDATED: Lube done this week (either subuser or main user) ---
        weekly_lube_done = SubUserAction.query.filter(
            SubUserAction.machine_id == machine.id,
            SubUserAction.action_type == "lube",
            SubUserAction.status == "done",
            or_(
                SubUserAction.subuser_id == (sub.id if sub else None),
                SubUserAction.user_id == current_user.id
            ),
            SubUserAction.timestamp >= start_of_week
        ).first() is not None

        # Grease done this quarter (only main user)
        quarterly_grease_done = SubUserAction.query.filter(
            SubUserAction.machine_id == machine.id,
            SubUserAction.action_type == "grease",
            SubUserAction.status == "done",
            SubUserAction.user_id == current_user.id,
            SubUserAction.timestamp >= start_of_quarter
        ).first() is not None

        # Last action timestamps
        last_oil_log = SubUserAction.query.filter(
            SubUserAction.machine_id == machine.id,
            SubUserAction.action_type == "oil",
            SubUserAction.status == "done",
            or_(
                SubUserAction.subuser_id == (sub.id if sub else None),
                SubUserAction.user_id == current_user.id
            )
        ).order_by(SubUserAction.timestamp.desc()).first()
        last_oil_time = last_oil_log.timestamp if last_oil_log else None
        next_oil_due = (
            last_oil_time + timedelta(hours=machine.oil_interval_hours)
        ) if last_oil_time else None

        last_lube_log = SubUserAction.query.filter(
            SubUserAction.machine_id == machine.id,
            SubUserAction.action_type == "lube",
            SubUserAction.status == "done",
            or_(
                SubUserAction.subuser_id == (sub.id if sub else None),
                SubUserAction.user_id == current_user.id
            )
        ).order_by(SubUserAction.timestamp.desc()).first()
        last_lube_time = last_lube_log.timestamp if last_lube_log else None
        next_lube_due = (
            last_lube_time + timedelta(days=machine.lube_interval_days)
        ) if last_lube_time else None

        last_grease_log = SubUserAction.query.filter(
            SubUserAction.machine_id == machine.id,
            SubUserAction.action_type == "grease",
            SubUserAction.status == "done",
            SubUserAction.user_id == current_user.id
        ).order_by(SubUserAction.timestamp.desc()).first()
        last_grease_time = last_grease_log.timestamp if last_grease_log else None
        next_grease_due = (
            last_grease_time + timedelta(days=30 * machine.grease_interval_months)
        ) if last_grease_time else None

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

        last_service_log = ServiceLog.query.filter_by(batch_id=machine.batch_id).order_by(ServiceLog.timestamp.desc()).first()
        status_ok = True
        if last_service_log and last_service_log.warranty_till:
            days_left = (last_service_log.warranty_till - today).days
            status_ok = days_left >= 30
        last_service_time = last_service_log.timestamp if last_service_log else None
        next_service_due = last_service_log.warranty_till if last_service_log and last_service_log.warranty_till else None

        quick_overview.append({
            "id": machine.id,
            "name": machine.name,
            "assigned_subuser": sub.name if sub else None,
            "oiled_today": oiled_today,
            "weekly_lube_done": weekly_lube_done,
            "quarterly_grease_done": quarterly_grease_done,
            "status_ok": status_ok,
            "pending_count": pending_count,
            "pending_requests": pending_requests,
            "last_oil_time": last_oil_time,
            "next_oil_due": next_oil_due,
            "next_oil_due_str": time_until(next_oil_due),
            "last_lube_time": last_lube_time,
            "next_lube_due": next_lube_due,
            "next_lube_due_str": time_until(next_lube_due),
            "last_grease_time": last_grease_time,
            "next_grease_due": next_grease_due,
            "next_grease_due_str": time_until(next_grease_due),
            "last_service_time": last_service_time,
            "next_service_due": next_service_due
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

    # --- Usage analytics ---
    action_counts = dict(
        db.session.query(SubUserAction.action_type, func.count(SubUserAction.id))
        .group_by(SubUserAction.action_type)
        .all()
    )
    service_requests_count = ServiceRequest.query.count()
    total_machines = Machine.query.count()
    total_subusers = SubUser.query.count()

    for batch in batches:
        batch.qrcodes = QRCode.query.filter_by(batch_id=batch.id).all()
        batch.user = User.query.filter_by(id=batch.owner_id).first()
        batch.machine = Machine.query.filter_by(batch_id=batch.id).first()

    return render_template(
        "admin_dashboard.html",
        batches=batches,
        total_batches=total_batches,
        total_qrcodes=total_qrcodes,
        action_counts=action_counts,
        service_requests_count=service_requests_count,
        total_machines=total_machines,
        total_subusers=total_subusers,
    )

@routes.route("/admin/create-batch")
@login_required
def create_batch():
    if current_user.role != "admin":
        return redirect(url_for("routes.admin_login"))
    batch_id = generate_and_store_qr_batch()  # Defaults to admin or None if not specified
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


@routes.route("/download-qr/<int:qr_id>")
@login_required
def download_qr(qr_id):
    """Serve a single QR code image as a downloadable file."""
    qr = QRCode.query.get_or_404(qr_id)

    # Permission check: ensure owner or subuser
    if current_user.is_authenticated and getattr(current_user, "role", None) == "user":
        if qr.batch.owner_id != current_user.id:
            abort(403)
    elif "subuser_id" in session:
        sub = SubUser.query.get(session["subuser_id"])
        if not sub or qr.batch.owner_id != sub.parent_id:
            abort(403)
    else:
        abort(403)

    response = requests.get(qr.image_url)
    buffer = io.BytesIO(response.content)
    buffer.seek(0)
    return send_file(
        buffer,
        mimetype="image/png",
        as_attachment=True,
        download_name=f"{qr.qr_type}.png"
    )



def _build_qr_page(qr_codes, title=None, machine=None):
    """Return a PIL Image with QR codes arranged on an A4 page."""
    A4_WIDTH, A4_HEIGHT = 2480, 3508

    # QR code dimensions ~30mm x 45mm at 300DPI (354x472), keeping 2:3 aspect ratio
    QR_W = int(30 / 25.4 * 300)
    QR_H = int(QR_W * 1.5)

    COLS, ROWS = 3, 4
    top_margin = 250
    x_space = (A4_WIDTH - (QR_W * COLS)) // (COLS + 1)
    y_space = (A4_HEIGHT - top_margin - (QR_H * ROWS)) // (ROWS + 1)

    page = Image.new("RGB", (A4_WIDTH, A4_HEIGHT), "white")
    draw = ImageDraw.Draw(page)
    try:
        font_title = ImageFont.truetype("app/fonts/Agrandir.ttf", 80)
        font_label = ImageFont.truetype("app/fonts/Agrandir.ttf", 50)
    except Exception:
        font_title = ImageFont.load_default()
        font_label = ImageFont.load_default()

    if machine:
        owner = machine.batch.owner
        owner_name = owner.company_name or owner.name
        subtitle = f"{machine.type} - {owner_name}" if machine.type else owner_name
    else:
        subtitle = None

    if title:
        bbox = draw.textbbox((0, 0), title, font=font_title)
        draw.text(((A4_WIDTH - bbox[2]) // 2, 60), title, font=font_title, fill="black")
        if subtitle:
            sbbox = draw.textbbox((0, 0), subtitle, font=font_label)
            draw.text(((A4_WIDTH - sbbox[2]) // 2, 60 + bbox[3] + 20), subtitle, font=font_label, fill="black")

    for idx, qr in enumerate(qr_codes):
        col = idx % COLS
        row = idx // COLS
        x = x_space + col * (QR_W + x_space)
        y = top_margin + y_space + row * (QR_H + y_space + 70)
        try:
            resp = requests.get(qr.image_url)
            img = Image.open(io.BytesIO(resp.content)).convert("RGB")
            img = img.resize((QR_W, QR_H))

            # Draw light gray border to mimic admin card style
            border_rect = [x - 10, y - 10, x + QR_W + 10, y + QR_H + 10]
            draw.rectangle(border_rect, outline="gray", width=2)

            page.paste(img, (x, y))

            # Determine label
            label = f"HEAD {qr.qr_type[3:]}" if qr.qr_type.startswith("sub") else qr.qr_type.upper()

            lbbox = draw.textbbox((0, 0), label, font=font_label)
            draw.text((x + (QR_W - lbbox[2]) // 2, y + QR_H + 10), label, font=font_label, fill="black")
        except Exception:
            continue

    return page
@routes.route("/download-machine-qrs/<int:machine_id>")
@login_required
def download_machine_qrs(machine_id):
    """Generate a single-page PDF of all QR codes for one machine."""
    machine = Machine.query.get_or_404(machine_id)

    # permission check
    if current_user.is_authenticated and getattr(current_user, "role", None) == "user":
        if machine.batch.owner_id != current_user.id:
            abort(403)
    elif "subuser_id" in session:
        sub = SubUser.query.get(session["subuser_id"])
        if not sub or sub.parent_id != machine.batch.owner_id:
            abort(403)
    else:
        abort(403)

    qr_codes = QRCode.query.filter_by(batch_id=machine.batch_id).order_by(QRCode.qr_type).all()
    if not qr_codes:
        flash("No QR codes found for this machine.", "danger")
        return redirect(url_for("routes.user_settings", tab="download"))

    page = _build_qr_page(qr_codes, title=machine.name, machine=machine)

    buffer = io.BytesIO()
    page.save(buffer, format="PDF")
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name=f"machine_{machine.id}_qrs.pdf",
    )

@routes.route("/download-all-qrs")
@login_required
def download_all_qrs():
    """Generate a PDF with all QR codes belonging to the current user."""
    machines = Machine.query.join(QRBatch).filter(QRBatch.owner_id == current_user.id).all()
    if not machines:
        flash("No QR codes found for your machines.", "danger")
        return redirect(url_for("routes.user_settings", tab="download"))

    pages = []
    for machine in machines:
        codes = QRCode.query.filter_by(batch_id=machine.batch_id).order_by(QRCode.qr_type).all()
        if codes:
            pages.append(_build_qr_page(codes, title=machine.name, machine=machine))

    if not pages:
        flash("Failed to retrieve QR images.", "danger")
        return redirect(url_for("routes.user_settings", tab="download"))

    buffer = io.BytesIO()
    pages[0].save(buffer, format="PDF", save_all=True, append_images=pages[1:])
    buffer.seek(0)

    return send_file(
        buffer,
        mimetype="application/pdf",
        as_attachment=True,
        download_name="qr_codes.pdf",
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
    issue = request.form.get("message")

    if not machine_id or not heads or not issue:
        flash("Please fill in all required fields.", "danger")
        return redirect(url_for("routes.subuser_dashboard"))

    try:
        new_request = ServiceRequest(
            machine_id=machine_id,
            subuser_id=sub.id,
            heads=int(heads),
            issue=issue,
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

@routes.route("/user/raise-service/<int:machine_id>", methods=["POST"])
@login_required
def user_raise_service_request(machine_id):
    user = current_user
    heads = request.form.get("heads")
    issue = request.form.get("message")

    if not heads or not issue:
        flash("Please fill in all required fields.", "danger")
        return redirect(url_for("routes.user_dashboard"))

    try:
        new_request = ServiceRequest(
            machine_id=machine_id,
            subuser_id=None,  # user raising directly
            heads=int(heads),
            issue=issue,
            timestamp=datetime.utcnow(),
            resolved=False
        )
        db.session.add(new_request)
        db.session.commit()
        flash("✅ Service request submitted successfully.", "success")
    except Exception as e:
        print("Error creating request:", e)
        flash("Something went wrong. Please try again.", "danger")

    return redirect(url_for("routes.user_dashboard"))


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
    machine = Machine.query.filter_by(batch_id=service_tag.batch_id).first()

    # Determine who is logged in for proper back URL
    if 'subuser_id' in session:
        back_url = url_for('routes.subuser_dashboard')
    elif current_user.is_authenticated:
        back_url = url_for('routes.user_dashboard')
    else:
        back_url = url_for('routes.home')

    # Last oil and lube timestamps for display
    last_oil = SubUserAction.query.filter_by(
        machine_id=machine.id,
        action_type="oil",
        status="done"
    ).order_by(SubUserAction.timestamp.desc()).first()

    last_lube = SubUserAction.query.filter_by(
        machine_id=machine.id,
        action_type="lube",
        status="done"
    ).order_by(SubUserAction.timestamp.desc()).first()

    oil_alert = True
    if last_oil and (datetime.utcnow() - last_oil.timestamp).total_seconds() < 86400:
        oil_alert = False

    lube_alert = True
    if last_lube and (datetime.utcnow() - last_lube.timestamp).days < 6:
        lube_alert = False

    return render_template(
        "service_options.html",
        service_tag=service_tag,
        machine=machine,
        back_url=back_url,
        last_oil_time=last_oil.timestamp if last_oil else None,
        last_lube_time=last_lube.timestamp if last_lube else None,
        oil_alert=oil_alert,
        lube_alert=lube_alert,
        now=datetime.utcnow()
    )


@routes.route("/service/<int:service_tag_id>/action/<string:action>", methods=["POST"])
def service_action(service_tag_id, action):
    """Allow logging oil/lube or raising a service request via the service QR."""
    service_tag = QRTag.query.get_or_404(service_tag_id)
    machine = Machine.query.filter_by(batch_id=service_tag.batch_id).first_or_404()

    sub_id = session.get('subuser_id')
    user_id = current_user.id if current_user.is_authenticated else None

    if action == "oil":
        today = date.today()
        existing = SubUserAction.query.filter_by(
            machine_id=machine.id,
            action_type="oil",
            status="done",
        ).filter(func.date(SubUserAction.timestamp) == today).first()

        if not existing:
            log = SubUserAction(
                subuser_id=sub_id,
                user_id=user_id,
                machine_id=machine.id,
                action_type="oil",
                status="done",
                timestamp=datetime.utcnow(),
            )
            db.session.add(log)
            db.session.commit()
            flash("Marked as oiled for today!", "success")
        else:
            flash("Oiling already logged today.", "info")

    elif action == "lube":
        log = SubUserAction(
            subuser_id=sub_id,
            user_id=user_id,
            machine_id=machine.id,
            action_type="lube",
            status="done",
            timestamp=datetime.utcnow(),
        )
        db.session.add(log)
        db.session.commit()
        flash("Lube completed!", "success")

    elif action == "service":
        heads = request.form.get("heads")
        issue = request.form.get("message")
        if heads and issue:
            sr = ServiceRequest(
                machine_id=machine.id,
                subuser_id=sub_id,
                heads=int(heads),
                issue=issue,
                timestamp=datetime.utcnow(),
                resolved=False,
            )
            db.session.add(sr)
            db.session.commit()
            flash("Service request sent!", "success")
        else:
            flash("Please fill in all required fields.", "danger")
    else:
        flash("Invalid action.", "danger")

    return redirect(url_for("routes.scan_service", service_tag_id=service_tag.id))

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
