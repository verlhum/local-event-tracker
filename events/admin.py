from __future__ import annotations

from django.contrib import admin, messages
from django.contrib.admin.helpers import ACTION_CHECKBOX_NAME
from django.template.response import TemplateResponse
from django.utils import timezone
from django.utils.dateparse import parse_date, parse_datetime, parse_time

from django.db import models

from urllib.parse import urlencode

from django.shortcuts import redirect
from django.urls import reverse

from datetime import timedelta

from .forms import ScrapedEventBatchEditForm
from .models import (
    ManualSingleEvent,
    ManualRecurringEvent,
    RecurringException,
    EventLog,
    ScrapeSource,
    ScrapeRun,
    ScrapedEvent,
    ScrapedEventOverride,
)

class SaveAndAddSimilarAdminMixin:
    """
    Adds a 'Save and add similar' workflow to Django admin screens.

    Admin classes using this mixin should define:

        add_similar_fields = (
            "field_1",
            "field_2",
            ...
        )

    These fields will be copied from the saved object into the next add form.
    """

    change_form_template = "admin/events/change_form_with_add_similar.html"

    add_similar_fields = ()

    def response_add(self, request, obj, post_url_continue=None):
        if "_save_add_similar" in request.POST:
            return self.redirect_to_add_similar(request, obj)

        return super().response_add(request, obj, post_url_continue)

    def response_change(self, request, obj):
        if "_save_add_similar" in request.POST:
            return self.redirect_to_add_similar(request, obj)

        return super().response_change(request, obj)

    def redirect_to_add_similar(self, request, obj):
        opts = self.model._meta

        add_url = reverse(
            f"admin:{opts.app_label}_{opts.model_name}_add",
            current_app=self.admin_site.name,
        )

        params = {}

        for field_name in self.add_similar_fields:
            value = getattr(obj, field_name, None)

            if value is None:
                continue

            # For FK fields, use the object pk.
            if hasattr(value, "pk"):
                value = value.pk

            # For dates/datetimes/times, pass through the URL as strings.
            # get_changeform_initial_data() will parse them back.
            if hasattr(value, "isoformat"):
                value = value.isoformat()

            params[field_name] = value

        query_string = urlencode(params)

        self.message_user(
            request,
            "Saved. You can now add a similar event.",
            level=messages.SUCCESS,
        )

        return redirect(f"{add_url}?{query_string}")

    def get_changeform_initial_data(self, request):
        initial = super().get_changeform_initial_data(request)

        for field_name in self.add_similar_fields:
            if field_name not in initial:
                continue

            try:
                model_field = self.model._meta.get_field(field_name)
            except Exception:
                continue

            value = initial[field_name]

            if value in (None, ""):
                continue

            if isinstance(model_field, models.DateTimeField):
                parsed_value = parse_datetime(value)

                if parsed_value is not None:
                    initial[field_name] = parsed_value

            elif isinstance(model_field, models.DateField):
                parsed_value = parse_date(value)

                if parsed_value is not None:
                    initial[field_name] = parsed_value

            elif isinstance(model_field, models.TimeField):
                parsed_value = parse_time(value)

                if parsed_value is not None:
                    initial[field_name] = parsed_value

        return initial

@admin.register(ManualSingleEvent)
class ManualSingleEventAdmin(SaveAndAddSimilarAdminMixin, admin.ModelAdmin):
    add_similar_fields = (
        "title",
        "start_datetime",
        "end_datetime",
        "venue",
        "location",
        "city",
        "state",
        "categories",
        "summary",
        "event_url",
        "source_page",
        "notes",
        "status",
    )
    list_display = (
        "title",
        "start_datetime",
        "venue",
        "city",
        "status",
        "updated_at",
    )
    list_filter = ("status", "city", "state")
    search_fields = ("title", "venue", "location", "notes")
    date_hierarchy = "start_datetime"
    ordering = ("start_datetime",)


class RecurringExceptionInline(admin.TabularInline):
    model = RecurringException
    extra = 0


