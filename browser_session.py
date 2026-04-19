import logging
import time

# undetected_chromedriver patches Chrome to bypass AIS bot-detection fingerprinting
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import CONFIG

log = logging.getLogger(__name__)


def navigate(driver: uc.Chrome, url: str, wait_seconds: int = 3) -> None:
    """Navigate to a URL and wait for the page to settle."""
    driver.get(url)
    time.sleep(wait_seconds)


def make_driver(headless: bool = True) -> uc.Chrome:
    """Create an undetected Chrome driver. headless=False is useful for debugging login."""
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--window-size=1280,900")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    # use_subprocess prevents Chrome from inheriting Python's signal handlers (avoids zombie on Ctrl+C)
    return uc.Chrome(options=options, use_subprocess=True)


def login(driver: uc.Chrome, email: str, password: str) -> bool:
    """
    Log into AIS. Returns True on success.
    Selenium handles cookies and CSRF automatically via the real browser session.
    """
    log.info("Navigating to login page...")
    login_url = f"{CONFIG.base_url}/niv/users/sign_in"
    driver.get(login_url)
    time.sleep(3)

    try:
        log.info("Page loaded. Title: %s, URL: %s", driver.title, driver.current_url)

        wait = WebDriverWait(driver, 20)

        log.info("Waiting for email field...")
        email_field = wait.until(EC.presence_of_element_located((By.ID, "user_email")))
        log.info("Found email field")
        email_field.clear()
        email_field.send_keys(email)

        password_field = driver.find_element(By.ID, "user_password")
        log.info("Filling password...")
        password_field.clear()
        password_field.send_keys(password)

        log.info("Finding privacy policy checkbox...")
        try:
            checkbox = driver.find_element(By.ID, "policy_confirmed")
            selected = checkbox.is_selected()
            log.info("Checkbox found. Currently selected: %s", selected)

            if not selected:
                try:
                    checkbox.click()
                    log.info("Clicked checkbox with Selenium")
                except Exception:
                    # AIS JS sometimes intercepts the DOM click event
                    log.info("Checkbox click via Selenium failed, trying JavaScript...")
                    driver.execute_script("arguments[0].click();", checkbox)
                    log.info("Clicked checkbox with JavaScript")

            time.sleep(0.5)
            if not checkbox.is_selected():
                # Last resort: bypass event listeners entirely
                log.warning("Checkbox still not selected after click. Trying again...")
                driver.execute_script("arguments[0].checked = true;", checkbox)
                log.info("Set checkbox to checked via JavaScript")
        except Exception as exc:
            log.error("Checkbox error: %s", exc)

        log.info("Submitting login form...")
        submit_btn = driver.find_element(By.CSS_SELECTOR, "input[type='submit'], button[type='submit']")
        submit_btn.click()

        time.sleep(2)
        try:
            ok_button = driver.find_element(By.CSS_SELECTOR, ".ui-dialog-buttonset button")
            ok_button.click()
            log.info("Closed error dialog")
            time.sleep(1)
        except Exception:
            pass

        log.info("Waiting for redirect...")
        wait.until(EC.url_changes(login_url))
        time.sleep(2)

        current = driver.current_url
        if "sign_in" in current:
            log.error("Login failed — still on login page. Check credentials or solve CAPTCHA manually.")
            return False

        log.info("Login successful")
        return True
    except Exception as exc:
        log.error("Login error: %s", exc)
        return False
