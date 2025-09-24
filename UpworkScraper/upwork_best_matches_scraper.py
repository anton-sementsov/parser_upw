# Copyright (c) 2024 roperi

import os
import sys
import time
from datetime import datetime
import logging
import undetected_chromedriver as uc
import certifi
from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import WebDriverException, InvalidSessionIdException
from utils.job_helpers import generate_job_id, clean_job_proposals, calculate_posted_datetime
from utils.database import create_db, connect_to_db
from utils.telegram_service import notify_new_job
from utils.search_scraper import scrape_search_page
from settings import config


# LOGGING

# Create logger
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
# Get paths
scriptdir = os.path.dirname(os.path.abspath(__file__))
logdir = os.path.join(scriptdir, 'log')
if not os.path.exists(logdir):
    os.makedirs(logdir)
mypath = os.path.join(logdir, 'upwork_best_matches_scraper.log')
# Create file handler which logs even DEBUG messages
fh = logging.FileHandler(mypath)
fh.setLevel(logging.DEBUG)
# Create console handler
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
# create formatter and add it to the handlers
formatter = logging.Formatter('[%(levelname)s. %(name)s, (line #%(lineno)d) - %(asctime)s] %(message)s')
fh.setFormatter(formatter)
ch.setFormatter(formatter)
# add handlers to logger
logger.addHandler(fh)
logger.addHandler(ch)


# FUNCTIONS

def get_driver_with_retry(chrome_versions, max_attempts=3):
    # Ensure urllib/requests know where the CA bundle is so uc can fetch releases
    try:
        ca_bundle_path = certifi.where()
        os.environ.setdefault('SSL_CERT_FILE', ca_bundle_path)
        os.environ.setdefault('REQUESTS_CA_BUNDLE', ca_bundle_path)
        logger.info(f'Using certifi CA bundle: {ca_bundle_path}')
    except Exception:
        logger.warning('Failed to set certifi CA env; continuing anyway')

    last_exception = None
    for attempt in range(max_attempts):
        for chrome_version in chrome_versions:
            logger.info(f'Trying with Chrome version {chrome_version}')
            try:
                logger.info(f'Attempt #{attempt+1}/{max_attempts}')
                options = uc.ChromeOptions()
                options.headless = False
                driver = uc.Chrome(options=options, version_main=chrome_version)
                logger.info('Launched undetected_chromedriver successfully')
                return driver
            except Exception as e:
                last_exception = e
                logger.exception(
                    f"Failed to launch undetected_chromedriver with version {chrome_version} on attempt "
                    f"{attempt+1}/{max_attempts}"
                )

    logger.error(
        f"All attempts failed for all Chrome versions within {max_attempts} attempts. Trying Selenium Manager fallback."
    )

    # Fallback: try Selenium Manager (native webdriver) to resolve the correct ChromeDriver automatically
    try:
        chrome_candidate_paths = [
            "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
            "/Applications/Google Chrome Beta.app/Contents/MacOS/Google Chrome Beta",
            "/Applications/Google Chrome Dev.app/Contents/MacOS/Google Chrome Dev",
            "/Applications/Google Chrome Canary.app/Contents/MacOS/Google Chrome Canary",
        ]

        chrome_options = webdriver.ChromeOptions()
        for candidate in chrome_candidate_paths:
            if os.path.exists(candidate):
                chrome_options.binary_location = candidate
                logger.info(f'Using Chrome binary at: {candidate}')
                break

        chrome_options.add_argument('--disable-gpu')
        chrome_options.add_argument('--no-sandbox')
        chrome_options.add_argument('--start-maximized')

        driver = webdriver.Chrome(options=chrome_options)
        logger.info('Launched Selenium WebDriver via Selenium Manager successfully')
        return driver
    except Exception as e:
        logger.exception('Selenium Manager fallback failed to launch Chrome')
        if last_exception is not None:
            logger.error(f'Last undetected_chromedriver error: {last_exception}')
        return None


def is_driver_alive(current_driver) -> bool:
    try:
        current_driver.execute_script("return 1")
        return True
    except Exception:
        return False


