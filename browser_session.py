import logging
import os
import time

from dotenv import load_dotenv
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

load_dotenv()

BASE_URL = "https://ais.usvisa-info.com/en-et"
LOGIN_URL = f"{BASE_URL}/niv/users/sign_in"

AIS_EMAIL = os.getenv("AIS_EMAIL", "")
AIS_PASSWORD = os.getenv("AIS_PASSWORD", "")
SCHEDULE_ID = int(os.getenv("SCHEDULE_ID", "0"))
FACILITY_ID = int(os.getenv("FACILITY_ID", "0"))
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "300"))

log = logging.getLogger(__name__)


def navigate(driver: uc.Chrome, url: str, wait_seconds: int = 3) -> None:
    """Navigate to a URL and wait for the page to settle."""
    driver.get(url)
    time.sleep(wait_seconds)


def make_driver(headless: bool = True) -> uc.Chrome:
    """
    Create an undetected Chrome driver.
    headless=False is useful for debugging login issues.
    """
    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless")
    options.add_argument("--window-size=1280,900")
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    )
    return uc.Chrome(options=options)


def login(driver: uc.Chrome, email: str, password: str) -> bool:
    """
    Log into AIS. Returns True on success.
    Selenium handles cookies and CSRF automatically via the real browser session.
    """
    log.info("Navigating to login page...")
    driver.get(LOGIN_URL)
    time.sleep(3)

    try:
        log.info("Page loaded. Title: %s, URL: %s", driver.title, driver.current_url)

        wait = WebDriverWait(driver, 20)

        log.info("Waiting for email field...")
        email_field = wait.until(EC.presence_of_element_located((By.ID, "user_email")))
        log.info("Found email field")
        email_field.clear()
        email_field.send_keys(email)

        log.info("Filling password...")
        pw_field = driver.find_element(By.ID, "user_password")
        pw_field.clear()
        pw_field.send_keys(password)

        log.info("Finding privacy policy checkbox...")
        try:
            checkbox = driver.find_element(By.ID, "policy_confirmed")
            log.info("Checkbox found. Currently selected: %s", checkbox.is_selected())

            if not checkbox.is_selected():
                try:
                    checkbox.click()
                    log.info("Clicked checkbox with Selenium")
                except Exception:
                    log.info("Checkbox click via Selenium failed, trying JavaScript...")
                    driver.execute_script("arguments[0].click();", checkbox)
                    log.info("Clicked checkbox with JavaScript")

            time.sleep(0.5)
            if not checkbox.is_selected():
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
        wait.until(EC.url_changes(LOGIN_URL))
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
