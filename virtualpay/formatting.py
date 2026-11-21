import hashlib
import io

import qrcode

def Indian_money(value: int | float) -> str:
    """Format a rupee amount with Indian digit grouping."""
    number = int(round(value))
    sign = "−" if number < 0 else ""
    digits = str(abs(number))
    if len(digits) <= 3:
        grouped = digits
    else:
        grouped = digits[-3:]
        digits = digits[:-3]
        while digits:
            grouped = digits[-2:] + "," + grouped
            digits = digits[:-2]
    return f"{sign}₹{grouped}"


def pin_digest(pin: str) -> str:
    return hashlib.sha256(pin.encode("utf-8")).hexdigest()


def make_qr(value: str) -> bytes:
    image = qrcode.make(value)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()
