from django.urls import path
from . import views
app_name = 'disbaglanti'
urlpatterns = [
    path('<int:project_id>/broken-link-analysis/', views.broken_link_analysis, name='broken_link_analysis'),
    path('<int:project_id>/check-broken-link-status/', views.check_broken_link_status, name='check_broken_link_status'),
    path('<int:project_id>/cancel-analysis/', views.cancel_analysis, name='cancel_analysis'),
    path('<int:project_id>/get-analysis-results/', views.get_analysis_results, name='get_analysis_results'),
    path('reset-analysis-counters/<int:project_id>/', views.reset_analysis_counters, name='reset_analysis_counters'),
]