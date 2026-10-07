"""Views for the Manpower Capacity Planning and Monte Carlo Forecasting System."""
import logging

from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db.models import Count, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils import timezone
from django.views import View
from django.views.generic import CreateView, ListView, TemplateView, UpdateView

from . import permissions as perms
from .forms import (DEFAULT_SCENARIOS, ApprovalForm, BulkUploadForm, ExecutiveFilterForm, ForecastFilterForm,
                    FunctionMasterForm, ManpowerForecastForm, ProcessMasterForm, ScenarioBaseForm, ScenarioFormSet)
from .models import ApprovalStatus, ForecastAuditLog, FunctionMaster, ManpowerForecast, ProcessMaster
from .permissions import ROLE_ADMIN, ROLE_ANALYST, ROLE_APPROVER, RoleRequiredMixin
from .services import excel_service
from .services.dashboard_service import build_dashboard
from .services.executive_service import build_executive, exec_config
from .services.forecast_service import build_input, log_action, save_forecast, serialize_forecast
from .services.scenario_service import compare_scenarios

logger = logging.getLogger(__name__)
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
UPLOAD_ERRORS_SESSION_KEY = "bulk_upload_errors"


def xlsx_response(content, filename):
    response = HttpResponse(content, content_type=XLSX)
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    return response


def forecast_base_qs():
    return ManpowerForecast.objects.select_related(
        "function", "process", "created_by", "approved_by").prefetch_related("simulation_summaries")


def get_visible_forecast(user, pk):
    forecast = get_object_or_404(forecast_base_qs(), pk=pk)
    if not perms.can_view_forecast(user, forecast):
        raise PermissionDenied("You do not have permission to view this forecast.")
    return forecast


def projection_chart_data(forecast):
    points = forecast.projection_points
    if not points:
        return None
    return {
        "labels": [p["label"] for p in points],
        "required": [p["required_fte"] for p in points],
        "operational": [p["operational_fte"] for p in points],
        "p90": [p["p90_fte"] for p in points] if forecast.run_monte_carlo else None,
        "needed": [p["fte_needed"] for p in points],
        "current": [float(forecast.current_fte)] * len(points),
        "status": [p["status"] for p in points],
        "utilization": [p["utilization"] for p in points],
        "sufficiency": [p["sufficiency"] for p in points] if forecast.run_monte_carlo else None,
        "aht": [p.get("aht_minutes") for p in points],
        "has_aht_change": forecast.has_aht_change,
        "shortfall_index": forecast.projected_shortfall_month,
    }


def forecast_context(user, forecast):
    s = forecast.latest_summary
    chart = {}
    if s:
        chart.update({
            "histogram": s.histogram_data,
            "current_fte": float(forecast.current_fte),
            "percentiles": {
                "labels": ["Calculated", "P50", "P80", "P90", "P95", "P99"],
                "values": [float(forecast.required_fte)] + [
                    round(float(getattr(s, f"p{p}_required_fte")), 2) for p in (50, 80, 90, 95, 99)],
            },
        })
    projection = projection_chart_data(forecast)
    if projection:
        chart["projection"] = projection
    return {
        "f": forecast,
        "summary": s,
        "chart_data": chart,
        "can_edit": perms.can_edit_forecast(user, forecast),
        "can_delete": perms.can_delete_forecast(user, forecast),
        "can_approve": perms.can_approve_forecast(user, forecast),
        "is_maker": forecast.created_by_id == user.id,
        "approval_form": ApprovalForm(),
    }


# ============================================================ Dashboards
class DashboardView(RoleRequiredMixin, TemplateView):
    template_name = "forecasting/dashboard.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filter_form = ForecastFilterForm(self.request.GET or None)
        qs = perms.visible_forecasts(self.request.user, ManpowerForecast.objects.all())
        qs = filter_form.apply(qs)
        ctx.update(build_dashboard(qs))
        ctx["filter_form"] = filter_form
        ctx["pending_count"] = (ManpowerForecast.objects.filter(approval_status=ApprovalStatus.PENDING)
                                .exclude(created_by=self.request.user).count()
                                if perms.can_review(self.request.user) else 0)
        return ctx


