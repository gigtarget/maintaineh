import os
import qrcode
from io import BytesIO
import cloudinary.uploader
from PIL import Image, ImageDraw, ImageFont
from app import db
from app.models import QRBatch, QRCode, QRTag, NeedleChange, ServiceLog
from datetime import datetime

BASE_URL = "https://www.tokatap.com"

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

def generate_custom_qr_image(data, tag_type, logo_path='app/static/logo/qr code logo.jpg'):
    img_width, img_height = 800, 1200
    base = Image.new('RGBA', (img_width, img_height), (255, 255, 255, 0))
    card = Image.new('RGB', (img_width, img_height), 'white')
    mask = Image.new('L', (img_width, img_height), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle([0, 0, img_width, img_height], radius=40, fill=255)
    card.putalpha(mask)
    base.paste(card, (0, 0), mask)
    draw = ImageDraw.Draw(base)
    qr = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
    qr_img = qr_img.resize((800, 800))
    qr_img.putalpha(255)
    base.paste(qr_img, ((img_width - qr_img.width) // 2, 60), qr_img)
    try:
        font = ImageFont.truetype("app/fonts/Agrandir.ttf", 70)
    except Exception as e:
        print(f"⚠️ Font load failed: {e}")
        font = ImageFont.load_default()
    if tag_type.lower().startswith("sub"):
        display_text = f"HEAD {tag_type[3:]}"
    else:
        display_text = tag_type.upper()
    bbox = font.getbbox(display_text)
    w = bbox[2] - bbox[0]
    draw.text(((img_width - w) // 2, 850), display_text, font=font, fill="black")
    try:
        logo_img = Image.open(logo_path).convert("RGBA")
        logo_img = logo_img.resize((550, 140))
        base.paste(logo_img, ((img_width - logo_img.width) // 2, 980), logo_img)
    except Exception as e:
        print(f"❌ Logo error: {e}")
    return base.convert("RGB")

def generate_and_store_qr_batch(user_id=None, num_heads=8):
    """
    Create a QRBatch and all QRTags (Master, Service, 8 Subs) for the specified user.
    Returns the batch id.
    """
    print("👉 Creating new QR batch...")
    batch = QRBatch(owner_id=user_id, created_at=datetime.utcnow())  # Ensure owner_id is the user
    db.session.add(batch)
    db.session.commit()

    qr_types = ['master', 'service'] + [f"sub{i}" for i in range(1, num_heads + 1)]

    for qr_type in qr_types:
        qr_tag = QRTag(tag_type=qr_type, batch_id=batch.id)
        db.session.add(qr_tag)
        db.session.commit()

        if qr_type == "master":
            qr_url = f"{BASE_URL}/scan/master/{batch.id}"
        elif qr_type.startswith("sub"):
            qr_url = f"{BASE_URL}/scan/sub/{qr_tag.id}"
        else:
            qr_url = f"{BASE_URL}/scan/service/{qr_tag.id}"

        print(f"➡️ Generating QR for: {qr_url}")
        qr_img = generate_custom_qr_image(qr_url, qr_type)
        buffer = BytesIO()
        qr_img.save(buffer, format="PNG")
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

            qr_tag.qr_url = qr_url
            qr_tag.image_url = image_url
            db.session.commit()

            qr_code = QRCode(
                batch_id=batch.id,
                qr_type=qr_type,
                image_url=image_url,
                qr_url=qr_url
            )
            db.session.add(qr_code)

        except Exception as e:
            print(f"❌ Upload failed: {e}")
            raise e

    db.session.commit()
    return batch.id


def sync_qr_heads(batch_id, num_heads):
    """Ensure the batch has QR codes for the specified number of heads."""
    existing = [t for t in QRTag.query.filter_by(batch_id=batch_id).all() if t.tag_type.startswith('sub')]
    current = len(existing)

    if num_heads > current:
        for i in range(current + 1, num_heads + 1):
            qr_type = f"sub{i}"
            qr_tag = QRTag(tag_type=qr_type, batch_id=batch_id)
            db.session.add(qr_tag)
            db.session.commit()

            qr_url = f"{BASE_URL}/scan/sub/{qr_tag.id}"
            qr_img = generate_custom_qr_image(qr_url, qr_type)
            buf = BytesIO()
            qr_img.save(buf, format="PNG")
            buf.seek(0)
            try:
                result = cloudinary.uploader.upload(
                    buf,
                    folder=f"maintaineh/batch_{batch_id}",
                    public_id=qr_type,
                    overwrite=True,
                    resource_type="image",
                )
                image_url = result.get("secure_url")
                qr_tag.qr_url = qr_url
                qr_tag.image_url = image_url
                db.session.commit()

                qr_code = QRCode(batch_id=batch_id, qr_type=qr_type, image_url=image_url, qr_url=qr_url)
                db.session.add(qr_code)
            except Exception as e:
                print(f"❌ Upload failed: {e}")
                raise e
        db.session.commit()
    elif num_heads < current:
        for i in range(num_heads + 1, current + 1):
            qr_type = f"sub{i}"
            qr_tag = QRTag.query.filter_by(batch_id=batch_id, tag_type=qr_type).first()
            if qr_tag:
                NeedleChange.query.filter_by(sub_tag_id=qr_tag.id).delete()
                ServiceLog.query.filter_by(sub_tag_id=qr_tag.id).delete()
                qr_code = QRCode.query.filter_by(batch_id=batch_id, qr_type=qr_type).first()
                if qr_code:
                    db.session.delete(qr_code)
                db.session.delete(qr_tag)
        db.session.commit()