@admin.register(ManualRecurringEvent)
class ManualRecurringEventAdmin(SaveAndAddSimilarAdminMixin, admin.ModelAdmin):
    add_similar_fields = (
        "title",
        "recurrence_type",
        "weekday",
        "week_of_month",
        "start_time",
        "venue",
        "location",
        "city",
        "state",
        "status",
        "start_date",
        "end_date",
    )
    list_display = (
        "title",
        "recurrence_type",
        "weekday",
        "week_of_month",
        "start_time",
        "venue",
        "status",
        "start_date",
        "end_date",
    )
    list_filter = ("status", "recurrence_type", "city", "state")
    search_fields = ("title", "venue", "location", "notes")
    inlines = [RecurringExceptionInline]


@admin.register(RecurringException)
class RecurringExceptionAdmin(admin.ModelAdmin):
    list_display = (
        "recurring_event",
        "occurrence_date",
        "exception_type",
    )
    list_filter = ("exception_type",)
    search_fields = ("recurring_event__title",)


@admin.register(EventLog)
class EventLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "action_type", "entity_type", "entity_id")
    list_filter = ("action_type", "entity_type")
    search_fields = ("note",)
    ordering = ("-timestamp",)

@admin.register(ScrapeRun)
class ScrapeRunAdmin(admin.ModelAdmin):
    list_display = (
        "source_name",
        "status",
        "started_at",
        "completed_at",
        "events_found",
        "relevant_count",
        "irrelevant_count",
        "error_count",
    )
    list_filter = ("status", "source_name")
    search_fields = ("source_name", "notes")
    ordering = ("-started_at",)


class ScrapedEventOverrideInline(admin.StackedInline):
    model = ScrapedEventOverride
    extra = 0


