from io import BytesIO

import qrcode
from aiogram.types import BufferedInputFile


def make_address_qr(address: str) -> BufferedInputFile:
    qr = qrcode.QRCode(box_size=8, border=3)
    qr.add_data(address)
    qr.make(fit=True)
    image = qr.make_image()

    output = BytesIO()
    image.save(output, format="PNG")
    return BufferedInputFile(output.getvalue(), filename="usdt-trc20.png")
