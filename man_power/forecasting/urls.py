from django.urls import path

from . import views

app_name = "forecasting"

urlpatterns = [
    path("", views.DashboardView.as_view(), name="dashboard"),
    path("forecasts/", views.ForecastListView.as_view(), name="forecast_list"),
    path("forecasts/add/", views.ForecastCreateView.as_view(), name="forecast_create"),
    path("forecasts/<int:pk>/", views.ForecastDetailView.as_view(), name="forecast_detail"),
    path("forecasts/<int:pk>/result/", views.ForecastResultView.as_view(), name="forecast_result"),
    path("forecasts/<int:pk>/edit/", views.ForecastUpdateView.as_view(), name="forecast_update"),
    path("forecasts/<int:pk>/delete/", views.ForecastDeleteView.as_view(), name="forecast_delete"),
    path("forecasts/<int:pk>/rerun/", views.ForecastRerunView.as_view(), name="forecast_rerun"),
    path("forecasts/<int:pk>/approve/", views.ForecastApprovalView.as_view(), name="forecast_approve"),
    path("forecasts/<int:pk>/export/", views.ForecastExportView.as_view(), name="forecast_export"),
    path("ajax/processes/", views.ProcessOptionsView.as_view(), name="process_options"),
    path("functions/", views.FunctionListView.as_view(), name="function_list"),
    path("functions/add/", views.FunctionCreateView.as_view(), name="function_create"),
    path("functions/<int:pk>/edit/", views.FunctionUpdateView.as_view(), name="function_update"),
    path("processes/", views.ProcessListView.as_view(), name="process_list"),
    path("processes/add/", views.ProcessCreateView.as_view(), name="process_create"),
    path("processes/<int:pk>/edit/", views.ProcessUpdateView.as_view(), name="process_update"),
    path("scenarios/", views.ScenarioComparisonView.as_view(), name="scenario"),
    path("upload/", views.BulkUploadView.as_view(), name="bulk_upload"),
    path("upload/template/", views.UploadTemplateDownloadView.as_view(), name="upload_template"),
    path("upload/errors/", views.UploadErrorReportView.as_view(), name="upload_errors"),
    path("reports/", views.ReportView.as_view(), name="reports"),
    path("reports/export/", views.ReportExportView.as_view(), name="report_export"),
]
