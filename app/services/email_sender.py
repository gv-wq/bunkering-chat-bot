import aiosmtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.application import MIMEApplication

MAIL = "precompiledasset@gmail.com"

SMTP_HOST = "smtp.gmail.com"
SMTP_PORT = 587
SMTP_USER = MAIL
SMTP_PASS = '["Honor400"]'
PSWD = "bfoi egfj lqxr otcn"

class EmailSender:

    async def route_report(
        self,
        subject: str,
        text: str,
        images: list[bytes],
        pdf_bytes: bytes,
        to: str = None
    ):
        msg = MIMEMultipart()
        msg["From"] = SMTP_USER
        msg["To"] = to if to else "gv@thebunkering.com"
        msg["Subject"] = subject

        # HTML body
        msg.attach(MIMEText(text, "html"))

        # Attach images
        for image_index, img_bytes in enumerate(images, 1):
            part = MIMEApplication(img_bytes, Name=f"image_{image_index}.png")
            part["Content-Disposition"] = (
                f'attachment; filename="image_{image_index}.png"'
            )
            msg.attach(part)

        # Attach PDF
        pdf_part = MIMEApplication(pdf_bytes, Name="report.pdf")
        pdf_part["Content-Disposition"] = 'attachment; filename="report.pdf"'
        msg.attach(pdf_part)

        try:
            await aiosmtplib.send(
                msg,
                hostname=SMTP_HOST,
                port=SMTP_PORT,
                username=SMTP_USER,
                password=PSWD,
                start_tls=True,
            )
            return True, None
        except Exception as e:
            return False, str(e)