from django.shortcuts import render, get_object_or_404
from django.http import JsonResponse
from project_management.models import Project
from .models import BrokenLink, BrokenLinkAnalysisStatus, AnalysisResult
from .tasks import analyze_broken_links_task
from celery.result import AsyncResult
from django.template.loader import render_to_string
from django.db import transaction
from django.views.decorators.http import require_http_methods

def start_broken_link_analysis(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    status, created = BrokenLinkAnalysisStatus.objects.get_or_create(project=project)

    project.progress = 0
    project.save()

    if not status.is_analyzing:
        task = analyze_broken_links_task.delay(project_id)
        status.task_id = task.id
        status.save()
        return JsonResponse({'status': 'started', 'task_id': task.id})
    else:
        return JsonResponse({'status': 'already_running', 'task_id': status.task_id})

@transaction.atomic
def save_analysis_results(project, broken_links):
    # Mevcut analiz sonucunu al veya yeni oluştur
    analysis_result, created = AnalysisResult.objects.get_or_create(project=project)
    
    # Mevcut kırık linkleri al
    existing_links = set(BrokenLink.objects.filter(analysis_result=analysis_result).values_list('source_url', 'broken_url'))
    
    # Yeni kırık linkleri ekle veya güncelle
    for link in broken_links:
        link_tuple = (link['source_url'], link['broken_url'])
        if link_tuple not in existing_links:
            BrokenLink.objects.create(
                analysis_result=analysis_result,
                source_url=link['source_url'],
                broken_url=link['broken_url'],
                status_code=link['status_code'],
                context=link['context']
            )
        else:
            # Mevcut linki güncelle (örneğin, status_code veya context değişmiş olabilir)
            BrokenLink.objects.filter(
                analysis_result=analysis_result,
                source_url=link['source_url'],
                broken_url=link['broken_url']
            ).update(
                status_code=link['status_code'],
                context=link['context']
            )
        existing_links.discard(link_tuple)
    
    # Artık mevcut olmayan kırık linkleri sil
    BrokenLink.objects.filter(
        analysis_result=analysis_result,
        source_url__in=[url for url, _ in existing_links],
        broken_url__in=[url for _, url in existing_links]
    ).delete()
    
    # Analiz sonucu tarihini güncelle
    analysis_result.last_updated = timezone.now()
    analysis_result.save()
    return analysis_result

def get_analysis_results(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    analysis_result = AnalysisResult.objects.filter(project=project).order_by('-last_updated').first()
    
    if analysis_result:
        broken_links = analysis_result.broken_links.all()
        seo_warnings = broken_links.filter(status_code='SEO Warning').count()
        no_response_links = broken_links.filter(is_no_response=True).count()
        http_errors = broken_links.exclude(status_code='SEO Warning').exclude(is_no_response=True).count()
    else:
        broken_links = []
        seo_warnings = no_response_links = http_errors = 0
    
    context = {
        'project': project,
        'analysis_result': analysis_result,
        'broken_links': broken_links,
        'seo_warnings': seo_warnings,
        'no_response_links': no_response_links,
        'http_errors': http_errors,
    }
    
    html = render_to_string('disbaglanti/analysis_results.html', context)
    return JsonResponse({'html': html})
def broken_link_analysis(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    status, created = BrokenLinkAnalysisStatus.objects.get_or_create(project=project)
    # Yeni analiz başlatılacaksa mevcut analiz durumunu sıfırla
    if request.method == 'POST':
        if not status.is_analyzing:
            # Analiz başlamadan önce sayaç ve metrikleri sıfırla
            status.processed_urls = 0
            status.save()
            # Analizi başlat
            task = analyze_broken_links_task.delay(project_id)
            status.task_id = task.id
            status.is_analyzing = True
            status.save()
            return JsonResponse({'status': 'started', 'task_id': task.id})
        else:
            return JsonResponse({'status': 'already_analyzing'})
    # En son analiz sonucunu al
    latest_analysis = AnalysisResult.objects.filter(project=project).order_by('-last_updated').first()
    
    if latest_analysis:
        broken_links = latest_analysis.broken_links.all()
    else:
        broken_links = BrokenLink.objects.none()
    
    context = {
        'project': project,
        'broken_links': broken_links,
        'no_response_links': broken_links.filter(is_no_response=True).count(),
        'status': status,
        'analysis_result': latest_analysis,
    }
    
    return render(request, 'disbaglanti/broken_link_analysis.html', context)

def check_broken_link_analysis_status(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    status = BrokenLinkAnalysisStatus.objects.get(project=project)
    
    if status.is_analyzing and status.task_id:
        task_result = AsyncResult(status.task_id)
        if task_result.state == 'PROGRESS':
            return JsonResponse({
                'is_analyzing': True,
                'progress': task_result.info.get('progress', 0),
                'total_links': task_result.info.get('total', 0),
            })
        elif task_result.state == 'SUCCESS':
            status.is_analyzing = False
            status.save()
            return JsonResponse({
                'is_analyzing': False,
                'progress': 100,
                'total_links': status.total_links,
            })
    
    return JsonResponse({
        'is_analyzing': status.is_analyzing,
        'progress': status.progress,
        'total_links': status.total_links,
        'last_analysis': status.last_analysis.isoformat() if status.last_analysis else None,
    })

@require_http_methods(["GET"])
def check_broken_link_status(request, project_id):
    try:
        status = BrokenLinkAnalysisStatus.objects.get(project_id=project_id)
        task_result = AsyncResult(status.task_id) if status.task_id else None
        if task_result and task_result.state == 'FAILURE':
            status.is_analyzing = False
            status.error_message = str(task_result.result)
            status.save()
        return JsonResponse({
            'is_analyzing': status.is_analyzing,
            'progress': status.progress,
            'total_links': status.total_links,
            'error_message': status.error_message,
        })
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
@require_http_methods(["POST"])
def start_broken_link_analysis(request, project_id):
    try:
        status, created = BrokenLinkAnalysisStatus.objects.get_or_create(project_id=project_id)
        
        if not status.is_analyzing:
            task = analyze_broken_links_task.delay(project_id)
            status.is_analyzing = True
            status.task_id = task.id
            status.save()
            return JsonResponse({'status': 'started', 'task_id': task.id})
        else:
            return JsonResponse({'status': 'already_running', 'task_id': status.task_id})
    except Exception as e:
        return JsonResponse({'error': str(e)}, status=500)
    
    return JsonResponse({
        'is_analyzing': status.is_analyzing,
        'progress': status.progress,
        'total_links': status.total_links,
        'elapsed_time': elapsed_time,
        'broken_links': status.broken_links,
        'no_response_links': status.no_response_links,
        'last_analysis': status.last_analysis.isoformat() if status.last_analysis else None,
    })


def cancel_analysis(request, project_id):
    project = get_object_or_404(Project, id=project_id)
    status = BrokenLinkAnalysisStatus.objects.get(project=project)
    
    if status.is_analyzing and status.task_id:
        AsyncResult(status.task_id).revoke(terminate=True)
        status.is_analyzing = False
        status.error_message = "Analiz kullanıcı tarafından iptal edildi."
        status.save()
        return JsonResponse({'status': 'cancelled'})
    else:
        return JsonResponse({'status': 'not_analyzing'})

def reset_analysis_counters(request, project_id):
    if request.method == "POST":
        project = get_object_or_404(Project, id=project_id)
        status, created = BrokenLinkAnalysisStatus.objects.get_or_create(project=project)
        
        # Sayaçları sıfırla
        status.progress = 0
        status.total_links = 0
        status.broken_links = 0
        status.no_response_links = 0
        status.save()

        return JsonResponse({'message': 'Sayaçlar sıfırlandı'})        