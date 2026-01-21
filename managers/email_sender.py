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

def attempt_send(server_host, port, user, password, msg, timeout=10):
    """
    Internal helper to try sending email on a specific port.
    Uses strict socket timeouts to prevent Gunicorn Worker Death.
    """
    server = None
    try:
        print(f"📧 [DEBUG] Attempting Connection: {server_host}:{port} (Timeout: {timeout}s)...")
        
        # Create Secure Context
        context = ssl.create_default_context()
        
        # Enforce Global Socket Timeout (Fixes DNS hanging issues)
        socket.setdefaulttimeout(timeout)
        
        if int(port) == 465:
            server = smtplib.SMTP_SSL(server_host, port, context=context, timeout=timeout)
        else:
            server = smtplib.SMTP(server_host, port, timeout=timeout)
            # server.set_debuglevel(1) 
            server.ehlo()
            try:
                server.starttls(context=context)
                server.ehlo()
            except Exception as tls_err:
                print(f"⚠️ [WARN] STARTTLS skipped/failed on {port}: {tls_err}")

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
    Sends email with Auto-Fallback logic and strict timeout controls.
    """
    # 1. Reset Timeout to Default (to avoid affecting other app parts)
    original_timeout = socket.getdefaulttimeout()
    
    try:
        config = get_smtp_config()
        if not config:
            return {"status": "error", "message": "SMTP Config missing in Admin Panel."}

        # Extract Settings
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

        # ATTEMPT 1: User Configured Port
        start_time = time.time()
        success, error = attempt_send(smtp_server, primary_port, user_email, user_pass, msg)
        
        if success:
            return {"status": "success"}
        
        # Check elapsed time. If first attempt took > 15s, don't try fallback (save the worker).
        elapsed = time.time() - start_time
        if elapsed > 15:
             return {"status": "error", "message": f"Connection Timed Out on {primary_port}. Aborted Fallback to prevent crash."}

        # ATTEMPT 2: Fallback Port
        fallback_port = 587 if primary_port == 465 else 465
        print(f"🔄 [RETRY] Switching to Fallback Port: {fallback_port}...")
        
        success_fb, error_fb = attempt_send(smtp_server, fallback_port, user_email, user_pass, msg)
        
        if success_fb:
            print(f"✅ [SUCCESS] Email Sent via Fallback Port {fallback_port}.")
            return {"status": "success"}
        
        return {"status": "error", "message": f"All ports failed (Firewall?). Primary: {error} | Fallback: {error_fb}"}

    except Exception as e:
        return {"status": "error", "message": str(e)}
        
    finally:
        # CRITICAL: Restore original socket behavior
        socket.getaddrinfo = orig_getaddrinfo
        socket.setdefaulttimeout(original_timeout)