@admin.register(ScrapedEvent)
class ScrapedEventAdmin(admin.ModelAdmin):
    # ScrapedEventAdmin intentionally does not use SaveAndAddSimilarAdminMixin
    # because scraped events should normally be created through the import workflow.
    change_list_template = "admin/events/scrapedevent/change_list.html"
    list_display = (
        "title",
        "start_datetime",
        "source_name",
        "city",
        "relevance_status",
        "review_status",
        "last_seen_at",
    )
    list_filter = (
        "source_name",
        "relevance_status",
        "review_status",
        "city",
        "state",
    )
    search_fields = (
        "title",
        "venue",
        "location",
        "summary",
        "external_event_id",
        "source_name",
    )
    ordering = ("start_datetime",)
    inlines = [ScrapedEventOverrideInline]

    actions = [
        "mark_relevant_reviewed",
        "mark_irrelevant_reviewed",
        "mark_canceled_reviewed",
        "mark_hidden_reviewed",
        "mark_duplicate_reviewed",
        "batch_edit_events",
    ]
    
    custom_date_filter_params = ("event_start_date", "event_end_date")
    
    def changelist_view(self, request, extra_context=None):
        start_date, end_date = self.get_date_range_from_request(request)
    
        # Store parsed dates on the request so get_queryset can use them.
        request._event_start_date = start_date
        request._event_end_date = end_date
    
        # Remove custom params before Django admin's ChangeList processes GET.
        # Otherwise admin may treat event_start_date/event_end_date as invalid model lookups.
        cleaned_get = request.GET.copy()
        for param in self.custom_date_filter_params:
            cleaned_get.pop(param, None)
    
        request.GET = cleaned_get
        request.META["QUERY_STRING"] = cleaned_get.urlencode()
    
        extra_context = extra_context or {}
        extra_context["event_start_date"] = start_date.isoformat()
        extra_context["event_end_date"] = end_date.isoformat()
    
        return super().changelist_view(request, extra_context=extra_context)
    
    def get_queryset(self, request):
        qs = super().get_queryset(request)
    
        start_date = getattr(request, "_event_start_date", None)
        end_date = getattr(request, "_event_end_date", None)
    
        if start_date is None or end_date is None:
            start_date, end_date = self.get_date_range_from_request(request)
    
        if start_date:
            qs = qs.filter(start_datetime__date__gte=start_date)
    
        if end_date:
            qs = qs.filter(start_datetime__date__lte=end_date)
    
        return qs
    
    def get_date_range_from_request(self, request):
        start_param = request.GET.get("event_start_date")
        end_param = request.GET.get("event_end_date")
    
        start_date = parse_date(start_param) if start_param else None
        end_date = parse_date(end_param) if end_param else None
    
        today = timezone.localdate()
        monday = today - timedelta(days=today.weekday())
        sunday = monday + timedelta(days=6)
    
        return start_date or monday, end_date or sunday

    @admin.action(description="Mark selected events as relevant + reviewed")
    def mark_relevant_reviewed(self, request, queryset):
        updated = queryset.update(
            relevance_status="relevant",
            review_status="approved",
            review_notes="Marked relevant via admin action.",
            updated_at=timezone.now(),
        )
        self.message_user(
            request,
            f"{updated} scraped event(s) marked relevant and reviewed.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Mark selected events as irrelevant + reviewed")
    def mark_irrelevant_reviewed(self, request, queryset):
        updated = queryset.update(
            relevance_status="irrelevant",
            review_status="approved",
            review_notes="Marked irrelevant via admin action.",
            updated_at=timezone.now(),
        )
        self.message_user(
            request,
            f"{updated} scraped event(s) marked irrelevant and reviewed.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Mark selected events as canceled + reviewed")
    def mark_canceled_reviewed(self, request, queryset):
        updated = queryset.update(
            review_status="canceled",
            review_notes="Marked canceled via admin action.",
            updated_at=timezone.now(),
        )
        self.message_user(
            request,
            f"{updated} scraped event(s) marked canceled.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Mark selected events as hidden + reviewed")
    def mark_hidden_reviewed(self, request, queryset):
        updated = queryset.update(
            review_status="hidden",
            review_notes="Marked hidden via admin action.",
            updated_at=timezone.now(),
        )
        self.message_user(
            request,
            f"{updated} scraped event(s) hidden.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Mark selected events as duplicate + reviewed")
    def mark_duplicate_reviewed(self, request, queryset):
        updated = queryset.update(
            review_status="duplicate",
            review_notes="Marked duplicate via admin action.",
            updated_at=timezone.now(),
        )
        self.message_user(
            request,
            f"{updated} scraped event(s) marked duplicate.",
            level=messages.SUCCESS,
        )

    @admin.action(description="Batch edit selected scraped events")
    def batch_edit_events(self, request, queryset):
        if "apply" in request.POST:
            form = ScrapedEventBatchEditForm(request.POST)
            if form.is_valid():
                updates = {}
                cleaned = form.cleaned_data

                if cleaned["city"]:
                    updates["city"] = cleaned["city"]
                if cleaned["state"]:
                    updates["state"] = cleaned["state"]
                if cleaned["venue"]:
                    updates["venue"] = cleaned["venue"]
                if cleaned["location"]:
                    updates["location"] = cleaned["location"]
                if cleaned["start_datetime"]:
                    updates["start_datetime"] = cleaned["start_datetime"]
                if cleaned["end_datetime"]:
                    updates["end_datetime"] = cleaned["end_datetime"]

                if cleaned["mark_reviewed"]:
                    updates["review_status"] = "corrected"
                    updates["review_notes"] = "Batch edited via admin action."

                if not updates:
                    self.message_user(
                        request,
                        "No changes were provided.",
                        level=messages.WARNING,
                    )
                    return None

                updates["updated_at"] = timezone.now()
                count = queryset.update(**updates)

                self.message_user(
                    request,
                    f"{count} scraped event(s) updated.",
                    level=messages.SUCCESS,
                )
                return None
        else:
            form = ScrapedEventBatchEditForm(
                initial={
                    "_selected_action": request.POST.getlist(ACTION_CHECKBOX_NAME),
                }
            )

        context = {
            **self.admin_site.each_context(request),
            "opts": self.model._meta,
            "queryset": queryset,
            "form": form,
            "title": "Batch edit scraped events",
            "action_checkbox_name": ACTION_CHECKBOX_NAME,
        }

        return TemplateResponse(
            request,
            "admin/events/scrapedevent/batch_edit.html",
            context,
        )

@admin.register(ScrapedEventOverride)
class ScrapedEventOverrideAdmin(admin.ModelAdmin):
    list_display = (
        "scraped_event",
        "action",
        "updated_at",
    )
    list_filter = ("action",)
    search_fields = ("scraped_event__title", "reason")
    ordering = ("-updated_at",)

@admin.register(ScrapeSource)
class ScrapeSourceAdmin(admin.ModelAdmin):
    list_display = ("name", "extractor_key", "url", "is_enabled", "sort_order")
    list_filter = ("extractor_key", "is_enabled")
    search_fields = ("name", "url", "notes")
    ordering = ("sort_order", "name")