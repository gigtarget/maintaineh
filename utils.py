import qrcode
import os
from datetime import datetime

def generate_qr_batch():
    base_path = 'app/static/qrcodes'
    timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
    batch_path = os.path.join(base_path, f'batch_{timestamp}')
    os.makedirs(batch_path, exist_ok=True)

    labels = ['Master QR', 'Service QR'] + [f'Sub QR {i+1}' for i in range(8)]

    for i, label in enumerate(labels):
        qr_data = f"https://maintaineh.app/{label.replace(' ', '_').lower()}_{timestamp}"
        img = qrcode.make(qr_data)
        img.save(os.path.join(batch_path, f'qr{i+1}.png'))
