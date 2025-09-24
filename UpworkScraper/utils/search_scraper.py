import time
from typing import List, Dict
from settings import config

from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC


def scrape_search_page(driver, url: str) -> List[Dict[str, str]]:
    """
    Navigate to a search page URL, wait, scroll, and collect job entries.

    Returns a list of dicts: {url, title, description, proposals, posted, tags}
    Filters out jobs whose description mentions India or Pakistan.
    """
    driver.get(url)
    time.sleep(8)
    try:
        driver.refresh()
        time.sleep(4)
    except Exception:
        pass

    # Scroll to load more
    body = driver.find_elements('xpath', "/html/body")
    for _ in range(0, 10):
        body[-1].send_keys(Keys.PAGE_DOWN)
        time.sleep(1.5)
    driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")

    # Wait for any job tile
    wait = WebDriverWait(driver, 120)
    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "section[data-test='JobsList'] article[data-test='JobTile']")))

    # Collect from structured job tiles
    tiles = driver.find_elements(By.CSS_SELECTOR, "section[data-test='JobsList'] article[data-test='JobTile']")
    job_urls_seen = set()
    job_entries: List[Dict[str, str]] = []

    for tile in tiles:
        try:
            # Title and URL
            title_el = tile.find_element(By.CSS_SELECTOR, "h2.job-tile-title a[data-test*='job-tile-title-link']")
            href = (title_el.get_attribute('href') or '').strip()
            title = (title_el.text or '').strip()
            if not href or not title:
                continue
            if any(bad in href for bad in ['ontology_skill_uid', 'search/saved', 'search/jobs/saved']):
                continue
            href = href.split('/?')[0]
            if href in job_urls_seen:
                continue
            job_urls_seen.add(href)

            # Posted time
            posted_text = ''
            try:
                posted_small = tile.find_element(By.CSS_SELECTOR, "small[data-test='job-pubilshed-date']")
                posted_text = posted_small.text
            except Exception:
                pass

            # Description
            description_text = ''
            try:
                desc_p = tile.find_element(By.XPATH, ".//div[@data-test='UpCLineClamp JobDescription']//p")
                description_text = (desc_p.text or '').strip()
            except Exception:
                pass

            # Proposals
            proposals_text = ''
            try:
                prop_li = tile.find_element(By.CSS_SELECTOR, "li[data-test='proposals-tier']")
                proposals_text = (prop_li.text or '').strip()
            except Exception:
                pass

            # Tags
            tags_list: List[str] = []
            try:
                for btn in tile.find_elements(By.CSS_SELECTOR, "div[data-test='TokenClamp JobAttrs'] button[data-test='token'] span"):
                    tag_text = (btn.text or '').strip()
                    if tag_text:
                        tags_list.append(tag_text)
            except Exception:
                pass

            # Client info (payment verified, rating, spent, location)
            client_parts: List[str] = []
            try:
                client_ul = tile.find_element(By.CSS_SELECTOR, "ul[data-test='JobInfoClient']")
                # Payment verification
                try:
                    client_ul.find_element(By.CSS_SELECTOR, "li[data-test='payment-verified']")
                    client_parts.append("Payment verified")
                except Exception:
                    # If not verified, check explicit unverified marker
                    try:
                        client_ul.find_element(By.CSS_SELECTOR, "li[data-test='payment-unverified']")
                        client_parts.append("Payment unverified")
                    except Exception:
                        pass
                # Rating value
                try:
                    rating_text = client_ul.find_element(By.CSS_SELECTOR, "div.air3-rating-value-text").text
                    if rating_text:
                        client_parts.append(f"rating {rating_text}")
                except Exception:
                    pass
                # Total spent
                try:
                    spent_li = client_ul.find_element(By.CSS_SELECTOR, "li[data-test='total-spent']")
                    # Prefer amount + literal 'spent' exactly as shown
                    try:
                        amount = spent_li.find_element(By.TAG_NAME, 'strong').text
                        if amount:
                            client_parts.append(f"{amount} spent")
                    except Exception:
                        txt = (spent_li.text or '').strip()
                        if txt:
                            client_parts.append(txt)
                except Exception:
                    pass
                # Location
                try:
                    loc_li = client_ul.find_element(By.CSS_SELECTOR, "li[data-test='location']")
                    country = ''
                    # Preferred: the outer span with tabindex holds the visible text with an sr-only prefix inside
                    try:
                        outer_span = loc_li.find_element(By.CSS_SELECTOR, "span[tabindex]")
                        country = (outer_span.text or '').strip()
                    except Exception:
                        country = ''

                    # Fallback to the whole li text if needed
                    if not country:
                        try:
                            country = (loc_li.text or '').strip()
                        except Exception:
                            country = ''

                    if country:
                        # Remove possible screen-reader prefix
                        for prefix in ["Location ", "Location:", "Location\u00a0", "Location\n", "Location\t", "Location"]:
                            if country.startswith(prefix):
                                country = country[len(prefix):].strip()
                                break
                        # If multiple lines, keep the last visible token
                        if '\n' in country:
                            tokens = [t.strip() for t in country.split('\n') if t.strip()]
                            if tokens:
                                country = tokens[-1]
                    if country:
                        client_parts.append(country)
                except Exception:
                    pass
            except Exception:
                pass

            # Filter out by banned countries (from location)
            if client_parts:
                lowered_countries = [c.lower() for c in config.BANNED_COUNTRIES]
                for banned_country in lowered_countries:
                    if any(banned_country in part.lower() for part in client_parts):
                        # Skip entries with banned country in client info
                        raise Exception('Skipped due to banned country')

            # Filter out by keywords in description as a secondary safeguard
            if description_text:
                lowered = description_text.lower()
                for banned_country in getattr(config, 'BANNED_COUNTRIES', []):
                    if banned_country.lower() in lowered:
                        raise Exception('Skipped due to banned country in description')

            # Compose enriched description in order: Client, proposals, description
            client_info = ' | '.join(client_parts) if client_parts else ''
            parts: List[str] = []
            if client_info:
                parts.append(f"Client: {client_info}\n-")
            if proposals_text:
                parts.append(f"Proposals: {proposals_text}\n-")
            if description_text:
                parts.append(description_text)
            composed_description = "\n".join(parts)

            job_entries.append({
                'url': href,
                'title': title,
                'description': composed_description,
                'proposals': proposals_text,
                'posted': posted_text,
                'tags': tags_list,
            })
        except Exception:
            continue

    return job_entries


