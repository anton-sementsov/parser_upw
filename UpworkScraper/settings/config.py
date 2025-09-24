# Upwork credentials
UPWORK_USER_NAME = "Varvara"             # First name shown in your Upwork UI
UPWORK_USERNAME = "vavavivava6@gmail.com"      # Your Upwork email/username
UPWORK_PASSWORD = "! Vavav22-ivava6"          # Your Upwork password

# Chrome driver settings
CHROME_VERSIONS = [139, 140, 141]             # Replace 123 with your Chrome MAJOR version(s), e.g. [90, 123]
MAX_ATTEMPTS = 5

# Login wait time (seconds) to complete 2FA/captcha if any
VERIFICATION_PAUSE = 30

# Scrape interval (minutes)
SCRAPE_INTERVAL_MINUTES = 15

# Telegram
TELEGRAM_BOT_TOKEN = "8335278647:AAG2XuefsP8bldm-Co5rGinP3Lep-yxUDAk"
TELEGRAM_CHAT_ID = "-1002669795679"
TELEGRAM_THREAD_ID = 1012

# Additional search pages to scrape each cycle (after Best Matches)
SEARCH_PAGES = [
    "https://www.upwork.com/nx/search/jobs/?q=next.js&sort=recency",
    "https://www.upwork.com/nx/search/jobs/?q=%28front%20AND%20end%29&sort=recency",
    "https://www.upwork.com/nx/search/jobs/?q=react%20AND%20NOT%20native&sort=recency",
    "https://www.upwork.com/nx/search/jobs/?q=gsap&sort=recency",
    "https://www.upwork.com/nx/search/jobs/?q=sanity%20next&sort=recency",
    "https://www.upwork.com/nx/search/jobs/?q=%28shopify%20AND%20developer%29&sort=recency",
]

# Countries to skip (case-insensitive)
BANNED_COUNTRIES = [
    "pakistan",
    "india",
    "uzbekistan",
    "nigeria",
    "south africa",
    "kenya",
]