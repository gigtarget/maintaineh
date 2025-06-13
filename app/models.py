from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, date

db = SQLAlchemy()

class User(UserMixin, db.Model):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(150), unique=True, nullable=False)
    password = db.Column(db.String(150), nullable=False)
    role = db.Column(db.String(20), nullable=False, default="user")
    claimed_batches = db.relationship("QRBatch", backref="owner", lazy=True)

class QRBatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=True)
    qr_tags = db.relationship("QRTag", backref="batch", lazy=True)
    needle_changes = db.relationship("NeedleChange", backref="batch", lazy=True)
    qr_codes = db.relationship("QRCode", backref="batch", lazy=True)
    machine = db.relationship("Machine", backref="batch", uselist=False)

class QRTag(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    tag_type = db.Column(db.String(20))
    batch_id = db.Column(db.Integer, db.ForeignKey("qr_batch.id"))
    qr_url = db.Column(db.String(255))
    needle_changes = db.relationship("NeedleChange", backref="sub_tag", lazy=True)

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
    batch_id = db.Column(db.Integer, db.ForeignKey("qr_batch.id"))
    name = db.Column(db.String(100))
    type = db.Column(db.String(100))

class ServiceLog(db.Model):
    __tablename__ = 'servicelog'
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey("qr_batch.id"))
    sub_tag_id = db.Column(db.Integer, db.ForeignKey("qr_tag.id"))
    part_name = db.Column(db.String(100), nullable=False)
    description = db.Column(db.Text)
    warranty_till = db.Column(db.Date)  # instead of db.String or character
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)

class Batch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    # Link to the user who claimed the batch
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=True)
    user = db.relationship('User', backref='claimed_batches')

    # One-to-One with machine (optional)
    machine = db.relationship('Machine', backref='batch', uselist=False)

    qrcodes = db.relationship('QRCode', backref='batch', lazy=True)
