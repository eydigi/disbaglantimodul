from django.db import migrations, models
import django.db.models.deletion

def forward_func(apps, schema_editor):
    BrokenLink = apps.get_model('disbaglanti', 'BrokenLink')
    AnalysisResult = apps.get_model('disbaglanti', 'AnalysisResult')
    
    # Eğer hiç AnalysisResult yoksa, bir tane oluştur
    default_analysis_result, created = AnalysisResult.objects.get_or_create(
        project_id=79  # Varsayılan bir proje ID'si kullanın
    )
    
    # NULL analysis_result'a sahip tüm BrokenLink'leri güncelle
    BrokenLink.objects.filter(analysis_result__isnull=True).update(
        analysis_result=default_analysis_result
    )
class Migration(migrations.Migration):
    dependencies = [
        ('disbaglanti', '0006_brokenlinkanalysisstatus_start_time'),  # Önceki migrasyonun adını buraya yazın
    ]
    operations = [
        migrations.RunPython(forward_func),
        migrations.AlterField(
            model_name='brokenlink',
            name='analysis_result',
            field=models.ForeignKey(on_delete=models.CASCADE, related_name='broken_links', to='disbaglanti.analysisresult'),
        ),
    ]