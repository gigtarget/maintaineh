from app import db
from flask_login import UserMixin
from datetime import datetime

class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    email = db.Column(db.String(120), unique=True, nullable=False)
    password = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), default="user")
    batches = db.relationship('QRBatch', backref='user', lazy=True)

class QRBatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'))
    qrcodes = db.relationship('QRCode', backref='batch', lazy=True)
    machines = db.relationship('Machine', backref='batch', lazy=True)

class QRCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('qr_batch.id'), nullable=False)
    qr_type = db.Column(db.String(20))
    image_url = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

class Machine(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('qr_batch.id'), nullable=False)
    name = db.Column(db.String(100), nullable=False)
    type = db.Column(db.String(50), nullable=False)
    added_at = db.Column(db.DateTime, default=datetime.utcnow)
