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
    Includes Anti-Detection, Extended Timeouts, and Authorization handling.
    """
    driver = None
    
    # --- 1. RESOLVE CREDENTIALS ---
    if user_specific_creds:
        USER_ID = user_specific_creds.get('user_id')
        PASSWORD = user_specific_creds.get('password')
        TOTP_SECRET = user_specific_creds.get('totp')
    else:
        USER_ID = config.ZERODHA_USER_ID
        PASSWORD = config.ZERODHA_PASSWORD
        TOTP_SECRET = config.TOTP_SECRET

    if not USER_ID or not PASSWORD or not TOTP_SECRET:
        return None, "Missing Credentials"

    try:
        login_url = kite_instance.login_url()
        logger.info(f"Starting Auto-Login for User: {USER_ID}")

        # --- 2. CONFIGURE CHROME OPTIONS (ANTI-DETECTION) ---
        chrome_options = Options()
        chrome_options.add_argument("--headless=new") 
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Hide Automation Flags
        chrome_options.add_argument("--disable-blink-features=AutomationControlled")
        chrome_options.add_experimental_option("excludeSwitches", ["enable-automation"])
        chrome_options.add_experimental_option("useAutomationExtension", False)
        chrome_options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
        
        # --- 3. INITIALIZE DRIVER ---
        driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()), 
            options=chrome_options
        )
        
        # --- 4. LOGIN FLOW ---
        driver.get(login_url)
        wait = WebDriverWait(driver, 45) 

        logger.info("Page loaded. Attempting User ID...")

        # Step A: Enter User ID
        try:
            user_id_field = wait.until(EC.presence_of_element_located((By.ID, "userid")))
            user_id_field.clear()
            user_id_field.send_keys(USER_ID)
            logger.info("User ID entered.")
        except Exception as e:
            return None, f"Failed at User ID: {str(e)}"
        
        # Step B: Enter Password
        try:
            password_field = wait.until(EC.presence_of_element_located((By.ID, "password")))
            password_field.clear()
            password_field.send_keys(PASSWORD)
            logger.info("Password entered.")
        except Exception as e:
            return None, f"Failed at Password: {str(e)}"
        
        # Step C: Click Login Button
        try:
            login_btn = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, "button[type='submit']")))
            login_btn.click()
            logger.info("Login clicked. Waiting for TOTP...")
        except Exception as e:
            return None, f"Failed clicking Login: {str(e)}"
        
        # Step D: Handle TOTP (2FA)
        try:
            totp_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'][minlength='6']")))
            
            totp = pyotp.TOTP(TOTP_SECRET)
            token_code = totp.now()
            
            totp_field.send_keys(token_code)
            logger.info(f"TOTP Entered ({token_code}).")
            
            # Note: Zerodha often auto-submits. We try to click continue just in case.
            try:
                time.sleep(1) 
                # Look for submit button specifically in the TOTP form container
                continue_btn = driver.find_element(By.CSS_SELECTOR, "button[type='submit']")
                continue_btn.click()
            except:
                pass 
                
        except Exception as e:
            if "request_token" in driver.current_url:
                logger.info("Redirected before TOTP entry (Session might be active).")
            else:
                logger.error(f"TOTP Step Error: {e}")
                return None, f"TOTP Error: {str(e)}"

        # --- STEP E: HANDLE "AUTHORIZE" SCREEN (CRITICAL FIX) ---
        try:
            # Brief wait to see if Authorize screen appears (Looking for "Authorize" text or typical button)
            # The authorize button usually has class 'button-orange' or similar, but structure varies.
            # We look for the container.
            time.sleep(3) # Wait for page transition
            
            if "Authorize" in driver.page_source:
                logger.info("Authorize Screen Detected. Attempting to click...")
                # Try to find the generic 'Authorize' button (usually the primary submit button on that page)
                auth_btn = driver.find_element(By.XPATH, "//button[contains(text(), 'Authorize')]")
                auth_btn.click()
                logger.info("Clicked Authorize.")
        except Exception as e:
            logger.info(f"No Authorize screen or click failed (might not be needed): {e}")

        # --- 5. CAPTURE REQUEST TOKEN ---
        logger.info("Waiting for Redirect...")
        
        def check_url_for_token(d):
            return "request_token=" in d.current_url

        try:
            wait.until(check_url_for_token)
        except Exception:
            # Log the URL we got stuck on for debugging
            logger.error(f"Stuck URL: {driver.current_url}")
            return None, f"Redirect Timeout. Stuck at: {driver.title} | {driver.current_url}"

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
