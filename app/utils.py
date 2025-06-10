import os
import qrcode
import cloudinary
import cloudinary.uploader
from io import BytesIO
from app import db
from app.models import QRBatch, QRCode, QRTag

# ✅ Cloudinary Configuration
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

# ✅ Use Railway subdomain as base
BASE_URL = "https://web-production-a8c0.up.railway.app"

def generate_and_store_qr_batch():
    print("👉 Creating new QR batch...")

    # Create new batch
    batch = QRBatch()
    db.session.add(batch)
    db.session.commit()

    # Define QR types: 1 master, 1 service, 8 sub tags
    qr_types = ['master', 'service'] + [f"sub{i}" for i in range(1, 9)]

    for qr_type in qr_types:
        # Create QRTag record in database first
        qr_tag = QRTag(tag_type=qr_type, batch_id=batch.id)
        db.session.add(qr_tag)
        db.session.commit()  # Commit so qr_tag.id is generated

        # Decide scan URL based on tag type
        if qr_type == "master":
            qr_url = f"{BASE_URL}/scan/master/{batch.id}"
        elif qr_type.startswith("sub"):
            qr_url = f"{BASE_URL}/scan/sub/{qr_tag.id}"
        else:  # service
            qr_url = f"{BASE_URL}/scan/service/{qr_tag.id}"

        print(f"➡️ Generating QR for: {qr_url}")

        # Generate QR image
        qr_img = qrcode.make(qr_url)
        buffer = BytesIO()
        qr_img.save(buffer)
        buffer.seek(0)

        try:
            # Upload to Cloudinary
            upload_result = cloudinary.uploader.upload(
                buffer,
                folder=f"maintaineh/batch_{batch.id}",
                public_id=qr_type,
                overwrite=True,
                resource_type="image"
            )
            image_url = upload_result.get("secure_url")
            print(f"✅ Uploaded {qr_type} → {image_url}")

            # Update QRTag with URL
            qr_tag.qr_url = image_url
            db.session.commit()

            # Optional: If still using QRCode model
            qr_code = QRCode(
                batch_id=batch.id,
                qr_type=qr_type,
                image_url=image_url
            )
            db.session.add(qr_code)

        except Exception as e:
            print(f"❌ Cloudinary upload failed for {qr_type}: {e}")
            raise e

    db.session.commit()
    return batch.id
