import requests
from celery import shared_task, group, chord
from celery.result import AsyncResult
from .utils import check_broken_links
from .models import Project, BrokenLink, BrokenLinkAnalysisStatus, Content, AnalysisResult
from project_management.models import Project
from django.utils import timezone
from celery.utils.log import get_task_logger
from .utils import check_link, should_check_link
from urllib.parse import urljoin
from bs4 import BeautifulSoup
import logging
from itertools import islice
from django.db import transaction
from celery.exceptions import SoftTimeLimitExceeded

logger = get_task_logger(__name__)

def chunked_iterable(iterable, size):
    it = iter(iterable)
    while True:
        chunk = tuple(islice(it, size))
        if not chunk:
            break
        yield chunk

@shared_task
def check_single_link(url, source_url, project_id):
    if should_check_link(url):
        result = check_link(url, source_url)
        if result:
            return {
                'source': source_url,
                'url': url,
                'status': result['status'],
                'context': result['context'],
                'is_no_response': result['status'] == 'No Response'
            }
    return None

@shared_task(bind=True)
def process_content(self, content_id, project_id):
    content = Content.objects.get(id=content_id)
    soup = BeautifulSoup(content.raw_content, 'html.parser')
    links = soup.find_all(['a', 'link', 'script', 'img'], href=True) + soup.find_all(['a', 'link', 'script', 'img'], src=True)
    
    tasks = []
    for link in links:
        href = link.get('href') or link.get('src')
        if href and href != '#':
            full_url = urljoin(content.url, href)
            tasks.append(check_single_link.s(full_url, content.url, project_id))
    
    return group(tasks)()


@shared_task(bind=True)
def save_results(self, results, project_id):
    logger.info(f"Saving results for project {project_id}")
    project = Project.objects.get(id=project_id)
    broken_links = [r for r in results if r is not None]
    
    BrokenLink.objects.filter(project=project).delete()
    BrokenLink.objects.bulk_create([
        BrokenLink(
            project=project,
            source_url=link['source'],
            broken_url=link['url'],
            status_code=link['status'],
            context=link['context'],
            is_no_response=link['is_no_response']
        ) for link in broken_links
    ])
    
    status = BrokenLinkAnalysisStatus.objects.get(project=project)
    status.is_analyzing = False
    status.last_analysis = timezone.now()
    status.total_links = len(results)
    status.broken_links = len(broken_links)
    status.no_response_links = sum(1 for link in broken_links if link['is_no_response'])
    status.save()
    
    logger.info(f"Completed broken link analysis for project {project_id}. Found {len(broken_links)} broken links out of {len(results)} total links.")




@shared_task(bind=True, soft_time_limit=3600, time_limit=3660)
def analyze_broken_links_task(self, project_id):
    project = Project.objects.get(id=project_id)
    
    status, _ = BrokenLinkAnalysisStatus.objects.get_or_create(project=project)
    if not status.is_analyzing:
        status.is_analyzing = True
        status.progress = 0
        status.total_links = 0
        status.broken_links = 0
        status.save()

    try:
        contents = Content.objects.filter(project=project)
        total_links = 0
        analysis_result, _ = AnalysisResult.objects.update_or_create(
            project=project,
            defaults={'last_updated': timezone.now()}
        )
        
        existing_links = set(BrokenLink.objects.filter(analysis_result=analysis_result).values_list('source_url', 'broken_url'))

        for content in contents:
            soup = BeautifulSoup(content.raw_content, 'html.parser')
            links = soup.find_all(['a', 'link', 'script', 'img'], href=True) + soup.find_all(['a', 'link', 'script', 'img'], src=True)
            total_links += len(links)

            for link in links:
                href = link.get('href') or link.get('src')

                if href is not None:
                    full_url = urljoin(content.url, href)
                    result = check_link(full_url, content.url)

                    if result:
                        link_tuple = (content.url, full_url)
                        BrokenLink.objects.update_or_create(
                            analysis_result=analysis_result,
                            source_url=content.url,
                            broken_url=full_url,
                            defaults={
                                'status_code': result['status'],
                                'context': result['context'],
                                'is_no_response': result['status'] == 'No Response'
                            }
                        )
                        existing_links.discard(link_tuple)

            status.progress += len(links)
            status.save()
            self.update_state(state='PROGRESS', meta={'current': status.progress, 'total': total_links})

        status.total_links = total_links
        status.save()

        # Clean up links that no longer exist
        BrokenLink.objects.filter(
            analysis_result=analysis_result,
            source_url__in=[url for url, _ in existing_links],
            broken_url__in=[url for _, url in existing_links]
        ).delete()

        status.is_analyzing = False
        status.broken_links = BrokenLink.objects.filter(analysis_result=analysis_result).count()
        status.no_response_links = BrokenLink.objects.filter(analysis_result=analysis_result, is_no_response=True).count()
        status.last_analysis = timezone.now()
        status.task_id = None
        status.save()

        logger.info(f"Completed broken link analysis for project {project_id}. Found {status.broken_links} broken links out of {total_links} total links.")

    except Exception as e:
        logger.error(f"Error during analysis for project {project_id}: {str(e)}")
        status.is_analyzing = False
        status.error_message = str(e)
        status.save()