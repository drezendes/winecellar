from django.contrib import admin

from .models import ApiUsage, DistributorEmail, LabelScan, MenuAnalysis, TasteProfile


@admin.register(TasteProfile)
class TasteProfileAdmin(admin.ModelAdmin):
    list_display = ["user", "modified"]


@admin.register(DistributorEmail)
class DistributorEmailAdmin(admin.ModelAdmin):
    list_display = ["subject", "sender", "received_at", "status", "reviewed"]
    list_filter = ["status", "reviewed"]
    search_fields = ["subject", "sender", "raw_text"]
    date_hierarchy = "received_at"


@admin.register(ApiUsage)
class ApiUsageAdmin(admin.ModelAdmin):
    list_display = ["feature", "model", "input_tokens", "output_tokens", "created"]
    list_filter = ["feature", "model"]
    date_hierarchy = "created"


@admin.register(LabelScan)
class LabelScanAdmin(admin.ModelAdmin):
    list_display = ["created", "status", "created_by"]
    list_filter = ["status", "created_by"]


@admin.register(MenuAnalysis)
class MenuAnalysisAdmin(admin.ModelAdmin):
    list_display = ["created", "food", "notes", "status", "created_by"]
    list_filter = ["status", "created_by"]