def login_to_upwork(active_driver):
    try:
        user_login_page = 'https://www.upwork.com/ab/account-security/login'
        logger.info(f'Navigating to `{user_login_page}`')
        active_driver.get(user_login_page)
        logger.info('Pausing for windows to fully load')
        time.sleep(25)

        logger.info('Switching to main window')
        all_windows = active_driver.window_handles
        active_driver.switch_to.window(all_windows[-1])

        logger.info('Submitting username')
        username_input = WebDriverWait(active_driver, 30).until(
            EC.visibility_of_element_located(
                (By.XPATH,
                 "/html/body/div[4]/div/div/div/main/div/div/div[2]/div[2]/form/div/div/div[1]/div[3]/div/div/div/"
                 "div/input")
            )
        )
        username_input.send_keys(config.UPWORK_USERNAME)

        username_field = WebDriverWait(active_driver, 30).until(
            EC.visibility_of_element_located(
                (By.XPATH,
                 "/html/body/div[4]/div/div/div/main/div/div/div[2]/div[2]/form/div/div/div[1]/div[3]/div/div/div/"
                 "div/input")
            )
        )
        username_field.send_keys(Keys.ENTER)

        logger.info('Submitting password')
        password_input = WebDriverWait(active_driver, 30).until(
            EC.visibility_of_element_located(
                (By.XPATH,
                 "/html/body/div[4]/div/div/div/main/div/div/div[2]/div[2]/div/form/div/div/div[1]/div[3]/div/div/div"
                 "/input")
            )

        )
        password_input.send_keys(config.UPWORK_PASSWORD)

        password_field = WebDriverWait(active_driver, 30).until(
            EC.visibility_of_element_located(
                (By.XPATH,
                 "/html/body/div[4]/div/div/div/main/div/div/div[2]/div[2]/div/form/div/div/div[1]/div[3]/div/div/div"
                 "/input")
            )

        )
        password_field.send_keys(Keys.ENTER)

        logger.info(f'Pausing for {config.VERIFICATION_PAUSE} seconds for credentials verification')
        time.sleep(config.VERIFICATION_PAUSE)
    except Exception:
        logger.warning('Automated login inputs not found or blocked during re-login; continuing')


def recreate_driver_if_needed(current_driver):
    if current_driver and is_driver_alive(current_driver):
        return current_driver
    try:
        if current_driver:
            try:
                current_driver.quit()
            except Exception:
                pass
    finally:
        new_driver = get_driver_with_retry(chrome_versions=config.CHROME_VERSIONS, max_attempts=config.MAX_ATTEMPTS)
        if new_driver:
            login_to_upwork(new_driver)
        return new_driver