def executive_data(request):
    """Shared by the executive page and its Excel export."""
    defaults = exec_config()
    form = ExecutiveFilterForm(request.GET or None, initial={"horizon": defaults["horizon"],
                                                              "cost_per_fte": defaults["cost_per_fte"]})
    function, horizon, cost, approved_only = form.values(defaults)
    qs = perms.visible_forecasts(request.user, ManpowerForecast.objects.all())
    if function:
        qs = qs.filter(function=function)
    if approved_only:
        qs = qs.filter(approval_status=ApprovalStatus.APPROVED)
    data = build_executive(qs, timezone.localdate(), cost_per_fte=cost, horizon=horizon)
    parts = [f"Function: {function}" if function else "All functions",
             "Approved forecasts only" if approved_only else "All visible forecasts"]
    return form, data, " | ".join(parts)


class ExecutiveDashboardView(RoleRequiredMixin, View):
    """CEO-level summary: health score, hiring need and budget, risks, redeployment and outlook."""
    template_name = "forecasting/executive.html"

    def get(self, request):
        form, data, filters_text = executive_data(request)
        return render(request, self.template_name, {
            "form": form, "filters_text": filters_text, "export_query": request.GET.urlencode(),
            "today": timezone.localdate(), **data,
        })


class ExecutiveExportView(RoleRequiredMixin, View):
    def get(self, request):
        _, data, filters_text = executive_data(request)
        stamp = timezone.localtime().strftime("%Y%m%d_%H%M")
        return xlsx_response(excel_service.export_executive(data, filters_text),
                             f"executive_workforce_summary_{stamp}.xlsx")


# ============================================================ Forecast CRUD
class ForecastCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = (ROLE_ADMIN, ROLE_ANALYST)
    model = ManpowerForecast
    form_class = ManpowerForecastForm
    template_name = "forecasting/forecast_form.html"

    def get_initial(self):
        initial = super().get_initial()
        process_id = self.request.GET.get("process")
        if process_id and process_id.isdigit():
            process = ProcessMaster.objects.filter(pk=process_id, is_active=True).first()
            if process:
                initial.update(function=process.function_id, process=process.pk,
                               frequency=process.default_frequency)
        return initial

    def form_valid(self, form):
        forecast = form.save(commit=False)
        try:
            save_forecast(forecast, self.request.user, ForecastAuditLog.Action.CREATE)
        except Exception as exc:
            logger.exception("Forecast calculation failed")
            form.add_error(None, f"Calculation failed: {exc}")
            return self.form_invalid(form)
        self.object = forecast
        method = "calculated and simulated" if forecast.run_monte_carlo else "calculated (deterministic only)"
        if forecast.has_projection:
            method += f" with a {forecast.forecast_horizon_months}-month projection ({forecast.growth_drivers_text})"
        messages.success(self.request, f"Forecast #{forecast.pk} {method} and submitted for approval.")
        return redirect("forecasting:forecast_result", pk=forecast.pk)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = "Add Forecast"
        return ctx


class ForecastUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = (ROLE_ADMIN, ROLE_ANALYST)
    model = ManpowerForecast
    form_class = ManpowerForecastForm
    template_name = "forecasting/forecast_form.html"

    def get_object(self, queryset=None):
        obj = super().get_object(queryset)
        if not perms.can_edit_forecast(self.request.user, obj):
            raise PermissionDenied("You can only edit forecasts you created.")
        return obj

    def form_valid(self, form):
        forecast = form.save(commit=False)
        try:
            save_forecast(forecast, self.request.user, ForecastAuditLog.Action.UPDATE)
        except Exception as exc:
            logger.exception("Forecast recalculation failed")
            form.add_error(None, f"Calculation failed: {exc}")
            return self.form_invalid(form)
        messages.success(self.request, f"Forecast #{forecast.pk} updated, recalculated and resubmitted for approval.")
        return redirect("forecasting:forecast_result", pk=forecast.pk)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["page_title"] = f"Edit Forecast #{self.object.pk}"
        return ctx


