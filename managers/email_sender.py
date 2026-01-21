import smtplib
import json
import socket
import ssl
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from database import db, SystemConfig

# --- IPv4 FORCING PATCH ---
# Fixes [Errno 101] Network is unreachable in Docker
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

def attempt_send(server_host, port, user, password, msg, timeout=5):
    """
    Internal helper to try sending email.
    TIMEOUT IS SET TO 5 SECONDS to prevent Gunicorn Worker Timeout (Crash).
    """
    server = None
    try:
        print(f"📧 [DEBUG] Connecting to {server_host}:{port} (Timeout: {timeout}s)...")
        
        context = ssl.create_default_context()
        socket.setdefaulttimeout(timeout) # Force Global Timeout
        
        if int(port) == 465:
            server = smtplib.SMTP_SSL(server_host, port, context=context, timeout=timeout)
        else:
            server = smtplib.SMTP(server_host, port, timeout=timeout)
            server.ehlo()
            try:
                server.starttls(context=context)
                server.ehlo()
            except Exception as tls_err:
                print(f"⚠️ [WARN] STARTTLS skipped on {port}: {tls_err}")

        server.login(user, password)
        server.send_message(msg)
        server.quit()
        return True, "Sent"

    except Exception as e:
        err_str = str(e)
        print(f"❌ [FAIL] Port {port} failed: {err_str}")
        try:
            if server: server.quit()
        except: pass
        return False, err_str

def send_email(to_email, subject, body_html):
    """
    Sends email with Aggressive Timeout & Fallback.
    Tries User Port -> 465 -> 587 -> 2525.
    Aborts if total time exceeds 25s.
    """
    original_timeout = socket.getdefaulttimeout()
    start_time = time.time()
    
    try:
        config = get_smtp_config()
        if not config:
            return {"status": "error", "message": "SMTP Config missing in Admin Panel."}

        smtp_server = config.get('server')
        user_email = config.get('email')
        user_pass = config.get('password')
        
        try:
            primary_port = int(config.get('port', 465))
        except:
            primary_port = 465

        if not all([smtp_server, user_email, user_pass]):
            return {"status": "error", "message": "Incomplete SMTP settings."}

        msg = MIMEMultipart()
        msg['From'] = user_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html'))

        # Force IPv4
        socket.getaddrinfo = getaddrinfo_ipv4

        # Ports to try in order
        ports_to_try = []
        if primary_port not in ports_to_try: ports_to_try.append(primary_port)
        if 465 not in ports_to_try: ports_to_try.append(465)
        if 587 not in ports_to_try: ports_to_try.append(587)
        if 2525 not in ports_to_try: ports_to_try.append(2525)

        last_error = ""

        for port in ports_to_try:
            # SAFETY CHECK: If we are close to Gunicorn timeout (25s), stop trying.
            if time.time() - start_time > 25:
                return {"status": "error", "message": "Connection Timed Out (All ports blocked)."}

            success, error = attempt_send(smtp_server, port, user_email, user_pass, msg, timeout=5)
            
            if success:
                return {"status": "success"}
            
            last_error = error
            # If Auth failed, password is wrong. Don't retry other ports.
            if "Authentication" in error or "535" in error:
                return {"status": "error", "message": "Authentication Failed. Check Password."}

        return {"status": "error", "message": f"Connection Failed (Firewall?). Last error: {last_error}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}
        
    finally:
        socket.getaddrinfo = orig_getaddrinfo
        socket.setdefaulttimeout(original_timeout)
