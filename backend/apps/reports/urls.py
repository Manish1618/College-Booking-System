from django.urls import path

from .views import DailyExportView, SummaryView

urlpatterns = [
    path("reports/summary", SummaryView.as_view()),
    path("reports/daily.csv", DailyExportView.as_view()),
]
