"""E-mail sign-in link ("magic link") helpers for the public portal.

The link proves control of a mailbox and nothing else. Tokens are random, only
their SHA-256 is stored, each works once and expires quickly. Sending uses the
standard library (SMTP, STARTTLS by default) and is disabled until a server is
configured, so the feature is invisible on installations without mail.
"""
import hashlib
import re
import secrets
import smtplib
import ssl
from email.message import EmailMessage

_EMAIL_RE = re.compile(r"^[^@\s]{1,64}@[^@\s]{1,190}\.[^@\s.]{2,}$")


def enabled(settings) -> bool:
    return bool(settings.smtp_host and settings.smtp_from and settings.public_domain)


def new_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def normalize_email(value: str) -> str | None:
    """Lower-cased address, or None when it does not look like one."""
    email = (value or "").strip().lower()
    if len(email) > 254 or not _EMAIL_RE.fullmatch(email) or "\n" in email or "\r" in email:
        return None
    return email


def build_message(settings, to: str, link: str) -> EmailMessage:
    minutes = max(1, settings.email_link_ttl // 60)
    msg = EmailMessage()
    msg["Subject"] = "Votre lien de connexion AURA"
    msg["From"] = settings.smtp_from
    msg["To"] = to
    msg.set_content(
        "Bonjour,\n\n"
        "Voici votre lien pour entrer dans la bibliothèque AURA :\n\n"
        f"{link}\n\n"
        f"Il est valable {minutes} minutes et ne fonctionne qu'une seule fois.\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez simplement ce message.\n"
    )
    return msg


def send(settings, to: str, link: str) -> None:
    """Send the link; raises on any SMTP problem (the caller logs and moves on)."""
    msg = build_message(settings, to, link)
    context = ssl.create_default_context()
    if settings.smtp_port == 465:
        server = smtplib.SMTP_SSL(settings.smtp_host, settings.smtp_port, timeout=10, context=context)
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=10)
    with server:
        if settings.smtp_port != 465 and settings.smtp_starttls:
            server.starttls(context=context)
        if settings.smtp_user:
            server.login(settings.smtp_user, settings.smtp_password)
        server.send_message(msg)
