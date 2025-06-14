import os
import qrcode
from io import BytesIO
import cloudinary.uploader
from PIL import Image, ImageDraw, ImageFont
from app import db
from app.models import QRBatch, QRCode, QRTag

BASE_URL = "https://www.tokatap.com"

cloudinary.config(
    cloud_name=os.getenv("CLOUDINARY_CLOUD_NAME"),
    api_key=os.getenv("CLOUDINARY_API_KEY"),
    api_secret=os.getenv("CLOUDINARY_API_SECRET")
)

def generate_custom_qr_image(data, tag_type, logo_path='app/static/logo/qr code logo.jpg'):
    img_width, img_height = 800, 1200
    base = Image.new('RGBA', (img_width, img_height), (255, 255, 255, 0))

    # ✅ Rounded white card background
    card = Image.new('RGB', (img_width, img_height), 'white')
    mask = Image.new('L', (img_width, img_height), 0)
    draw_mask = ImageDraw.Draw(mask)
    draw_mask.rounded_rectangle([0, 0, img_width, img_height], radius=40, fill=255)
    card.putalpha(mask)
    base.paste(card, (0, 0), mask)

    draw = ImageDraw.Draw(base)

    # ✅ QR Code with central hole
    qr = qrcode.QRCode(version=2, error_correction=qrcode.constants.ERROR_CORRECT_H, box_size=10, border=4)
    qr.add_data(data)
    qr.make(fit=True)
    qr_img = qr.make_image(fill_color="black", back_color="white").convert('RGB')
    qr_img = qr_img.resize((600, 600))

    qr_mask = Image.new('L', qr_img.size, 255)
    draw_qr_mask = ImageDraw.Draw(qr_mask)
    cx, cy, r = qr_img.size[0] // 2, qr_img.size[1] // 2, 150  # ⬅️ same as HTML
    draw_qr_mask.ellipse((cx - r, cy - r, cx + r, cy + r), fill=0)
    qr_img.putalpha(qr_mask)

    base.paste(qr_img, ((img_width - 600) // 2, 60), qr_img)

    # ✅ Tag type (larger font, bold)
    try:
        font = ImageFont.truetype("arial.ttf", 64)
    except:
        font = ImageFont.load_default()
    text = tag_type.upper()
    bbox = font.getbbox(text)
    w = bbox[2] - bbox[0]
    draw.text(((img_width - w) // 2, 700), text, font=font, fill="black")

    # ✅ Logo as box image
    try:
        logo_img = Image.open(logo_path).convert("RGBA")
        logo_img.thumbnail((260, 190))  # ⬅️ logo box
        base.paste(logo_img, ((img_width - logo_img.width) // 2, 800), logo_img)
    except Exception as e:
        print(f"❌ Logo error: {e}")

    return base.convert("RGB")


def generate_and_store_qr_batch():
    print("👉 Creating new QR batch...")
    batch = QRBatch()
    db.session.add(batch)
    db.session.commit()

    qr_types = ['master', 'service'] + [f"sub{i}" for i in range(1, 9)]

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
