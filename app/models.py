from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, date

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")
    name = db.Column(db.String(100), nullable=False)
    company_name = db.Column(db.String(100))
    subuser_id = db.Column(db.String(10), unique=True, nullable=True)
    machine_id = db.Column(db.Integer, db.ForeignKey('machine.id'), nullable=True)

    
    # New preferences
    default_machine_name = db.Column(db.String(100))
    default_machine_location = db.Column(db.String(100))

    # One-to-many: user -> claimed batches
    claimed_batches = db.relationship("QRBatch", backref="owner", lazy=True)


class QRBatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    
    # Foreign key to User who claimed the batch
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)

    # Relationships
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
    batch_id = db.Column(db.Integer, db.ForeignKey("qr_batch.id"))
    qr_type = db.Column(db.String(20))
    image_url = db.Column(db.String(255))


class NeedleChange(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("qr_batch.id"))
    sub_tag_id = db.Column(db.Integer, db.ForeignKey("qr_tag.id"))
    needle_number = db.Column(db.Integer, nullable=False)
    needle_type = db.Column(db.Integer, nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)


class Machine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("qr_batch.id"), nullable=False)
    name = db.Column(db.String(100))
    type = db.Column(db.String(100))

class SubUser(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120))
    static_id = db.Column(db.String(10), unique=True)
    machine_id = db.Column(db.Integer, db.ForeignKey('machine.id'))
    created_by = db.Column(db.Integer, db.ForeignKey('user.id'))

class ServiceLog(db.Model):
    __tablename__ = 'servicelog'
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("qr_batch.id"))
    sub_tag_id = db.Column(db.Integer, db.ForeignKey("qr_tag.id"))
    part_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    warranty_till = db.Column(db.Date)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