class ForecastResultView(RoleRequiredMixin, View):
    template_name = "forecasting/forecast_result.html"

    def get(self, request, pk):
        forecast = get_visible_forecast(request.user, pk)
        return render(request, self.template_name, forecast_context(request.user, forecast))


class ForecastDetailView(RoleRequiredMixin, View):
    template_name = "forecasting/forecast_detail.html"

    def get(self, request, pk):
        forecast = get_visible_forecast(request.user, pk)
        ctx = forecast_context(request.user, forecast)
        ctx["audit_logs"] = forecast.audit_logs.select_related("performed_by")[:50]
        ctx["simulation_history"] = forecast.simulation_summaries.all()[:10]
        return render(request, self.template_name, ctx)


class ForecastListView(RoleRequiredMixin, ListView):
    template_name = "forecasting/forecast_list.html"
    context_object_name = "forecasts"
    paginate_by = 15

    def get_queryset(self):
        self.filter_form = ForecastFilterForm(self.request.GET or None)
        qs = perms.visible_forecasts(self.request.user, forecast_base_qs())
        return self.filter_form.apply(qs)

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["filter_form"] = self.filter_form
        user = self.request.user
        ctx["rows"] = [{"f": f, "can_edit": perms.can_edit_forecast(user, f),
                        "can_delete": perms.can_delete_forecast(user, f),
                        "can_approve": perms.can_approve_forecast(user, f)} for f in ctx["forecasts"]]
        return ctx


class ForecastDeleteView(RoleRequiredMixin, View):
    allowed_roles = (ROLE_ADMIN, ROLE_ANALYST)

    def post(self, request, pk):
        forecast = get_object_or_404(ManpowerForecast, pk=pk)
        if not perms.can_delete_forecast(request.user, forecast):
            raise PermissionDenied("You cannot delete this forecast.")
        log_action(None, ForecastAuditLog.Action.DELETE, request.user, old_data=serialize_forecast(forecast))
        forecast.delete()
        messages.success(request, f"Forecast #{pk} deleted.")
        return redirect("forecasting:forecast_list")


class ForecastRerunView(RoleRequiredMixin, View):
    """
    Recalculate a forecast (including the projection). Optional query parameter:
      ?monte_carlo=on  -> switch Monte Carlo on and run it
      ?monte_carlo=off -> switch Monte Carlo off (deterministic only)
    """
    allowed_roles = (ROLE_ADMIN, ROLE_ANALYST)

    def post(self, request, pk):
        forecast = get_object_or_404(ManpowerForecast, pk=pk)
        if not perms.can_edit_forecast(request.user, forecast):
            raise PermissionDenied("You can only recalculate your own forecasts.")
        switch = request.GET.get("monte_carlo")
        if switch in ("on", "off"):
            forecast.run_monte_carlo = switch == "on"
        save_forecast(forecast, request.user,
                      ForecastAuditLog.Action.SIMULATE if forecast.run_monte_carlo else ForecastAuditLog.Action.UPDATE)
        if forecast.run_monte_carlo:
            messages.success(request, "Monte Carlo simulation completed. Forecast resubmitted for approval.")
        else:
            messages.success(request, "Forecast recalculated (deterministic only). Resubmitted for approval.")
        return redirect("forecasting:forecast_result", pk=pk)


