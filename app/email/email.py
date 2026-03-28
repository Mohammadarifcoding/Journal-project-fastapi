from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from pydantic import EmailStr, BaseModel
import os
import logging

ADMIN_EMAIL = "programmermdarif@gmail.com"

logger = logging.getLogger(__name__)


class EmailSchema(BaseModel):
    email: EmailStr
    subject: str
    body: str


conf = ConnectionConfig(
    MAIL_USERNAME="nabirasek@gmail.com",
    MAIL_PASSWORD=os.getenv("EMAIL_APP_PASSWORD"),
    MAIL_FROM="nabirasek@gmail.com",
    MAIL_SERVER="smtp.gmail.com",
    MAIL_PORT=465,
    MAIL_SSL_TLS=True,
    MAIL_STARTTLS=False,
    USE_CREDENTIALS=True,
)

fm = FastMail(conf)


async def _send(email: str, subject: str, body: str):
    message = MessageSchema(
        subject=f"[Forwarded] {subject}",
        recipients=[ADMIN_EMAIL],
        body=f"""
        <p><strong>Original Recipient:</strong> {email}</p>
        <hr>
        <div>{body}</div>
        """,
        subtype="html",
    )

    await fm.send_message(message)


async def send_email(email: str, subject: str, body: str):
    try:
        await _send(email, subject, body)
    except Exception as e:
        logger.error(f"Email send failed: {str(e)}")
        raise


async def send_registration_email(email: str):
    subject = "Welcome to Ai Journal!"
    body = f"""
    <p>Hi there,</p>
    <p>Thank you for registering on Ai Journal. We're excited to have you on board!</p>
    <p>Best regards,<br/>The Ai Journal Team</p>
    """
    await send_email(email, subject, body)

    logger.info(f"Registration email sent to {email}")

    return {"message": "Registration email sent"}
