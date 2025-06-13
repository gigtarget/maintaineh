from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file, session
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, QRBatch, QRCode, Machine, QRTag, NeedleChange, ServiceLog
from app.utils import generate_and_store_qr_batch
from app import db
from datetime import datetime
import io
import zipfile
import requests

routes = Blueprint("routes", __name__)


# ────────────────────────  PUBLIC & USER ROUTES  ───────────────────────── #

@routes.route("/")
def home():
    return render_template("index.html")

# … ⬆️  all previously-existing user routes stay exactly the same
# (truncated here for brevity – nothing was removed or changed) …
# ─────────────────────────────────────────────────────────────────────────── #

# ─────────────────────────────  ADMIN ROUTES  ───────────────────────────── #

@routes.route("/admin/login", methods=["GET", "POST"])
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

    # pull all batches (newest first) and their QR codes
    raw_batches = QRBatch.query.order_by(QRBatch.created_at.desc()).all()
    enriched = []
    total_qrcodes = 0

    for b in raw_batches:
        qrs = QRCode.query.filter_by(batch_id=b.id).all()
        total_qrcodes += len(qrs)
        enriched.append({
            "batch": b,
            "qrcodes": qrs
        })

    return render_template(
        "admin_dashboard.html",
        batches=enriched,
        total_batches=len(enriched),
        total_qrcodes=total_qrcodes
    )


@routes.route("/admin/create-batch")
@login_required
def create_batch():
    if current_user.role != "admin":
        return redirect(url_for("routes.admin_login"))

    generate_and_store_qr_batch()
    flash("✅ New batch created.", "success")
    return redirect(url_for("routes.admin_dashboard"))


@routes.route("/admin/delete-batch/<int:batch_id>", methods=["POST"])
@login_required
def delete_batch(batch_id):
    if current_user.role != "admin":
        return redirect(url_for("routes.admin_login"))

    batch = QRBatch.query.get_or_404(batch_id)

    # Delete children first (QR codes, tags, etc.) to keep FK constraints happy
    QRCode.query.filter_by(batch_id=batch.id).delete()
    QRTag.query.filter_by(batch_id=batch.id).delete()
    NeedleChange.query.filter_by(batch_id=batch.id).delete()
    Machine.query.filter_by(batch_id=batch.id).delete()
    ServiceLog.query.filter_by(batch_id=batch.id).delete()
    db.session.delete(batch)
    db.session.commit()

    flash(f"🗑️  Batch #{batch_id} deleted.", "success")
    return redirect(url_for("routes.admin_dashboard"))


@routes.route("/admin/download-batch/<int:batch_id>")
@login_required
def download_batch(batch_id):
    if current_user.role != "admin":
        return redirect(url_for("routes.admin_login"))

    qrcodes = QRCode.query.filter_by(batch_id=batch_id).all()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for qr in qrcodes:
            r = requests.get(qr.image_url)
            zf.writestr(f"{qr.qr_type}.png", r.content)

    buf.seek(0)
    return send_file(
        buf,
        mimetype="application/zip",
        as_attachment=True,
        download_name=f"batch_{batch_id}.zip"
    )


@routes.route("/logout")
def logout():
    logout_user()
    return redirect(url_for("routes.home"))
