import smtplib
import json
import socket
import ssl
import requests
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from database import db, SystemConfig

# --- IPv4 FORCING PATCH ---
orig_getaddrinfo = socket.getaddrinfo

def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    return orig_getaddrinfo(host, port, socket.AF_INET, type, proto, flags)

def get_smtp_config():
    """Fetches Email settings from the database."""
    try:
        conf_row = SystemConfig.query.filter_by(key="smtp_config").first()
        if conf_row:
            return json.loads(conf_row.value)
    except Exception as e:
        print(f"Error fetching Email config: {e}")
    return None

def send_via_api(config, to_email, subject, body_html):
    """
    Sends email via HTTP API (Resend/SendGrid) to bypass Railway Port Blocks.
    Port 443 is ALWAYS open on Railway.
    """
    provider = config.get('provider', 'smtp').lower()
    api_key = config.get('password') # Re-using password field for API Key
    sender_email = config.get('email')

    try:
        if provider == 'resend':
            # Resend.com API (Recommended for Railway)
            url = "https://api.resend.com/emails"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "from": f"RD Algo <{sender_email}>",
                "to": [to_email],
                "subject": subject,
                "html": body_html
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            
        elif provider == 'sendgrid':
            # SendGrid API
            url = "https://api.sendgrid.com/v3/mail/send"
            headers = {
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json"
            }
            payload = {
                "personalizations": [{"to": [{"email": to_email}]}],
                "from": {"email": sender_email},
                "subject": subject,
                "content": [{"type": "text/html", "value": body_html}]
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=10)

        else:
            return {"status": "error", "message": f"Unknown API Provider: {provider}"}

        # Check Response
        if resp.status_code in [200, 201, 202]:
            print(f"✅ [SUCCESS] Email sent via {provider.upper()} API!")
            return {"status": "success"}
        else:
            return {"status": "error", "message": f"API Error {resp.status_code}: {resp.text}"}

    except Exception as e:
        return {"status": "error", "message": f"API Request Failed: {str(e)}"}

def send_via_smtp(config, to_email, subject, body_html):
    """Standard SMTP sending (Will TIMEOUT on Railway Free Plan)."""
    socket.setdefaulttimeout(10)
    
    smtp_server = config.get('server')
    try:
        smtp_port = int(config.get('port', 465))
    except:
        smtp_port = 465
    
    sender_email = config.get('email')
    sender_password = config.get('password')

    msg = MIMEMultipart()
    msg['From'] = sender_email
    msg['To'] = to_email
    msg['Subject'] = subject
    msg.attach(MIMEText(body_html, 'html'))

    # IPv4 Patch
    socket.getaddrinfo = getaddrinfo_ipv4
    server = None

    try:
        print(f"📧 [DEBUG] SMTP Connecting to {smtp_server}:{smtp_port}...")
        
        context = ssl.create_default_context()
        
        if smtp_port == 465:
            server = smtplib.SMTP_SSL(smtp_server, smtp_port, context=context, timeout=10)
        else:
            server = smtplib.SMTP(smtp_server, smtp_port, timeout=10)
            server.starttls(context=context)

        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return {"status": "success"}

    except socket.timeout:
        return {"status": "error", "message": "Connection Timed Out. Railway Free Plan blocks SMTP ports (25, 465, 587). Please use Resend/SendGrid API."}
    except Exception as e:
        return {"status": "error", "message": str(e)}
    finally:
        socket.getaddrinfo = orig_getaddrinfo

def send_email(to_email, subject, body_html):
    """
    Main Entry Point. Routes to API or SMTP based on config.
    """
    config = get_smtp_config()
    if not config:
        return {"status": "error", "message": "Email Config missing in Admin Panel."}

    # Check for 'provider' field in config (You can add a dropdown in Admin UI later)
    # For now, auto-detect: if port is 0 or provider is set to 'resend'/'sendgrid'
    provider = config.get('provider', 'smtp')
    
    # Force API use if server contains 'resend' or 'sendgrid' to save user effort
    server_host = config.get('server', '').lower()
    if 'resend' in server_host: provider = 'resend'
    if 'sendgrid' in server_host: provider = 'sendgrid'

    if provider in ['resend', 'sendgrid']:
        return send_via_api(config | {'provider': provider}, to_email, subject, body_html)
    
    return send_via_smtp(config, to_email, subject, body_html)
