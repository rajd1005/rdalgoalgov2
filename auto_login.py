import time
import pyotp
import logging
from kiteconnect import KiteConnect
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
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
    V9 Update: Adds Staleness Checks and prioritizes Standard Clicks to fix React event issues.
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

        # --- 2. CONFIGURE CHROME OPTIONS ---
        chrome_options = Options()
        chrome_options.add_argument("--headless=new") 
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        chrome_options.add_argument("--window-size=1920,1080")
        
        # Anti-Detection
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
            # Wait for field
            totp_field = wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "input[type='text'][minlength='6']")))
            
            # Generate Code
            totp = pyotp.TOTP(TOTP_SECRET)
            token_code = totp.now()
            
            # Submit Code
            totp_field.send_keys(token_code)
            logger.info(f"TOTP Entered ({token_code}). Submitting...")
            totp_field.send_keys(Keys.ENTER)
            
        except Exception as e:
            if "request_token" in driver.current_url:
                logger.info("Redirected before TOTP entry.")
            else:
                logger.error(f"TOTP Step Error: {e}")
                return None, f"TOTP Error: {str(e)}"

        # --- STEP E: SMART POLLING LOOP ---
        logger.info("Entering Smart Polling Loop (Max 60s)...")
        
        start_time = time.time()
        max_duration = 60 
        
        while time.time() - start_time < max_duration:
            try:
                current_url = driver.current_url
                page_source = driver.page_source
                
                # 1. SUCCESS: Check for Redirect Token
                if "request_token=" in current_url:
                    logger.info("✅ Redirect URL Captured!")
                    from urllib.parse import urlparse, parse_qs
                    parsed = urlparse(current_url)
                    request_token = parse_qs(parsed.query).get('request_token', [None])[0]
                    return request_token, None

                # 2. FAILURE: Check for Errors
                if "Invalid TOTP" in page_source or "Incorrect password" in page_source:
                    error_msg = "Login Failed: Invalid TOTP or Password detected."
                    logger.error(f"❌ {error_msg}")
                    return None, error_msg

                # 3. ACTION: Find Action Buttons
                # We specifically look for submit buttons or the orange Zerodha buttons
                buttons = driver.find_elements(By.CSS_SELECTOR, "button[type='submit'], button.button-orange")
                
                action_taken = False
                for btn in buttons:
                    if btn.is_displayed() and btn.is_enabled():
                        text = btn.text.lower()
                        if any(x in text for x in ['continue', 'authorize', 'allow', 'approve', 'login']):
                            logger.info(f"🔘 Found Button: '{btn.text}' on page: {driver.title}")
                            
                            # METHOD A: Standard Click (Best for React)
                            try:
                                btn.click()
                                logger.info("   -> Standard Click sent.")
                            except Exception:
                                # METHOD B: JS Click (Fallback)
                                driver.execute_script("arguments[0].click();", btn)
                                logger.info("   -> JS Force-Click sent (Standard failed).")
                            
                            # CRITICAL: Wait for staleness (Page Load)
                            # This ensures we don't spam-click the same button instantly
                            try:
                                WebDriverWait(driver, 8).until(EC.staleness_of(btn))
                                logger.info("   -> Page transition detected (Button disappeared).")
                            except Exception:
                                logger.warning("   -> Warning: Page did not transition after 8s.")
                            
                            action_taken = True
                            break # Re-evaluate page state
                
                if action_taken:
                    continue # Loop immediately to check new URL

                # 4. ROBUST RETRY: Check Empty TOTP
                totp_inputs = driver.find_elements(By.CSS_SELECTOR, "input[type='text'][minlength='6']")
                if totp_inputs and totp_inputs[0].is_displayed():
                    curr_val = totp_inputs[0].get_attribute("value")
                    if not curr_val:
                        logger.warning("⚠️ TOTP field is empty. Re-filling...")
                        refill_totp = pyotp.TOTP(TOTP_SECRET)
                        totp_inputs[0].send_keys(refill_totp.now())
                        time.sleep(0.5)
                        totp_inputs[0].send_keys(Keys.ENTER)

            except Exception as e:
                pass 

            time.sleep(1) # Poll interval

        # Timeout
        logger.error(f"Timeout. Final URL: {driver.current_url}")
        return None, "Login Timeout: Zerodha did not redirect after 60 seconds."

    except Exception as e:
        logger.error(f"Auto-Login Exception: {e}")
        return None, str(e)
        
    finally:
        if driver:
            driver.quit()
