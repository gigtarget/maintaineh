import os
import qrcode
import cloudinary
import cloudinary.uploader
from io import BytesIO
from app import db
from app.models import QRBatch, QRCode

# ✅ Cloudinary Config
cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

def generate_and_store_qr_batch():
    print("👉 Creating new QR batch...")
    batch = QRBatch()
    db.session.add(batch)
    db.session.commit()

    qr_types = ['master', 'service'] + [f"sub{i}" for i in range(1, 9)]

    for qr_type in qr_types:
        qr_data = f"https://maintaineh.app/scan/{qr_type}/{batch.id}"
        print(f"➡️ Generating QR for: {qr_data}")

        qr_img = qrcode.make(qr_data)
        buffer = BytesIO()
        qr_img.save(buffer)
        buffer.seek(0)

        try:
            upload_result = cloudinary.uploader.upload(
                buffer,
                folder=f"maintaineh/batch_{batch.id}",
                public_id=qr_type,
                overwrite=True,
                resource_type="image"
            )
            image_url = upload_result.get("secure_url")
            print(f"✅ Uploaded {qr_type} → {image_url}")

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
