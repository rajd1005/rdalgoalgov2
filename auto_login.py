import time
import pyotp
import logging
from kiteconnect import KiteConnect
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def perform_auto_login(kite_instance, user_specific_creds=None):
    """
    Performs auto-login using Selenium with Multi-User support.
    
    Args:
        kite_instance: The user's KiteConnect object.
        user_specific_creds (dict): Dictionary containing 'user_id', 'password', 'totp'.
    """
    driver = None
    
    # --- 1. RESOLVE CREDENTIALS ---
    # Prioritize passed credentials (Multi-User), fallback to Config (Single-User/Legacy)
    if user_specific_creds:
        USER_ID = user_specific_creds.get('user_id')
        PASSWORD = user_specific_creds.get('password')
        TOTP_SECRET = user_specific_creds.get('totp')
    else:
        # Fallback for backward compatibility
        USER_ID = config.ZERODHA_USER_ID
        PASSWORD = config.ZERODHA_PASSWORD
        TOTP_SECRET = config.TOTP_SECRET

    if not USER_ID or not PASSWORD or not TOTP_SECRET:
        return None, "Missing Credentials"

    try:
        login_url = kite_instance.login_url()
        logger.info(f"Starting Auto-Login for User: {USER_ID}")

        # --- 2. CONFIGURE CHROME OPTIONS ---
        chrome_options = Options()
        chrome_options.add_argument("--headless")  # Run in background
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # --- 3. INITIALIZE DRIVER ---
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), 
            options=chrome_options
        )
        
        # --- 4. LOGIN FLOW ---
        driver.get(login_url)
        wait = WebDriverWait(driver, 15)

        # Step A: Enter User ID
        user_id_field = wait.until(EC.presence_of_element_located((By.ID, "userid")))
        user_id_field.send_keys(USER_ID)
        
        # Step B: Enter Password
        password_field = wait.until(EC.presence_of_element_located((By.ID, "password")))
        password_field.send_keys(PASSWORD)
        
        # Step C: Click Login Button
        login_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']")))
        login_btn.click()
        
        # Step D: Handle TOTP (2FA)
        try:
            # Wait for TOTP field to appear (it might be labeled 'userid' again in DOM or specific class)
            # Zerodha sometimes reuses IDs. Using input with minlength=6 covers most 2FA inputs.
            totp_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'][minlength='6']")))
            
            # Generate TOTP
            totp = pyotp.TOTP(TOTP_SECRET)
            token_code = totp.now()
            
            totp_field.send_keys(token_code)
            
            # Wait for redirection/submission
            # Sometimes need to click continue, sometimes auto-submits. Check for button.
            try:
                # Attempt to click continue if it exists and is clickable
                continue_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                continue_btn.click()
            except:
                pass # Auto-submit might have happened
                
        except Exception as e:
            logger.error(f"TOTP Step Error: {e}")
            return None, f"TOTP Error: {str(e)}"

        # --- 5. CAPTURE REQUEST TOKEN ---
        # Wait for the redirect to our callback URL
        # We look for 'request_token' in the current URL
        
        def check_url_for_token(d):
            return "request_token=" in d.current_url

        try:
            wait.until(check_url_for_token)
        except Exception:
            # If timeout, check if we are on an error page or still on login
            return None, f"Redirect Timeout. Current URL: {driver.current_url}"

        current_url = driver.current_url
        logger.info("Redirect URL Captured.")

        # Extract Token
        from urllib.parse import urlparse, parse_qs
        parsed = urlparse(current_url)
        request_token = parse_qs(parsed.query).get('request_token', [None])[0]

        if request_token:
            return request_token, None
        else:
            return None, "Token not found in redirect URL"

    except Exception as e:
        logger.error(f"Auto-Login Exception: {e}")
        return None, str(e)
        
    finally:
        if driver:
            driver.quit()
