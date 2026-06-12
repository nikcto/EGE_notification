import requests
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
import urllib3
import logging

# Disable SSL verification warnings for resilience
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
logger = logging.getLogger(__name__)


class StudentVerificationError(ValueError):
    """Учётные данные не прошли проверку на сайте РЦОИ."""


def _is_login_page(soup) -> bool:
    """Страница с формой входа — авторизация не удалась."""
    return (
        soup.find("input", {"name": "family"}) is not None
        and soup.find("input", {"name": "number"}) is not None
        and soup.find("input", {"name": "do"}) is not None
    )


def clean_score(score_str):
    """
    Cleans score values by returning None for placeholder dashes,
    converting valid digits to integers, and keeping other string values.
    """
    if not score_str or score_str == '-':
        return None
    try:
        return int(score_str)
    except ValueError:
        return score_str

def fetch_with_requests(surname: str, name: str, patronymic: str, passport: str, region: str) -> str:
    """
    Logs in and fetches the results page using a requests.Session for a specific student.
    Uses tenacity-style manual retry inside get_results_page.
    """
    session = requests.Session()
    session.verify = False  # Ignore certificate errors if any
    
    index_url = "https://rcoi02.ru/gia11_result/index.php"
    login_url = "https://rcoi02.ru/gia11_result/lk/pageall.php"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Referer": index_url
    }
    
    logger.debug(f"Parser: GET index page for {surname}...")
    resp = session.get(index_url, headers=headers, timeout=15)
    resp.raise_for_status()
    
    # Get form "do" input value (normally "Войти")
    soup = BeautifulSoup(resp.content.decode('utf-8', errors='ignore'), 'html.parser')
    do_value = "Войти"
    submit_input = soup.find('input', {'name': 'do'})
    if submit_input:
        do_value = submit_input.get('value', 'Войти')
        
    post_data = {
        "family": surname,
        "name": name,
        "father": patronymic,
        "number": passport,
        "region": region,
        "pd": "on",
        "do": do_value
    }
    
    logger.info(f"Parser: POST login to pageall.php for {surname} {name}...")
    post_headers = headers.copy()
    post_headers["Content-Type"] = "application/x-www-form-urlencoded"
    
    resp_post = session.post(login_url, data=post_data, headers=post_headers, timeout=15)
    resp_post.raise_for_status()
    
    return resp_post.content.decode('utf-8', errors='replace')

def fetch_with_playwright(surname: str, name: str, patronymic: str, passport: str, region: str) -> str:
    """
    Fallback method that runs headlessly via Playwright in case requests fails.
    """
    logger.warning(f"Parser: Falling back to Playwright for {surname}...")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        logger.error("Playwright library is not installed. Cannot use fallback.")
        raise RuntimeError("Playwright library is not installed.")
        
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context(ignore_https_errors=True)
            page = context.new_page()
            
            index_url = "https://rcoi02.ru/gia11_result/index.php"
            logger.info("Playwright: Navigating to index...")
            page.goto(index_url, timeout=30000)
            
            logger.info("Playwright: Filling credentials...")
            page.fill("input[name='family']", surname)
            page.fill("input[name='name']", name)
            page.fill("input[name='father']", patronymic)
            page.fill("input[name='number']", passport)
            
            # Select the region
            page.select_option("select[name='region']", label=region)
            
            # Check personal data agreement checkbox
            page.check("input[name='pd']")
            
            # Click submit button
            logger.info("Playwright: Clicking login...")
            page.click("input[name='do']")
            
            # Wait for content to load
            page.wait_for_load_state("networkidle", timeout=15000)
            
            content = page.content()
            return content
        finally:
            browser.close()

# Decorated request runner helper with tenacity retry
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(requests.RequestException),
    reraise=True
)
def fetch_retry_helper(surname: str, name: str, patronymic: str, passport: str, region: str) -> str:
    return fetch_with_requests(surname, name, patronymic, passport, region)

def get_results_page(surname: str, name: str, patronymic: str, passport: str, region: str) -> str:
    """
    Fetches the page content trying requests first, then falling back to Playwright.
    """
    try:
        return fetch_retry_helper(surname, name, patronymic, passport, region)
    except Exception as e:
        logger.error(f"Parser: requests.Session failed for {surname}: {e}. Attempting Playwright fallback...")
        try:
            return fetch_with_playwright(surname, name, patronymic, passport, region)
        except Exception as pw_err:
            logger.critical(f"Parser: Both requests and Playwright fallback failed for {surname}. Error: {pw_err}")
            raise

