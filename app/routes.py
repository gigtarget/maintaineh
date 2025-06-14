from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, session, abort
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, QRBatch, QRCode, Machine, QRTag, NeedleChange, ServiceLog
from app.utils import generate_and_store_qr_batch
from app import db
from datetime import datetime
import io
import zipfile
import requests

routes = Blueprint("routes", __name__)

@routes.route("/")
def home():
    return render_template("index.html")

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

@routes.route("/sub/<int:sub_tag_id>/choose")
@login_required
def sub_tag_options(sub_tag_id):
    sub_tag = QRTag.query.get_or_404(sub_tag_id)
    return render_template("sub_options.html", sub_tag=sub_tag)

@routes.route("/sub/<int:sub_tag_id>/needle-change", methods=["GET", "POST"])
@login_required
def sub_tag_view(sub_tag_id):
    sub_tag = QRTag.query.get_or_404(sub_tag_id)
    if not sub_tag.tag_type.startswith("sub"):
        flash("Invalid QR Tag. Only Sub QR tags represent machine heads.", "danger")
        return redirect(url_for("routes.user_dashboard"))

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

    return render_template("sub_tag_view.html", sub_tag=sub_tag, last_change_dict=last_change_dict, now=datetime.utcnow().date())

@routes.route("/sub/<int:sub_tag_id>/service-log", methods=["GET", "POST"])
@login_required
def sub_tag_service_log(sub_tag_id):
    sub_tag = QRTag.query.get_or_404(sub_tag_id)
    if not sub_tag.tag_type.startswith("sub"):
        flash("Invalid QR Tag for service logging.", "danger")
        return redirect(url_for("routes.user_dashboard"))

    if request.method == "POST":
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
            batch_id=sub_tag.batch.id,
            sub_tag_id=sub_tag.id,
            part_name=part_name,
            description=description,
            warranty_till=warranty_till,
            timestamp=datetime.utcnow()
        )
        db.session.add(log)
        db.session.commit()
        flash(f"Logged replacement for '{part_name}' successfully!", "success")
        return redirect(url_for("routes.sub_tag_service_log", sub_tag_id=sub_tag_id))

    service_logs = ServiceLog.query.filter_by(sub_tag_id=sub_tag.id).order_by(ServiceLog.timestamp.desc()).all()
    return render_template("sub_service_log.html", sub_tag=sub_tag, logs=service_logs, now=datetime.utcnow().date())

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
        # Account Settings
        email = request.form.get("email")
        password = request.form.get("password")

        if email and email != current_user.email:
            current_user.email = email

        if password:
            current_user.password = password  # Make sure to hash in production

        # Collect machine data
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

        # Update machine info
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

    # Load machines
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
            flash("Login successful", "success")
            return redirect(next_url or url_for("routes.user_dashboard"))
        else:
            flash("Invalid credentials", "danger")
    return render_template("login.html", next=next_url)

@routes.route("/user/dashboard", methods=["GET", "POST"])
@login_required
def user_dashboard():
    if current_user.role != "user":
        return redirect(url_for("routes.user_login"))

    if request.method == "POST":
        batch_id = request.form.get("batch_id")

        # Use default settings if machine name/type are not explicitly provided in form
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
        batch_data.append({
            "id": batch.id,
            "created_at": batch.created_at,
            "machine": machine,
            "qr_codes": qr_codes,
            "tags": tags
        })

    return render_template("user_dashboard.html", batches=batch_data)

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

@routes.route("/user/create-subuser", methods=["GET", "POST"])
@login_required
def create_subuser():
    if current_user.role != "user":
        abort(403)

    machines = Machine.query.join(QRBatch).filter(QRBatch.owner_id == current_user.id).all()

    if request.method == "POST":
        name = request.form["name"]
        machine_id = request.form["machine_id"]

        # Generate a 7-digit unique static subuser_id
        while True:
            subuser_id = ''.join(random.choices(string.digits, k=7))
            if not User.query.filter_by(subuser_id=subuser_id).first():
                break

        new_subuser = User(
            name=name,
            role="subuser",
            subuser_id=subuser_id,
            machine_id=machine_id
        )
        db.session.add(new_subuser)
        db.session.commit()
        flash(f"Sub-user created! Their login ID is: {subuser_id}", "success")
        return redirect(url_for("routes.user_dashboard"))

    return render_template("create_subuser.html", machines=machines)

@routes.route("/subuser/login", methods=["GET", "POST"])
def subuser_login():
    if request.method == "POST":
        subuser_id = request.form["subuser_id"]
        subuser = User.query.filter_by(role="subuser", subuser_id=subuser_id).first()
        if subuser:
            session["subuser_id"] = subuser_id
            return redirect(url_for("routes.subuser_machine"))
        else:
            flash("Invalid Sub-user ID", "danger")

    return render_template("subuser_login.html")

@routes.route("/subuser/machine")
def subuser_machine():
    subuser_id = session.get("subuser_id")
    if not subuser_id:
        return redirect(url_for("routes.subuser_login"))

    subuser = User.query.filter_by(role="subuser", subuser_id=subuser_id).first()
    if not subuser:
        return redirect(url_for("routes.subuser_login"))

    machine = Machine.query.get(subuser.machine_id)
    if not machine:
        flash("Machine not found", "danger")
        return redirect(url_for("routes.subuser_login"))

    return render_template("subuser_machine.html", machine=machine, subuser=subuser)

@routes.route("/settings/delete-subuser/<int:subuser_id>", methods=["POST"])
@login_required
def delete_subuser(subuser_id):
    subuser = User.query.get_or_404(subuser_id)
    if subuser.role != "subuser":
        flash("Invalid action.", "danger")
        return redirect(url_for("routes.user_settings"))

    db.session.delete(subuser)
    db.session.commit()
    flash("Sub-user deleted.", "success")
    return redirect(url_for("routes.user_settings"))
    

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

@routes.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("routes.home"))
