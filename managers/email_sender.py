import smtplib
import json
import socket
import ssl
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from database import db, SystemConfig

# --- IPv4 FORCING PATCH ---
orig_getaddrinfo = socket.getaddrinfo

def getaddrinfo_ipv4(host, port, family=0, type=0, proto=0, flags=0):
    # Forces IPv4 to fix Docker/IPv6 networking issues
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

def attempt_send(server_host, port, user, password, msg, timeout=20):
    """
    Internal helper to try sending email on a specific port.
    """
    server = None
    try:
        # 1. Resolve IP first to debug DNS issues
        try:
            ip = socket.gethostbyname(server_host)
            print(f"📧 [DEBUG] Resolved {server_host} -> {ip}")
        except:
            print(f"⚠️ [WARN] Could not resolve {server_host}")

        print(f"📧 [DEBUG] Connecting to {server_host}:{port} (Timeout: {timeout}s)...")
        
        # 2. Create Secure Context
        context = ssl.create_default_context()
        
        # 3. Enforce Socket Timeout
        socket.setdefaulttimeout(timeout)
        
        # 4. Connect based on Port
        if int(port) == 465:
            server = smtplib.SMTP_SSL(server_host, port, context=context, timeout=timeout)
        else:
            server = smtplib.SMTP(server_host, port, timeout=timeout)
            # server.set_debuglevel(1) # Enable for verbose protocol logs
            server.ehlo()
            try:
                server.starttls(context=context)
                server.ehlo()
            except Exception as tls_err:
                print(f"⚠️ [WARN] STARTTLS skipped on {port}: {tls_err}")

        # 5. Login & Send
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
    Sends email with Smart Fallback: User Port -> 465 -> 587 -> 2525.
    """
    original_timeout = socket.getdefaulttimeout()
    
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

        # Prepare Message
        msg = MIMEMultipart()
        msg['From'] = user_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html'))

        # --- APPLY IPv4 PATCH ---
        socket.getaddrinfo = getaddrinfo_ipv4

        # DEFINE PORTS TO TRY
        # Priority: Configured Port -> 465 (SSL) -> 587 (TLS) -> 2525 (Alternative)
        ports_to_try = []
        if primary_port not in ports_to_try: ports_to_try.append(primary_port)
        if 465 not in ports_to_try: ports_to_try.append(465)
        if 587 not in ports_to_try: ports_to_try.append(587)
        if 2525 not in ports_to_try: ports_to_try.append(2525)

        last_error = ""

        for port in ports_to_try:
            print(f"🔄 [INFO] Trying SMTP Port: {port}...")
            success, error = attempt_send(smtp_server, port, user_email, user_pass, msg)
            if success:
                print(f"✅ [SUCCESS] Email Sent via Port {port}!")
                return {"status": "success"}
            last_error = error
            # If authentication failed, don't try other ports (password is wrong)
            if "Authentication" in error or "Auth" in error:
                return {"status": "error", "message": "Authentication Failed. Check Email/Password."}

        return {"status": "error", "message": f"All ports blocked by Firewall. Last Error: {last_error}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}
        
    finally:
        # Restore Original Socket Settings
        socket.getaddrinfo = orig_getaddrinfo
        socket.setdefaulttimeout(original_timeout)
