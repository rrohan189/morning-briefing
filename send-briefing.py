import smtplib
import sys
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime
from dotenv import load_dotenv

try:
    import premailer
    HAS_PREMAILER = True
except ImportError:
    HAS_PREMAILER = False

load_dotenv()

def inline_css(html):
    """Inline CSS styles for Gmail desktop compatibility.
    Gmail strips <style> tags from <head>, so all styles
    must be inlined for desktop rendering."""
    if HAS_PREMAILER:
        return premailer.transform(
            html,
            keep_style_tags=True,
            strip_important=False,
        )
    else:
        print("Warning: premailer not installed - sending without CSS inlining (desktop may look rough)")
        print("Fix with: pip install premailer")
        return html

def send_briefing(html_path):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"Morning Intelligence — {datetime.now().strftime('%A, %B %d').replace(' 0', ' ')}"
    msg["From"] = os.getenv("GMAIL_ADDRESS")
    msg["To"] = os.getenv("BRIEFING_RECIPIENT")

    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    html = inline_css(html)
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(os.getenv("GMAIL_ADDRESS"), os.getenv("GMAIL_APP_PASSWORD"))
        server.send_message(msg)
        print(f"Briefing sent to {msg['To']}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python send-briefing.py <path-to-briefing.html>")
        sys.exit(1)
    send_briefing(sys.argv[1])