class ForecastApprovalView(RoleRequiredMixin, View):
    """Maker-checker approval. The creator can never approve their own forecast."""
    allowed_roles = (ROLE_ADMIN, ROLE_APPROVER)

    def post(self, request, pk):
        forecast = get_object_or_404(ManpowerForecast, pk=pk)
        if forecast.created_by_id == request.user.id:
            messages.error(request, "Maker-checker rule: you cannot approve or reject your own forecast.")
            return redirect("forecasting:forecast_detail", pk=pk)
        if not perms.can_approve_forecast(request.user, forecast):
            messages.error(request, "This forecast is not pending approval.")
            return redirect("forecasting:forecast_detail", pk=pk)
        form = ApprovalForm(request.POST)
        if not form.is_valid():
            for errs in form.errors.values():
                for e in errs:
                    messages.error(request, e)
            return redirect("forecasting:forecast_detail", pk=pk)
        old = serialize_forecast(forecast)
        approve = form.cleaned_data["decision"] == "APPROVE"
        forecast.approval_status = ApprovalStatus.APPROVED if approve else ApprovalStatus.REJECTED
        forecast.approved_by = request.user
        forecast.approved_at = timezone.now()
        forecast.approval_comments = form.cleaned_data["comments"]
        forecast.save(update_fields=["approval_status", "approved_by", "approved_at", "approval_comments",
                                     "updated_at"])
        log_action(forecast, ForecastAuditLog.Action.APPROVE if approve else ForecastAuditLog.Action.REJECT,
                   request.user, old, serialize_forecast(forecast))
        messages.success(request, f"Forecast #{pk} {'approved' if approve else 'rejected'}.")
        return redirect("forecasting:forecast_detail", pk=pk)


class ProcessOptionsView(RoleRequiredMixin, View):
    """AJAX: active processes for a function (dependent dropdown)."""

    def get(self, request):
        function_id = request.GET.get("function", "")
        if not function_id.isdigit():
            return JsonResponse({"results": []})
        processes = ProcessMaster.objects.filter(function_id=function_id, is_active=True).order_by("process_name")
        return JsonResponse({"results": [
            {"id": p.pk, "name": p.process_name, "default_frequency": p.default_frequency} for p in processes]})


# ============================================================ Masters
class FunctionListView(RoleRequiredMixin, ListView):
    allowed_roles = (ROLE_ADMIN,)
    template_name = "forecasting/function_list.html"
    context_object_name = "functions"
    paginate_by = 15

    def get_queryset(self):
        qs = FunctionMaster.objects.annotate(process_count=Count("processes", distinct=True)).select_related(
            "created_by")
        search = self.request.GET.get("q", "").strip()
        if search:
            qs = qs.filter(Q(function_name__icontains=search) | Q(function_owner__icontains=search))
        return qs.order_by("function_name")


class FunctionCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = (ROLE_ADMIN,)
    model = FunctionMaster
    form_class = FunctionMasterForm
    template_name = "forecasting/master_form.html"
    success_url = reverse_lazy("forecasting:function_list")
    extra_context = {"page_title": "Add Function", "back_url": reverse_lazy("forecasting:function_list")}

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, f"Function '{form.instance.function_name}' created.")
        return super().form_valid(form)


class FunctionUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = (ROLE_ADMIN,)
    model = FunctionMaster
    form_class = FunctionMasterForm
    template_name = "forecasting/master_form.html"
    success_url = reverse_lazy("forecasting:function_list")
    extra_context = {"page_title": "Edit Function", "back_url": reverse_lazy("forecasting:function_list")}

    def form_valid(self, form):
        messages.success(self.request, f"Function '{form.instance.function_name}' updated.")
        return super().form_valid(form)


class ProcessListView(RoleRequiredMixin, ListView):
    allowed_roles = (ROLE_ADMIN,)
    template_name = "forecasting/process_list.html"
    context_object_name = "processes"
    paginate_by = 15

    def get_queryset(self):
        qs = ProcessMaster.objects.select_related("function", "created_by").annotate(
            forecast_count=Count("forecasts"))
        search = self.request.GET.get("q", "").strip()
        function_id = self.request.GET.get("function", "")
        if search:
            qs = qs.filter(Q(process_name__icontains=search) | Q(process_owner__icontains=search))
        if function_id.isdigit():
            qs = qs.filter(function_id=function_id)
        return qs.order_by("function__function_name", "process_name")

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        ctx["functions"] = FunctionMaster.objects.all()
        ctx["selected_function"] = self.request.GET.get("function", "")
        return ctx


