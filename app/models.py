from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, date

db = SQLAlchemy()

# -------------------------
# 🔐 USER MODEL
# -------------------------
class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")
    name = db.Column(db.String(100), nullable=False)
    company_name = db.Column(db.String(100))
    mobile = db.Column(db.String(20))

    security_question = db.Column(db.String(255))
    security_answer = db.Column(db.String(255))

    default_machine_name = db.Column(db.String(100))
    default_machine_location = db.Column(db.String(100))

    claimed_batches = db.relationship("QRBatch", backref="owner", lazy=True)

# -------------------------
# 🧾 QR BATCH + TAGS
# -------------------------
class QRBatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"))

    qr_tags = db.relationship("QRTag", backref="batch", lazy=True)
    needle_changes = db.relationship("NeedleChange", backref="batch", lazy=True)
    qr_codes = db.relationship("QRCode", backref="batch", lazy=True)
    machine = db.relationship("Machine", backref="batch", uselist=False)
    service_logs = db.relationship("ServiceLog", backref="batch", lazy=True)

class QRTag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tag_type = db.Column(db.String(20))
    batch_id = db.Column(db.Integer, db.ForeignKey("qr_batch.id"))
    qr_url = db.Column(db.String(255))

    needle_changes = db.relationship("NeedleChange", backref="sub_tag", lazy=True)
    service_logs = db.relationship("ServiceLog", backref="sub_tag", lazy=True)

class QRCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('qr_batch.id'))
    qr_type = db.Column(db.String(50))
    image_url = db.Column(db.String(500))
    qr_url = db.Column(db.String(500))

# -------------------------
# 🧵 MACHINE + HEAD LOGS
# -------------------------
class Machine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("qr_batch.id"), nullable=False)
    name = db.Column(db.String(100))
    type = db.Column(db.String(100))
    under_maintenance = db.Column(db.Boolean, default=False)
    # New: user configurable maintenance intervals
    oil_interval_hours = db.Column(db.Integer, default=24)
    lube_interval_days = db.Column(db.Integer, default=7)
    grease_interval_months = db.Column(db.Integer, default=3)
    # configurable heads and needles
    num_heads = db.Column(db.Integer, default=8)
    needles_per_head = db.Column(db.Integer, default=15)

    maintenance_logs = db.relationship("DailyMaintenance", backref="machine", lazy=True)
    service_requests = db.relationship("ServiceRequest", backref="machine", lazy=True)

class NeedleChange(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("qr_batch.id"))
    sub_tag_id = db.Column(db.Integer, db.ForeignKey("qr_tag.id"))
    needle_number = db.Column(db.Integer, nullable=False)
    needle_type = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

# -------------------------
# 👥 SUB USERS
# -------------------------
class SubUser(db.Model):
    __tablename__ = 'sub_user'
    id = db.Column(db.Integer, primary_key=True)
    static_id = db.Column(db.String(10), unique=True)
    name = db.Column(db.String(120))
    parent_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    assigned_machine_id = db.Column(db.Integer, db.ForeignKey('machine.id'))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    assigned_machine = db.relationship('Machine', backref='subusers', foreign_keys=[assigned_machine_id])

# -------------------------
# 🧰 SERVICE & MAINTENANCE LOGS
# -------------------------
class ServiceLog(db.Model):
    __tablename__ = 'servicelog'
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("qr_batch.id"))
    sub_tag_id = db.Column(db.Integer, db.ForeignKey("qr_tag.id"))
    part_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    warranty_till = db.Column(db.Date)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class DailyMaintenance(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    machine_id = db.Column(db.Integer, db.ForeignKey("machine.id"), nullable=False)
    date = db.Column(db.Date, default=date.today)
    oiled = db.Column(db.Boolean, default=False)

# -------------------------
# 🚨 SERVICE REQUEST ALERTS
# -------------------------
class ServiceRequest(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    machine_id = db.Column(db.Integer, db.ForeignKey('machine.id'))
    subuser_id = db.Column(db.Integer, db.ForeignKey('sub_user.id'))
    heads = db.Column(db.Integer, nullable=False)
    issue = db.Column(db.Text, nullable=True)
    resolved = db.Column(db.Boolean, default=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    resolved_at = db.Column(db.Date)  # ✅ New column


# -------------------------
# ✅ ACTIONS LOGGED BY SUB USERS OR MAIN USER
# -------------------------
class SubUserAction(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    subuser_id = db.Column(db.Integer, db.ForeignKey('sub_user.id'), nullable=True)  # can be NULL if logged by main user
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)         # NEW: main user id, can be NULL if subuser logs
    machine_id = db.Column(db.Integer, db.ForeignKey('machine.id'), nullable=False)
    action_type = db.Column(db.String(20))     # "oiling", "lube", "service"
    status = db.Column(db.String(20))          # "done", "pending", "completed"
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


# -------------------------
# 🔑 PASSWORD RESET TOKENS
# -------------------------
class PasswordResetToken(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    token = db.Column(db.String(64), unique=True, nullable=False)
    expires_at = db.Column(db.DateTime, nullable=False)
    used = db.Column(db.Boolean, default=False)


# -------------------------
# 📈 GENERAL ACTIVITY LOG
# -------------------------
class ActivityLog(db.Model):
    """Central log for notable user actions."""
    id = db.Column(db.Integer, primary_key=True)
    event_type = db.Column(db.String(50))
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    subuser_id = db.Column(db.Integer, db.ForeignKey('sub_user.id'), nullable=True)
    machine_id = db.Column(db.Integer, db.ForeignKey('machine.id'), nullable=True)
    description = db.Column(db.String(255))
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

