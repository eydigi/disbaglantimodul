import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from celery.utils.log import get_task_logger
from internal_link_suggestions.models import Content
from urllib.parse import urlparse, urljoin
import re
from requests.exceptions import RequestException, SSLError, Timeout
import time

logger = get_task_logger(__name__)

def get_link_context(soup, link):
    try:
        # Linkin kendisini al
        link_html = str(link)
        
        # Linkin bulunduğu en yakın anlamlı elementi bul
        parent = link.find_parent(['p', 'div', 'li', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
        if parent:
            context = str(parent)
        else:
            # Eğer anlamlı bir ebeveyn bulunamazsa, linkin etrafındaki metni al
            context = link.string or ""
        
        # Bağlamı kısalt
        if len(context) > 200:
            context = context[:100] + "..." + context[-100:]
        
        return f"Link: {link_html}\nContext: {context}"
    except Exception as e:
        return f"Error getting context: {str(e)}"

def is_valid_url(url):
    try:
        result = urlparse(url)
        return all([result.scheme, result.netloc])
    except ValueError:
        return False

def should_check_link(url):
    if re.search(r'\.(svg|css|js|png|jpg|jpeg|gif|ico)$', url, re.I):
        return False
    if url.startswith('data:'):
        return False
    if url.startswith(('mailto:', 'tel:', 'ftp:')):
        return False
    return True
      

def check_link(url, source_url, max_retries=3, backoff_factor=0.3):
    # Check for fragment identifiers (#)
    if url == '#' or (not is_valid_url(url) and '#' in url):
        return {'status': 'SEO Warning', 'context': "The link contains only '#' or is not a valid URL with '#'. This may not provide value for SEO purposes."}
    
    if not is_valid_url(url):
        return None
    
    if not should_check_link(url):
        return None

    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
    }
    for i in range(max_retries):
        try:
            response = requests.head(url, timeout=10, allow_redirects=True, headers=headers)
            if response.status_code == 405:
                # If HEAD request is not allowed, try GET
                response = requests.get(url, timeout=10, allow_redirects=True, headers=headers)
            if response.status_code >= 400:
                return {'status': str(response.status_code), 'context': f"HTTP Error: {response.status_code}"}
            return None  # Link is valid
        except (SSLError, Timeout):
            if i == max_retries - 1:
                return {'status': 'No Response', 'context': "Request timed out"}
            time.sleep(backoff_factor * (2 ** i))
        except RequestException as e:
            if i == max_retries - 1:
                return {'status': 'No Response', 'context': f"Connection error: {str(e)}"}
            time.sleep(backoff_factor * (2 ** i))
    return {'status': 'No Response', 'context': "No response after multiple attempts"}

def check_broken_links(project, update_state_callback):
    broken_links = []
    contents = Content.objects.filter(project=project)
    total_links = 0
    processed_links = 0
    for content in contents:
        soup = BeautifulSoup(content.raw_content, 'html.parser')
        links = soup.find_all(['a', 'link', 'script', 'img'], href=True) + soup.find_all(['a', 'link', 'script', 'img'], src=True)
        
        for link in links:
            href = link.get('href') or link.get('src')
            if href and href != '#':
                full_url = urljoin(content.url, href)
                if should_check_link(full_url):
                    total_links += 1
                    result = check_link(full_url, content.url)
                    if result:
                        broken_links.append({
                            'source': content.url,
                            'url': full_url,
                            'status': result['status'],
                            'context': get_link_context(soup, link) + "\n" + result['context']
                        })
                
                processed_links += 1
                update_state_callback(processed_links, total_links)
        # Her içerik işlendikten sonra kısa bir bekleme ekleyelim
        time.sleep(0.1)
    logger.info(f"Finished checking links for project {project.id}. Processed {processed_links} out of {total_links} links.")
    return broken_links, total_links