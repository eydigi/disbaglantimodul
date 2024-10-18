from django import template

register = template.Library()

@register.filter
def filter_seo_warnings(broken_links):
    """
    SEO uyarısı gereken bağlantıları döndürür. # sembolü içeren bağlantılar SEO uyarısı olarak işaretlenir.
    """
    return [link for link in broken_links if '#' in link.broken_url]

@register.filter
def filter_http_errors(broken_links):
    """
    HTTP hatası olan bağlantıları döndüren filtre. 4xx ve 5xx statü kodları hatalı kabul edilir.
    """
    return [link for link in broken_links if link.status_code.startswith('4') or link.status_code.startswith('5')]

@register.filter
def filter_no_response(broken_links):
    """
    Yanıt vermeyen bağlantıları döndüren filtre. Yanıt alamadığımız bağlantıları işaretler.
    """
    return [link for link in broken_links if link.is_no_response]