def _extract_results_from_soup(soup) -> tuple[dict, bool, bool]:
    """
    Извлекает результаты из HTML.
    Возвращает (results, найдена_таблица_расписания, найдена_таблица_результатов).
    """
    tables = soup.find_all('table')
    
    results = {}
    table_results = None
    table_schedules = None
    
    for table in tables:
        headers = [th.text.strip() for th in table.find_all('th')]
        if not headers:
            first_row = table.find('tr')
            if first_row:
                headers = [td.text.strip() for td in first_row.find_all(['td', 'th'])]
                
        if 'Первичный балл' in headers:
            table_results = table
        elif 'Пункт проведения экзамена' in headers:
            table_schedules = table

    # 1. Parse schedules (Table 1)
    if table_schedules:
        rows = table_schedules.find_all('tr')
        if rows:
            headers = [th.text.strip() for th in rows[0].find_all(['th', 'td'])]
            try:
                date_idx = headers.index('Дата')
                subject_idx = headers.index('Предмет')
            except ValueError:
                date_idx, subject_idx = 0, 2
                
            for row in rows[1:]:
                cols = [col.text.strip() for col in row.find_all('td')]
                if len(cols) > max(date_idx, subject_idx):
                    subject = cols[subject_idx]
                    date = cols[date_idx]
                    results[subject] = {
                        "date": date,
                        "primary": None,
                        "test": None,
                        "status": "ожидается",
                        "appeal": ""
                    }

    # 2. Parse results (Table 0)
    if table_results:
        rows = table_results.find_all('tr')
        if rows:
            headers = [th.text.strip() for th in rows[0].find_all(['th', 'td'])]
            try:
                date_idx = headers.index('Дата')
                subject_idx = headers.index('Предмет')
                primary_idx = headers.index('Первичный балл')
                test_idx = headers.index('Тестовый балл')
                status_idx = headers.index('Статус экзамена')
                appeal_idx = headers.index('Апелляция')
            except ValueError:
                date_idx, subject_idx, primary_idx, test_idx, status_idx, appeal_idx = 0, 2, 3, 4, 5, 6
                
            for row in rows[1:]:
                cols = [col.text.strip() for col in row.find_all('td')]
                if len(cols) > max(date_idx, subject_idx, primary_idx, test_idx, status_idx, appeal_idx):
                    subject = cols[subject_idx]
                    date = cols[date_idx]
                    primary = clean_score(cols[primary_idx])
                    test = clean_score(cols[test_idx])
                    status = cols[status_idx]
                    appeal = cols[appeal_idx]
                    if appeal == "отсутствует":
                        appeal = ""
                    
                    results[subject] = {
                        "date": date,
                        "primary": primary,
                        "test": test,
                        "status": status,
                        "appeal": appeal
                    }

    return results, table_schedules is not None, table_results is not None


def _site_error_message(soup) -> str:
    error_alert = soup.find(class_='alert') or soup.find(class_='error') or soup.find('div', class_='alert-danger')
    if error_alert:
        return f" Ошибка сайта: {error_alert.text.strip()}"
    return ""


def parse_results(html_content: str) -> dict:
    """
    Extracts exam schedules and results from HTML tables.
    """
    soup = BeautifulSoup(html_content, 'html.parser')

    if _is_login_page(soup):
        raise StudentVerificationError(
            f"Не удалось войти с указанными данными.{_site_error_message(soup)}"
        )

    results, has_schedule_table, has_results_table = _extract_results_from_soup(soup)

    if not has_schedule_table and not has_results_table:
        raise StudentVerificationError(
            f"На странице не найдена таблица с экзаменами.{_site_error_message(soup)}"
        )

    if not results:
        raise StudentVerificationError(
            f"Таблица экзаменов пуста — проверьте введённые данные.{_site_error_message(soup)}"
        )

    return results


def verify_student_credentials(
    surname: str, name: str, patronymic: str, passport: str, region: str
) -> dict:
    """
    Проверяет учётные данные: успешный вход и наличие таблицы экзаменов с данными.
    """
    html = get_results_page(surname, name, patronymic, passport, region)
    return parse_results(html)


def get_parsed_results(surname: str, name: str, patronymic: str, passport: str, region: str) -> dict:
    """
    Fetches results for a specific student.
    """
    return verify_student_credentials(surname, name, patronymic, passport, region)
