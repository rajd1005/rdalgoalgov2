import smtplib
import json
import socket
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from database import db, SystemConfig

# --- IPv4 FORCING PATCH ---
# This ensures we don't try to connect via IPv6 (which causes Errno 101 in Docker)
orig_getaddrinfo = socket.getaddrinfo

def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    # Force AF_INET (IPv4) family
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

def get_smtp_config():
    """
    Fetches SMTP settings from the database.
    """
    try:
        conf_row = SystemConfig.query.filter_by(key="smtp_config").first()
        if conf_row:
            return json.loads(conf_row.value)
    except Exception as e:
        print(f"Error fetching SMTP config: {e}")
    return None

def send_email(to_email, subject, body_html):
    """
    Sends an email using the SMTP settings stored in DB.
    Forces IPv4 to prevent '[Errno 101] Network is unreachable' in Docker.
    """
    config = get_smtp_config()
    
    if not config:
        return {"status": "error", "message": "SMTP Configuration not found. Please configure it in the Admin Panel."}

    # Extract Settings
    smtp_server = config.get('server')
    try:
        smtp_port = int(config.get('port', 587))
    except (ValueError, TypeError):
        smtp_port = 587
        
    sender_email = config.get('email')
    sender_password = config.get('password')

    # Validate Settings
    if not all([smtp_server, sender_email, sender_password]):
        return {"status": "error", "message": "Incomplete SMTP settings in database."}

    # --- APPLY IPv4 PATCH ---
    socket.getaddrinfo = getaddrinfo_ipv4

    try:
        # Create Message Object
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html'))

        # Connect to Server with Timeout
        # (Timeout prevents worker hangs if server is unresponsive)
        if smtp_port == 465:
            # SSL Connection (Legacy/Specific Providers)
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=15)
        else:
            # TLS Connection (Standard for Gmail/Outlook 587)
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=15)
            server.starttls() # Upgrade connection to secure

        # Login and Send
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()

        return {"status": "success"}

    except smtplib.SMTPAuthenticationError:
        return {"status": "error", "message": "SMTP Authentication Failed. Check Email/App Password."}
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Email Send Error: {error_msg}")
        return {"status": "error", "message": f"Email Failed: {error_msg}"}
        
    finally:
        # --- REMOVE IPv4 PATCH ---
        # Restore original socket behavior to not affect other parts of the app
        socket.getaddrinfo = orig_getaddrinfo
