import qrcode
import cloudinary
import cloudinary.uploader
import io
import os
from datetime import datetime
from app import db
from app.models import QRBatch, QRCode

# Cloudinary config using Railway environment variables
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

def generate_and_store_qr_batch():
    # Step 1: Create new batch in DB
    new_batch = QRBatch()
    db.session.add(new_batch)
    db.session.commit()

    # Step 2: Labels and QR types
    qr_types = ['master', 'service'] + [f'sub{i+1}' for i in range(8)]

    for qr_type in qr_types:
        # Sample encoded URL — can later be dynamic
        qr_data = f"https://maintaineh.app/{qr_type}/{new_batch.id}"

        # Generate QR image in memory
        qr_img = qrcode.make(qr_data)
        buffered = io.BytesIO()
        qr_img.save(buffered, format="PNG")
        buffered.seek(0)

        # Upload to Cloudinary
        result = cloudinary.uploader.upload(buffered, folder=f"maintaineh/batch_{new_batch.id}", public_id=qr_type)

        # Save to DB
        new_qr = QRCode(
            batch_id=new_batch.id,
            qr_type=qr_type,
            image_url=result['secure_url']
        )
        db.session.add(new_qr)

    db.session.commit()
    return new_batch.id
