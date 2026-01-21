import smtplib
import json
import socket
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from database import db, SystemConfig

# --- IPv4 FORCING PATCH (CRITICAL FOR DOCKER) ---
# This ensures we don't try to connect via IPv6 which causes timeouts/unreachable errors
orig_getaddrinfo = socket.getaddrinfo

def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

def get_smtp_config():
    """Fetches SMTP settings from the database."""
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
    Includes Timeout protection (30s) and IPv4 forcing.
    """
    config = get_smtp_config()
    
    if not config:
        return {"status": "error", "message": "SMTP Config missing. Go to Admin > SMTP."}

    # Extract Settings
    smtp_server = config.get('server')
    try:
        smtp_port = int(config.get('port', 465)) # Default to 465 for Hostinger/SSL
    except:
        smtp_port = 465
        
    sender_email = config.get('email')
    sender_password = config.get('password')

    if not all([smtp_server, sender_email, sender_password]):
        return {"status": "error", "message": "Incomplete SMTP settings in database."}

    # --- APPLY IPv4 PATCH ---
    socket.getaddrinfo = getaddrinfo_ipv4
    server = None

    try:
        print(f"📧 [DEBUG] Connecting to {smtp_server}:{smtp_port}...")
        
        # Create Message
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html'))

        # Create Secure Context
        context = ssl.create_default_context()

        # CONNECTION LOGIC
        # Port 465 = SSL (Recommended for Hostinger)
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=30)
        # Port 587 = STARTTLS
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=30)
            server.set_debuglevel(1) # Print connection details to logs
            print("📧 [DEBUG] Sending EHLO...")
            server.ehlo()
            print("📧 [DEBUG] Starting TLS...")
            server.starttls(context=context)
            print("📧 [DEBUG] Sending EHLO after TLS...")
            server.ehlo()

        print(f"📧 [DEBUG] Logging in as {sender_email}...")
        server.login(sender_email, sender_password)
        
        print(f"📧 [DEBUG] Sending email to {to_email}...")
        server.sendmail(sender_email, to_email, msg.as_string())
        
        print("✅ [DEBUG] Email Sent Successfully!")
        server.quit()
        return {"status": "success"}

    except socket.timeout:
        print("❌ [ERROR] Connection Timed Out. Firewall might be blocking the port.")
        return {"status": "error", "message": "Connection Timed Out (Firewall Blocked?)"}
        
    except smtplib.SMTPAuthenticationError:
        print("❌ [ERROR] Auth Failed. Check Email/Password.")
        return {"status": "error", "message": "Authentication Failed. Check Password."}
        
    except Exception as e:
        print(f"❌ [ERROR] Email Failed: {e}")
        return {"status": "error", "message": str(e)}
        
    finally:
        # Restore Socket (Clean up)
        socket.getaddrinfo = orig_getaddrinfo
        try:
            if server: server.quit()
        except: pass
