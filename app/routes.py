from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, QRBatch, QRCode, Machine, QRTag, NeedleChange
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
        return redirect(url_for("routes.user_login", next=url_for("routes.sub_tag_view", sub_tag_id=sub_tag_id)))
    return redirect(url_for("routes.sub_tag_view", sub_tag_id=sub_tag_id))


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


@routes.route("/signup", methods=["GET", "POST"])
def user_signup():
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        existing_user = User.query.filter_by(email=email).first()
        if existing_user:
            flash("Email already registered", "danger")
            return redirect(url_for("routes.user_signup"))

        new_user = User(email=email, password=password, role="user")
        db.session.add(new_user)
        db.session.commit()
        flash("Signup successful! Please login.", "success")
        return redirect(url_for("routes.user_login"))

    return render_template("signup.html")


@routes.route("/login", methods=["GET", "POST"])
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
        name = request.form.get("name")
        mtype = request.form.get("type")

        existing = Machine.query.filter_by(batch_id=batch_id).first()
        if existing:
            flash("A machine is already assigned to this batch.", "danger")
        else:
            machine = Machine(batch_id=batch_id, name=name, type=mtype)
            db.session.add(machine)
            db.session.commit()
            flash("Machine added successfully.", "success")

    user_batches = QRBatch.query.filter_by(owner_id=current_user.id).all()
    batch_data = []

    for batch in user_batches:
        machine = Machine.query.filter_by(batch_id=batch.id).first()
        qr_codes = QRCode.query.filter_by(batch_id=batch.id).all()
        tags = QRTag.query.filter_by(batch_id=batch.id).all()

        master_qr = next((q for q in qr_codes if q.qr_type == 'master'), None)
        service_qr = next((q for q in qr_codes if q.qr_type == 'service'), None)
        sub_qrs = [q for q in qr_codes if q.qr_type.startswith('sub')]

        batch_data.append({
            "id": batch.id,
            "created_at": batch.created_at,
            "machine": machine,
            "master_qr": master_qr,
            "service_qr": service_qr,
            "sub_qrs": sub_qrs,
            "tags": tags
        })

    return render_template("user_dashboard.html", batches=batch_data)


@routes.route("/sub/<int:sub_tag_id>", methods=["GET", "POST"])
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

    logs = (
        NeedleChange.query
        .filter_by(sub_tag_id=sub_tag.id)
        .order_by(NeedleChange.timestamp.desc())
        .all()
    )

    last_change_dict = {}
    for log in logs:
        if log.needle_number not in last_change_dict:
            last_change_dict[log.needle_number] = log

    return render_template("sub_tag_view.html",
                           sub_tag=sub_tag,
                           last_change_dict=last_change_dict,
                           now=datetime.utcnow().date())


@routes.route("/admin/login", methods=["GET", "POST"])
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
    return render_template("admin_dashboard.html", batches=batches)


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


@routes.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("routes.home"))