def main():
    """
    Main function for scraping job postings from Upwork.

    Returns:
        bool: True if the scraping process completed successfully, False otherwise.

    This function connects to the database, configures the web driver, logs into site, and then starts an infinite loop
    to continuously scrape job postings. It scrolls down the page to load more job postings, extracts job details, and
    stores them in the database. It refreshes the browser after each scraping cycle and pauses for the specified number
    of hours before continuing to the next cycle. If an error occurs during the scraping process, it prints the error
    message and returns False.
    """
    try:
        # Connect to database
        conn, cursor = connect_to_db()

        # Create table (if it does not exist)
        create_db(conn, cursor)

        # Configure the undetected_chromedriver options
        logger.info('Launching driver')
        driver = get_driver_with_retry(chrome_versions=config.CHROME_VERSIONS, max_attempts=config.MAX_ATTEMPTS)
        logger.info(f'driver: {driver}')

        if driver:
            # Login
            user_login_page = 'https://www.upwork.com/ab/account-security/login'
            logger.info(f'Navigating to `{user_login_page}`')
            driver.get(user_login_page)
            logger.info('Pausing for windows to fully load')
            time.sleep(25)

            logger.info('Switching to main window')
            all_windows = driver.window_handles
            driver.switch_to.window(all_windows[-1])

            try:
                logger.info('Submitting username')
                username_input = WebDriverWait(driver, 30).until(
                    EC.visibility_of_element_located(
                        (By.XPATH,
                         "/html/body/div[4]/div/div/div/main/div/div/div[2]/div[2]/form/div/div/div[1]/div[3]/div/div/div/"
                         "div/input")
                    )
                )
                username_input.send_keys(config.UPWORK_USERNAME)

                username_field = WebDriverWait(driver, 30).until(
                    EC.visibility_of_element_located(
                        (By.XPATH,
                         "/html/body/div[4]/div/div/div/main/div/div/div[2]/div[2]/form/div/div/div[1]/div[3]/div/div/div/"
                         "div/input")
                    )
                )
                username_field.send_keys(Keys.ENTER)

                logger.info('Submitting password')
                password_input = WebDriverWait(driver, 30).until(
                    EC.visibility_of_element_located(
                        (By.XPATH,
                         "/html/body/div[4]/div/div/div/main/div/div/div[2]/div[2]/div/form/div/div/div[1]/div[3]/div/div/div"
                         "/input")
                    )

                )
                password_input.send_keys(config.UPWORK_PASSWORD)

                password_field = WebDriverWait(driver, 30).until(
                    EC.visibility_of_element_located(
                        (By.XPATH,
                         "/html/body/div[4]/div/div/div/main/div/div/div[2]/div[2]/div/form/div/div/div[1]/div[3]/div/div/div"
                         "/input")
                    )

                )
                password_field.send_keys(Keys.ENTER)

                logger.info(f'Pausing for {config.VERIFICATION_PAUSE} seconds for credentials verification')
                time.sleep(config.VERIFICATION_PAUSE)
            except Exception as e:
                logger.warning('Automated login inputs not found or blocked; proceeding to Best Matches directly')

            # Repeat scraping in a loop
            while True:
                logger.info('--- Starting new scrape cycle (fresh session) ---')
                # Always start from scratch: close existing driver and create a new one
                if driver:
                    try:
                        driver.quit()
                    except Exception:
                        pass
                    driver = None

                driver = get_driver_with_retry(chrome_versions=config.CHROME_VERSIONS, max_attempts=config.MAX_ATTEMPTS)
                if not driver:
                    logger.error('Unable to create WebDriver; sleeping 30s and retrying...')
                    time.sleep(30)
                    continue

                # Login fresh each cycle
                login_to_upwork(driver)

                # Go to target url
                logger.info("Redirecting to Best Matches")
                driver.get('https://www.upwork.com/nx/find-work/best-matches')
                time.sleep(10)
                # Explicitly refresh to force latest jobs to load
                try:
                    logger.info('Refreshing page to load latest posts')
                    driver.refresh()
                    time.sleep(5)
                except Exception:
                    logger.warning('Standard refresh failed; attempting hard reload')
                    try:
                        driver.execute_script("location.reload(true);")
                        time.sleep(5)
                    except Exception:
                        logger.warning('Hard reload failed; continuing without refresh')

                # Scroll down using keyboard actions
                logger.info('Scrolling down page')
                body = driver.find_elements('xpath', "/html/body")
                for i in range(0, 12):  # Just an arbitrary number of page downs
                    body[-1].send_keys(Keys.PAGE_DOWN)
                    time.sleep(2)
                driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
                timeout_wait = 300

                # Wait for at least one job link to appear
                logger.info(f'Waiting for job links (timeout {timeout_wait}s)...')
                wait = WebDriverWait(driver, timeout_wait)
                wait.until(EC.presence_of_element_located((By.XPATH, "//a[contains(@href, '/jobs/')]")))

                # Collect job links
                raw_links = driver.find_elements(By.XPATH, "//a[contains(@href, '/jobs/')]")
                job_urls_seen = set()
                job_entries = []
                for link in raw_links:
                    try:
                        url = link.get_attribute('href') or ''
                        if not url:
                            continue
                        if any(bad in url for bad in ['ontology_skill_uid', 'search/saved', 'search/jobs/saved']):
                            continue
                        url = url.split('/?')[0]
                        title = (link.text or '').strip()
                        if not title:
                            # Some anchors have no visible text; skip
                            continue
                        # Deduplicate by url
                        if url in job_urls_seen:
                            continue
                        job_urls_seen.add(url)

                        # Try to get a container for richer fields
                        description_text = ''
                        proposals_text = ''
                        posted_text = ''
                        tags_list = []
                        try:
                            container = None
                            for ancestor_xpath in [
                                './ancestor::section[1]',
                                './ancestor::article[1]',
                                './ancestor::div[1]',
                            ]:
                                try:
                                    container = link.find_element(By.XPATH, ancestor_xpath)
                                    if container:
                                        break
                                except Exception:
                                    continue
                            if container:
                                # Description: choose the longest paragraph-like text not equal to title
                                text_candidates = []
                                for elem_xpath in [".//p", ".//div", ".//span"]:
                                    for el in container.find_elements(By.XPATH, elem_xpath):
                                        t = (el.text or '').strip()
                                        if t and t != title:
                                            text_candidates.append(t)
                                if text_candidates:
                                    description_text = max(text_candidates, key=len)

                                # Proposals
                                try:
                                    prop_el = container.find_element(By.XPATH, ".//*[contains(., 'Proposals')]")
                                    proposals_text = prop_el.text
                                except Exception:
                                    pass

                                # Posted time
                                try:
                                    posted_el = container.find_element(By.XPATH, ".//*[contains(., 'ago') or contains(., 'yesterday') or contains(., 'week')]")
                                    posted_text = posted_el.text
                                except Exception:
                                    pass
                        except Exception:
                            pass

                        # Skip if description mentions any banned country
                        if description_text:
                            lowered = description_text.lower()
                            banned_list = getattr(config, 'BANNED_COUNTRIES', [])
                            if any(bc.lower() in lowered for bc in banned_list):
                                continue

                        job_entries.append({
                            'url': url,
                            'title': title,
                            'description': description_text,
                            'proposals': proposals_text,
                            'posted': posted_text,
                            'tags': tags_list,
                        })
                    except Exception:
                        continue

                logger.info(f'Found {len(job_entries)} job entries')

                # Persist jobs
                for entry in job_entries:
                    job_id = generate_job_id(entry['title'])
                    job_url = entry['url']
                    posted_date = None
                    if entry['posted']:
                        try:
                            posted_date = calculate_posted_datetime(entry['posted'])
                        except Exception:
                            posted_date = None
                    job_title = entry['title']
                    job_description = entry['description'] or ''
                    job_tags = '[]'
                    job_proposals = ''
                    if entry['proposals']:
                        try:
                            job_proposals = clean_job_proposals(entry['proposals'])
                        except Exception:
                            job_proposals = ''

                    cursor.execute('SELECT COUNT(*) FROM jobs WHERE job_id = ?', (job_id,))
                    count = cursor.fetchone()[0]
                    if count > 0:
                        logger.info(f'    Job ID #{job_id} already exists. Updating job proposals...')
                        cursor.execute('UPDATE jobs SET job_proposals = ?, updated_at = ? WHERE job_id = ?', (
                            job_proposals, datetime.now(), job_id))
                    else:
                        logger.info(f'Storing `{job_title}` job in database')
                        cursor.execute(
                            'INSERT INTO jobs (job_id, job_url, job_title, posted_date, job_description, job_tags, job_proposals) VALUES (?, ?, ?, ?, ?, ?, ?)',
                            (job_id, job_url, job_title, posted_date, job_description, job_tags, job_proposals)
                        )
                        # Notify Telegram for new job
                        notify_new_job({
                            'job_id': job_id,
                            'job_url': job_url,
                            'job_title': job_title,
                            'posted_date': posted_date,
                            'job_description': job_description,
                            'job_tags': job_tags,
                            'job_proposals': job_proposals,
                        })
                    conn.commit()

                # After Best Matches, also visit additional search pages
                for search_url in getattr(config, 'SEARCH_PAGES', []):
                    try:
                        logger.info(f'Scraping search page: {search_url}')
                        search_entries = scrape_search_page(driver, search_url)
                        logger.info(f'Found {len(search_entries)} entries on search page')

                        for entry in search_entries:
                            job_id = generate_job_id(entry['title'])
                            job_url = entry['url']
                            posted_date = None
                            if entry['posted']:
                                try:
                                    posted_date = calculate_posted_datetime(entry['posted'])
                                except Exception:
                                    posted_date = None
                            job_title = entry['title']
                            job_description = entry['description'] or ''
                            job_tags = '[]'
                            job_proposals = ''
                            if entry['proposals']:
                                try:
                                    job_proposals = clean_job_proposals(entry['proposals'])
                                except Exception:
                                    job_proposals = ''

                            cursor.execute('SELECT COUNT(*) FROM jobs WHERE job_id = ?', (job_id,))
                            count = cursor.fetchone()[0]
                            if count > 0:
                                logger.info(f'    Job ID #{job_id} already exists. Updating job proposals...')
                                cursor.execute('UPDATE jobs SET job_proposals = ?, updated_at = ? WHERE job_id = ?', (
                                    job_proposals, datetime.now(), job_id))
                            else:
                                logger.info(f'Storing `{job_title}` job from search page in database (search)')
                                cursor.execute(
                                    'INSERT INTO jobs (job_id, job_url, job_title, posted_date, job_description, job_tags, job_proposals) VALUES (?, ?, ?, ?, ?, ?, ?)',
                                    (job_id, job_url, job_title, posted_date, job_description, job_tags, job_proposals)
                                )

                                notify_new_job({
                                    'job_id': job_id,
                                    'job_url': job_url,
                                    'job_title': job_title,
                                    'posted_date': posted_date,
                                    'job_description': job_description,
                                    'job_tags': job_tags,
                                    'job_proposals': job_proposals,
                                })
                            conn.commit()
                    except Exception as exc:
                        logger.exception(f'Failed scraping search page: {search_url} - {exc}')

                # End of cycle: close browser and sleep until next run
                try:
                    logger.info('Closing browser at end of cycle...')
                    driver.quit()
                except Exception:
                    pass
                driver = None

                logger.info(f"Sleeping {config.SCRAPE_INTERVAL_MINUTES} minutes before next check")
                time.sleep(config.SCRAPE_INTERVAL_MINUTES * 60)

        else:
            logger.error("Couldn't load driver")

    except Exception as e:
        logger.error(e)
        return False

    finally:
        logger.info('Closing connection to database')
        cursor.close()
        conn.close()


if __name__ == '__main__':
    main()
