from io import BytesIO
import qrcode
from aiogram.types import BufferedInputFile


def qr_file(data: str, filename: str = "payment-qr.png") -> BufferedInputFile:
    image = qrcode.make(data)
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    return BufferedInputFile(buffer.getvalue(), filename=filename)
