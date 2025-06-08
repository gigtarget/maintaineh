from flask import Blueprint, render_template, redirect, url_for, flash, request, send_file
from flask_login import login_user, logout_user, login_required, current_user
from app.models import User, QRBatch, QRCode
from app.utils import generate_and_store_qr_batch
from app import db
import io
import zipfile
import requests

routes = Blueprint("routes", __name__)

@routes.route("/")
def home():
    return render_template("index.html")

# ---------- USER AUTH ----------

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
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        user = User.query.filter_by(email=email, role="user").first()

        if user and user.password == password:
            login_user(user)
            flash("Login successful", "success")
            return redirect(url_for("routes.user_dashboard"))
        else:
            flash("Invalid credentials", "danger")

    return render_template("login.html")

@routes.route("/user/dashboard")
@login_required
def user_dashboard():
    if current_user.role != "user":
        return redirect(url_for("routes.user_login"))
    return render_template("user_dashboard.html")

# ---------- ADMIN AUTH ----------

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