class ProcessCreateView(RoleRequiredMixin, CreateView):
    allowed_roles = (ROLE_ADMIN,)
    model = ProcessMaster
    form_class = ProcessMasterForm
    template_name = "forecasting/master_form.html"
    success_url = reverse_lazy("forecasting:process_list")
    extra_context = {"page_title": "Add Process", "back_url": reverse_lazy("forecasting:process_list")}

    def form_valid(self, form):
        form.instance.created_by = self.request.user
        messages.success(self.request, f"Process '{form.instance.process_name}' created.")
        return super().form_valid(form)


class ProcessUpdateView(RoleRequiredMixin, UpdateView):
    allowed_roles = (ROLE_ADMIN,)
    model = ProcessMaster
    form_class = ProcessMasterForm
    template_name = "forecasting/master_form.html"
    success_url = reverse_lazy("forecasting:process_list")
    extra_context = {"page_title": "Edit Process", "back_url": reverse_lazy("forecasting:process_list")}

    def form_valid(self, form):
        messages.success(self.request, f"Process '{form.instance.process_name}' updated.")
        return super().form_valid(form)


# ============================================================ Scenario comparison
class ScenarioComparisonView(RoleRequiredMixin, View):
    allowed_roles = (ROLE_ADMIN, ROLE_ANALYST, ROLE_APPROVER)
    template_name = "forecasting/scenario.html"

    def _base_queryset(self):
        return perms.visible_forecasts(self.request.user, ManpowerForecast.objects.all())

    def get(self, request):
        base_id = request.GET.get("base", "")
        initial_base = {"simulation_seed": 42}
        initial_scenarios = []
        if base_id.isdigit():
            base = self._base_queryset().filter(pk=base_id).first()
            if base:
                initial_base["base_forecast"] = base.pk
                initial_base["run_monte_carlo"] = base.run_monte_carlo
                for sc in DEFAULT_SCENARIOS:
                    item = dict(sc)
                    if "current_fte" in item:
                        item["current_fte"] = (base.recommended_operational_fte
                                               if base.current_fte < base.recommended_operational_fte
                                               else base.current_fte + 1)
                    initial_scenarios.append(item)
        else:
            initial_scenarios = [dict(sc) for sc in DEFAULT_SCENARIOS if "current_fte" not in sc]
        return render(request, self.template_name, {
            "base_form": ScenarioBaseForm(initial=initial_base, queryset=self._base_queryset()),
            "formset": ScenarioFormSet(initial=initial_scenarios, prefix="sc"),
        })

    def post(self, request):
        base_form = ScenarioBaseForm(request.POST, queryset=self._base_queryset())
        formset = ScenarioFormSet(request.POST, prefix="sc")
        rows = None
        if base_form.is_valid() and formset.is_valid():
            base = base_form.cleaned_data["base_forecast"]
            inp = build_input(base)
            inp.run_monte_carlo = base_form.cleaned_data.get("run_monte_carlo", False)
            inp.simulation_seed = base_form.cleaned_data.get("simulation_seed")
            scenarios = []
            for i, form in enumerate(formset.forms, start=1):
                if form.cleaned_data and form.has_adjustment():
                    data = dict(form.cleaned_data)
                    data["name"] = data.get("name") or f"Scenario {i}"
                    scenarios.append(data)
            if not scenarios:
                messages.warning(request, "Add at least one scenario adjustment to compare against the base case.")
            rows = compare_scenarios(inp, scenarios)
        chart = None
        if rows:
            mc = rows[0]["monte_carlo"]
            chart = {
                "labels": [r["name"] for r in rows],
                "required": [float(r["required_fte"]) for r in rows],
                "operational": [float(r["operational_fte"]) for r in rows],
                "p90": [float(r["p90_fte"]) for r in rows] if mc else None,
                "current": [float(r["current_fte"]) for r in rows],
                "sufficiency": [float(r["sufficiency_probability"]) for r in rows] if mc else None,
                "utilization": [float(r["utilization"]) if r["utilization"] is not None else None for r in rows],
                "horizon_required": [float(r["horizon_required_fte"]) if r["has_projection"] else None
                                     for r in rows],
                "has_monte_carlo": mc,
                "has_projection": any(r["has_projection"] for r in rows),
            }
        return render(request, self.template_name, {
            "base_form": base_form, "formset": formset, "rows": rows, "chart_data": chart,
            "scenario_mc": bool(rows and rows[0]["monte_carlo"]),
            "scenario_projection": bool(rows and any(r["has_projection"] for r in rows)),
        })


