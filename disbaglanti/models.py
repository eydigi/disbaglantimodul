from django.db import models
from project_management.models import Project
from internal_link_suggestions.models import Content
from django.utils import timezone

class AnalysisResult(models.Model):
    project = models.ForeignKey(Project, on_delete=models.CASCADE, related_name='analysis_results')
    last_updated = models.DateTimeField(auto_now=True)
    def __str__(self):
        return f"Analysis Result for {self.project.name} - {self.last_updated}"

class BrokenLink(models.Model):
    analysis_result = models.ForeignKey(AnalysisResult, on_delete=models.CASCADE, related_name='broken_links')
    source_url = models.URLField()
    broken_url = models.URLField()
    status_code = models.CharField(max_length=20)
    context = models.TextField(blank=True, null=True)
    is_no_response = models.BooleanField(default=False)
    checked_at = models.DateTimeField(auto_now=True)
    def __str__(self):
        return f"{self.source_url} -> {self.broken_url}"
    class Meta:
        unique_together = ('analysis_result', 'source_url', 'broken_url')
    @property
    def project(self):
        return self.analysis_result.project

class BrokenLinkAnalysisStatus(models.Model):
    project = models.OneToOneField(Project, on_delete=models.CASCADE, related_name='broken_link_analysis_status')
    is_analyzing = models.BooleanField(default=False)
    progress = models.IntegerField(default=0)
    total_links = models.IntegerField(default=0)
    broken_links = models.IntegerField(default=0)
    no_response_links = models.IntegerField(default=0)
    last_analysis = models.DateTimeField(null=True, blank=True)
    start_time = models.DateTimeField(null=True, blank=True)  # Yeni eklenen alan
    error_message = models.TextField(blank=True, null=True)
    task_id = models.CharField(max_length=100, blank=True, null=True)
    def __str__(self):
        return f"Analysis Status for {self.project.name}"