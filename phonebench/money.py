from decimal import Decimal


def format_money(value, currency="IDR"):
    amount = Decimal(str(value or 0))
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if currency == "USD":
        return f"{sign}${amount:,.2f}"

    whole, fractional = f"{amount:,.2f}".split(".")
    whole = whole.replace(",", ".")
    fractional = "" if fractional == "00" else f",{fractional}"
    return f"{sign}Rp.{whole}{fractional}"


def parse_money(value, currency="IDR"):
    text = str(value or "").strip().replace(" ", "")
    if currency == "USD":
        text = text.replace(",", "")
    elif "," in text:
        text = text.replace(".", "").replace(",", ".")
    elif "." in text and len(text.rsplit(".", 1)[1]) == 3:
        text = text.replace(".", "")
    return Decimal(text)
