from django.contrib import admin

from .models import ForecastAuditLog, ForecastSimulationSummary, FunctionMaster, ManpowerForecast, ProcessMaster

admin.site.site_header = "Manpower Forecasting Administration"
admin.site.site_title = "Manpower Forecasting"
admin.site.index_title = "Administration"


class ProcessInline(admin.TabularInline):
    model = ProcessMaster
    extra = 0
    fields = ("process_name", "process_owner", "default_frequency", "is_active")


@admin.register(FunctionMaster)
class FunctionMasterAdmin(admin.ModelAdmin):
    list_display = ("function_name", "function_owner", "is_active", "created_by", "created_at")
    list_filter = ("is_active",)
    search_fields = ("function_name", "function_owner")
    readonly_fields = ("created_by", "created_at", "updated_at")
    inlines = [ProcessInline]

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(ProcessMaster)
class ProcessMasterAdmin(admin.ModelAdmin):
    list_display = ("process_name", "function", "process_owner", "default_frequency", "is_active", "created_at")
    list_filter = ("function", "default_frequency", "is_active")
    search_fields = ("process_name", "process_owner", "function__function_name")
    readonly_fields = ("created_by", "created_at", "updated_at")

    def save_model(self, request, obj, form, change):
        if not obj.created_by_id:
            obj.created_by = request.user
        super().save_model(request, obj, form, change)


class SimulationInline(admin.TabularInline):
    model = ForecastSimulationSummary
    extra = 0
    can_delete = False
    fields = ("created_at", "simulation_count", "p50_required_fte", "p90_required_fte",
              "risk_adjusted_recommended_fte", "sufficiency_probability")
    readonly_fields = fields


@admin.register(ManpowerForecast)
class ManpowerForecastAdmin(admin.ModelAdmin):
    list_display = ("id", "function", "process", "frequency", "current_fte", "required_fte",
                    "utilization_percentage", "run_monte_carlo", "growth_rate_percentage", "growth_period",
                    "projected_shortfall_month", "status", "approval_status", "created_by", "created_at")
    list_filter = ("status", "approval_status", "run_monte_carlo", "growth_period", "frequency", "function")
    search_fields = ("process__process_name", "function__function_name", "remarks")
    date_hierarchy = "created_at"
    inlines = [SimulationInline]
    readonly_fields = ("daily_volume", "processing_time_minutes", "productive_minutes_per_fte", "workload_minutes",
                       "workload_hours", "available_capacity_minutes", "required_fte",
                       "recommended_operational_fte", "fte_gap", "operational_fte_gap", "utilization_percentage",
                       "unused_capacity_percentage", "status", "high_utilization_risk", "recommendation",
                       "status_explanation", "projection_data", "projected_shortfall_month",
                       "projected_horizon_required_fte", "projected_horizon_fte_needed", "projected_horizon_status",
                       "projection_summary", "approval_status", "approved_by", "approved_at", "approval_comments",
                       "created_by", "created_at", "updated_at")

    def has_add_permission(self, request):
        # Forecasts must be created through the application so calculations run.
        return False


@admin.register(ForecastSimulationSummary)
class ForecastSimulationSummaryAdmin(admin.ModelAdmin):
    list_display = ("forecast", "simulation_count", "p50_required_fte", "p90_required_fte",
                    "risk_adjusted_recommended_fte", "sufficiency_probability", "created_at")
    readonly_fields = [f.name for f in ForecastSimulationSummary._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(ForecastAuditLog)
class ForecastAuditLogAdmin(admin.ModelAdmin):
    list_display = ("performed_at", "action", "forecast", "performed_by")
    list_filter = ("action",)
    search_fields = ("performed_by__username",)
    readonly_fields = ("forecast", "action", "old_data", "new_data", "performed_by", "performed_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
