import os
import qrcode
import cloudinary
import cloudinary.uploader
from io import BytesIO
from PIL import Image, ImageDraw, ImageFont
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

def generate_custom_qr_image(data, tag_type, logo_path='app/static/logo/logo.png'):
    # Create base image
    img_width, img_height = 800, 1200
    base = Image.new('RGB', (img_width, img_height), 'white')
    draw = ImageDraw.Draw(base)

    # Generate QR code
    qr = qrcode.QRCode(
        version=2,
        error_correction=qrcode.constants.ERROR_CORRECT_H,
        box_size=10,
        border=4,
    )
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
    qr_img = qr_img.resize((600, 600))

    # Create circular hole in center
    mask = Image.new('L', qr_img.size, 255)
    draw_mask = ImageDraw.Draw(mask)
    center = (qr_img.size[0] // 2, qr_img.size[1] // 2)
    radius = 120
    draw_mask.ellipse([
        (center[0] - radius, center[1] - radius),
        (center[0] + radius, center[1] + radius)
    ], fill=0)
    qr_img.putalpha(mask)

    # Paste QR into base image
    base.paste(qr_img, ((img_width - 600) // 2, 80), qr_img)

    # Add tag type text
    try:
        font = ImageFont.truetype("arial.ttf", 48)
    except:
        font = ImageFont.load_default()
    tag_text = tag_type.upper()
    w, h = draw.textsize(tag_text, font=font)
    draw.text(((img_width - w) / 2, 720), tag_text, fill="black", font=font)

    # Add logo at bottom
    if os.path.exists(logo_path):
        logo = Image.open(logo_path).convert("RGBA")
        logo.thumbnail((300, 300))
        base.paste(logo, ((img_width - logo.width) // 2, 900), logo)

    return base

def generate_and_store_qr_batch():
    print("👉 Creating new QR batch...")

    # Create new batch
    batch = QRBatch()
    db.session.add(batch)
    db.session.commit()

    # Define QR types
    qr_types = ['master', 'service'] + [f"sub{i}" for i in range(1, 9)]

    for qr_type in qr_types:
        # Create QRTag in DB
        qr_tag = QRTag(tag_type=qr_type, batch_id=batch.id)
        db.session.add(qr_tag)
        db.session.commit()

        # Determine URL
        if qr_type == "master":
            qr_url = f"{BASE_URL}/scan/master/{batch.id}"
        elif qr_type.startswith("sub"):
            qr_url = f"{BASE_URL}/scan/sub/{qr_tag.id}"
        else:
            qr_url = f"{BASE_URL}/scan/service/{qr_tag.id}"

        print(f"➡️ Generating QR for: {qr_url}")

        # Generate portrait-style custom QR image
        img = generate_custom_qr_image(qr_url, qr_type)

        buffer = BytesIO()
        img.save(buffer, format="PNG")
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

            # Update QRTag
            qr_tag.qr_url = image_url
            db.session.commit()

            # Optional: Save to QRCode model
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
