import smtplib
import json
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from database import db, SystemConfig

def get_smtp_config():
    """
    Fetches SMTP settings from the database.
    Returns a dictionary or None.
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
    Supports both STARTTLS (587) and SSL (465).
    Includes a 10-second timeout to prevent worker crashes.
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

    try:
        # Create Message Object
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html'))

        # Connect to Server with Timeout
        if smtp_port == 465:
            # SSL Connection (Legacy/Specific Providers like Yahoo/older Gmail)
            # ADDED timeout=10 to prevent hanging
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, timeout=10)
        else:
            # TLS Connection (Standard for Gmail/Outlook/AWS on 587)
            # ADDED timeout=10 to prevent hanging
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
            server.starttls() # Upgrade connection to secure

        # Login and Send
        server.login(sender_email, sender_password)
        server.sendmail(sender_email, to_email, msg.as_string())
        server.quit()

        return {"status": "success"}

    except smtplib.SMTPAuthenticationError:
        return {"status": "error", "message": "SMTP Authentication Failed. Check Email/Password."}
    except smtplib.SMTPConnectError:
        return {"status": "error", "message": "Could not connect to SMTP Server."}
    except Exception as e:
        error_msg = str(e)
        print(f"❌ Email Send Error: {error_msg}")
        return {"status": "error", "message": f"Email Failed: {error_msg}"}
