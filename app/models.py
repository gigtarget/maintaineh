from app import db
from datetime import datetime

class QRBatch(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    qrcodes = db.relationship('QRCode', backref='batch', lazy=True)

class QRCode(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    batch_id = db.Column(db.Integer, db.ForeignKey('qr_batch.id'), nullable=False)  # ✅ Fixed line
    qr_type = db.Column(db.String(20))  # master, service, sub1...sub8
    image_url = db.Column(db.String(255))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
