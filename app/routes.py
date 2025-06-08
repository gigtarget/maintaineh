from flask import render_template, redirect, url_for, request, session, send_from_directory, flash
from flask_login import login_required
from app import db
from flask import Blueprint
import os
from app.utils import generate_qr_batch

routes = Blueprint('routes', __name__)

ADMIN_USERNAME = 'admin@maintaineh.com'
ADMIN_PASSWORD = 'securebatch123'

@routes.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        email = request.form['email']
        password = request.form['password']
        if email == ADMIN_USERNAME and password == ADMIN_PASSWORD:
            session['admin_logged_in'] = True
            return redirect(url_for('routes.admin_dashboard'))
        else:
            flash('Invalid credentials')
    return render_template('admin_login.html')

@routes.route('/admin/dashboard')
def admin_dashboard():
    if not session.get('admin_logged_in'):
        return redirect(url_for('routes.admin_login'))

    batches = os.listdir('app/static/qrcodes')
    batches = sorted(batches, reverse=True)
    return render_template('admin_dashboard.html', batches=batches)

@routes.route('/admin/create-batch')
def create_batch():
    if not session.get('admin_logged_in'):
        return redirect(url_for('routes.admin_login'))

    generate_qr_batch()
    flash("✅ New batch generated successfully!")
    return redirect(url_for('routes.admin_dashboard'))

@routes.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('routes.admin_login'))

@routes.route('/qrcodes/<path:filename>')
def serve_qr(filename):
    return send_from_directory('static/qrcodes', filename)
