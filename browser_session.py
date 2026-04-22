import logging
import re
import subprocess
import time
from typing import Optional

# undetected_chromedriver patches Chrome to bypass AIS bot-detection fingerprinting
import undetected_chromedriver as uc
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

from config import CONFIG

log = logging.getLogger(__name__)


def _chrome_major_version() -> Optional[int]:
    """Detect the installed Chrome major version so uc downloads a matching ChromeDriver."""
    try:
        result = subprocess.run(
            ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome", "--version"],
            capture_output=True, text=True, timeout=5,
        )
        if m := re.search(r"(\d+)\.", result.stdout):
            return int(m.group(1))
    except Exception:
        pass
    return None


def make_driver(headless: bool = True) -> uc.Chrome:
    """Create an undetected Chrome driver. headless=False is useful for debugging login."""
    options = uc.ChromeOptions()
    options.add_argument("--window-size=1280,900")
    version = _chrome_major_version()
    log.info("Detected Chrome major version: %s", version)
    options.add_argument(
        "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        f"Chrome/{version}.0.0.0 Safari/537.36"
    )
    # use_subprocess=False: required on macOS — subprocess mode breaks the WebDriver session
    # before the first navigation completes (ref: ultrafunkamsterdam/undetected-chromedriver#2295).
    # Still seeing sporadic "no such window" crashes on Chrome 147; those are caught and recovered
    # in the main loop rather than solved here.
    # version_main: ensures uc downloads a ChromeDriver matching the installed Chrome,
    # preventing renderer crashes from version mismatch after a Chrome auto-update.
    driver = uc.Chrome(options=options, use_subprocess=False, headless=headless, version_main=version)
    driver.set_page_load_timeout(30)
    driver.set_script_timeout(30)
    return driver


def restart_driver(driver: uc.Chrome, headless: bool) -> uc.Chrome:
    """Quit a crashed driver silently and return a fresh one."""
    try:
        driver.quit()
    except Exception:
        pass
    return make_driver(headless=headless)


def login(driver: uc.Chrome, email: str, password: str) -> bool:
    """
    Log into AIS. Returns True on success.
    Selenium handles cookies and CSRF automatically via the real browser session.
    """
    log.debug("Navigating to login page...")
    login_url = f"{CONFIG.base_url}/niv/users/sign_in"
    driver.get(login_url)
    time.sleep(3)

    try:
        log.info(f"Login page loaded. Title: {driver.title}")

        wait = WebDriverWait(driver, 20)

        log.debug("Waiting for email field...")
        email_field = wait.until(EC.presence_of_element_located((By.ID, "user_email")))
        log.debug("Found email field")
        email_field.clear()
        email_field.send_keys(email)

        password_field = driver.find_element(By.ID, "user_password")
        log.debug("Filling password...")
        password_field.clear()
        password_field.send_keys(password)

        log.debug("Finding privacy policy checkbox...")
        try:
            checkbox = driver.find_element(By.ID, "policy_confirmed")
            selected = checkbox.is_selected()
            log.debug("Checkbox found. Currently selected: %s", selected)

            if not selected:
                try:
                    checkbox.click()
                    log.debug("Clicked checkbox with Selenium")
                except Exception:
                    # AIS JS sometimes intercepts the DOM click event
                    log.debug("Checkbox click via Selenium failed, trying JavaScript...")
                    driver.execute_script("arguments[0].click();", checkbox)
                    log.debug("Clicked checkbox with JavaScript")

            time.sleep(0.5)
            if not checkbox.is_selected():
                # Last resort: bypass event listeners entirely
                log.debug("Checkbox still not selected after click. Trying again...")
                driver.execute_script("arguments[0].checked = true;", checkbox)
                log.debug("Set checkbox to checked via JavaScript")
        except Exception as exc:
            log.error("Checkbox error: %s", exc)

        log.info("Submitting login form...")
        submit_btn = driver.find_element(By.CSS_SELECTOR, "input[type='submit'], button[type='submit']")
        submit_btn.click()

        time.sleep(2)
        try:
            driver.find_element(By.CSS_SELECTOR, ".ui-dialog-buttonset button").click()
            log.debug("Closed error dialog")
            time.sleep(1)
        except Exception:
            pass

        log.debug("Waiting for redirect...")
        wait.until(EC.url_changes(login_url))
        time.sleep(2)

        if "sign_in" in driver.current_url:
            log.error("Login failed — still on login page. Check credentials or solve CAPTCHA manually.")
            return False
        
        log.info(f"Redirected to home page. Title: {driver.title}")
        return True
    except Exception as exc:
        log.error("Login error: %s", exc)
        return False