# ============================================================ Excel
class BulkUploadView(RoleRequiredMixin, View):
    allowed_roles = (ROLE_ADMIN, ROLE_ANALYST)
    template_name = "forecasting/bulk_upload.html"

    def get(self, request):
        return render(request, self.template_name, {"form": BulkUploadForm()})

    def post(self, request):
        form = BulkUploadForm(request.POST, request.FILES)
        ctx = {"form": form}
        if form.is_valid():
            try:
                result = excel_service.process_upload(form.cleaned_data["file"], request.user)
            except excel_service.UploadFormatError as exc:
                messages.error(request, str(exc))
                return render(request, self.template_name, ctx)
            request.session[UPLOAD_ERRORS_SESSION_KEY] = result.errors
            ctx["result"] = result
            ctx["created"] = forecast_base_qs().filter(pk__in=result.created_ids)
            if result.success_count:
                messages.success(request, f"{result.success_count} of {result.total_rows} rows processed successfully.")
            if result.error_count:
                messages.warning(request, f"{result.error_count} rows failed validation. Download the error report.")
        return render(request, self.template_name, ctx)


class UploadTemplateDownloadView(RoleRequiredMixin, View):
    allowed_roles = (ROLE_ADMIN, ROLE_ANALYST)

    def get(self, request):
        return xlsx_response(excel_service.generate_upload_template(), "forecast_upload_template.xlsx")


class UploadErrorReportView(RoleRequiredMixin, View):
    allowed_roles = (ROLE_ADMIN, ROLE_ANALYST)

    def get(self, request):
        errors = request.session.get(UPLOAD_ERRORS_SESSION_KEY) or []
        if not errors:
            messages.info(request, "No upload errors to download.")
            return redirect("forecasting:bulk_upload")
        return xlsx_response(excel_service.build_error_report(errors), "forecast_upload_errors.xlsx")


class ReportView(RoleRequiredMixin, TemplateView):
    template_name = "forecasting/reports.html"

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        filter_form = ForecastFilterForm(self.request.GET or None)
        qs = filter_form.apply(perms.visible_forecasts(self.request.user, forecast_base_qs()))
        ctx["filter_form"] = filter_form
        ctx["record_count"] = qs.count()
        ctx["preview"] = qs[:10]
        ctx["query_string"] = self.request.GET.urlencode()
        return ctx


class ReportExportView(RoleRequiredMixin, View):
    def get(self, request):
        filter_form = ForecastFilterForm(request.GET or None)
        qs = filter_form.apply(perms.visible_forecasts(request.user, ManpowerForecast.objects.all()))
        stamp = timezone.localtime().strftime("%Y%m%d_%H%M")
        return xlsx_response(excel_service.export_forecasts(qs), f"manpower_forecast_report_{stamp}.xlsx")


class ForecastExportView(RoleRequiredMixin, View):
    def get(self, request, pk):
        forecast = get_visible_forecast(request.user, pk)
        return xlsx_response(excel_service.export_forecast_detail(forecast), f"forecast_{pk}.xlsx")


def permission_denied_view(request, exception=None):
    return render(request, "403.html", {"message": str(exception) if exception else ""}, status=403)
