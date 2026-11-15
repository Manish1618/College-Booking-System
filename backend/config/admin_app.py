from django.contrib.admin.apps import AdminConfig


class GuesthouseAdminConfig(AdminConfig):
    default_site = "apps.accounts.adminsite.GuesthouseAdminSite"
