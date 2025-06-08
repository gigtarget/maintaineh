from flask import render_template, request, redirect, url_for, flash, session, send_file
from app import app, db
from app.models import QRBatch, QRCode
from app.utils import generate_and_store_qr_batch
from io import BytesIO
import requests
import zipfile
import os

# ---------------- Admin Login ----------------
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if request.method == "POST":
        email = request.form.get("email")
        password = request.form.get("password")

        if email == os.getenv("ADMIN_EMAIL") and password == os.getenv("ADMIN_PASSWORD"):
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        else:
            flash("Invalid admin credentials.", "danger")

    return render_template("admin_login.html")

# ---------------- Admin Logout ----------------
@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))

# ---------------- Admin Dashboard ----------------
@app.route("/admin/dashboard")
def admin_dashboard():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    batches = QRBatch.query.order_by(QRBatch.created_at.desc()).all()
    return render_template("admin_dashboard.html", batches=batches)

# ---------------- Create New QR Batch ----------------
@app.route("/admin/create-batch")
def create_batch():
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    try:
        batch_id = generate_and_store_qr_batch()
        flash(f"✅ Batch #{batch_id} created successfully!", "success")
    except Exception as e:
        print(f"❌ Error generating batch: {e}")
        flash("❌ Failed to create new batch.", "danger")

    return redirect(url_for("admin_dashboard"))

# ---------------- Download QR Batch ----------------
@app.route("/admin/download/<int:batch_id>")
def download_batch(batch_id):
    if not session.get("admin_logged_in"):
        return redirect(url_for("admin_login"))

    batch = QRBatch.query.get_or_404(batch_id)
    qr_images = batch.qrcodes

    zip_stream = BytesIO()
    with zipfile.ZipFile(zip_stream, 'w') as zipf:
        for qr in qr_images:
            response = requests.get(qr.image_url)
            if response.status_code == 200:
                file_ext = qr.image_url.split('.')[-1].split('?')[0]
                filename = f"{qr.qr_type}.{file_ext}"
                zipf.writestr(filename, response.content)

    zip_stream.seek(0)
    return send_file(
        zip_stream,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'batch_{batch_id}_qrcodes.zip'
    )
