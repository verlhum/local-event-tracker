from django.db import models
from django.utils import timezone

class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class ManualSingleEvent(TimeStampedModel):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("canceled", "Canceled"),
        ("archived", "Archived"),
    ]

    title = models.CharField(max_length=255)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField(null=True, blank=True)
    venue = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    location = models.CharField(max_length=255, blank=True)
    categories = models.JSONField(default=list, blank=True)
    summary = models.TextField(blank=True)
    event_url = models.URLField(blank=True)
    source_page = models.URLField(blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    class Meta:
        ordering = ["start_datetime"]

    def __str__(self):
        return f"{self.title} ({self.start_datetime:%Y-%m-%d %H:%M})"


class ManualRecurringEvent(TimeStampedModel):
    STATUS_CHOICES = [
        ("active", "Active"),
        ("paused", "Paused"),
        ("ended", "Ended"),
        ("archived", "Archived"),
    ]

    RECURRENCE_CHOICES = [
        ("weekly", "Weekly"),
        ("monthly_nth_weekday", "Monthly nth weekday"),
    ]

    title = models.CharField(max_length=255)
    venue = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    location = models.CharField(max_length=255, blank=True)
    categories = models.JSONField(default=list, blank=True)
    summary_template = models.TextField(blank=True)
    event_url = models.URLField(blank=True)
    source_page = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    recurrence_type = models.CharField(max_length=50, choices=RECURRENCE_CHOICES)
    weekday = models.IntegerField(
        help_text="0=Monday, 6=Sunday", null=True, blank=True
    )
    week_of_month = models.IntegerField(
        null=True,
        blank=True,
        help_text="1,2,3,4 or -1 for last. Only used for monthly_nth_weekday.",
    )

    start_time = models.TimeField()
    end_time = models.TimeField(null=True, blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)

    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="active")

    class Meta:
        ordering = ["title"]

    def __str__(self):
        return self.title


class RecurringException(TimeStampedModel):
    EXCEPTION_CHOICES = [
        ("cancel_occurrence", "Cancel occurrence"),
        ("override_occurrence", "Override occurrence"),
    ]

    recurring_event = models.ForeignKey(
        ManualRecurringEvent,
        on_delete=models.CASCADE,
        related_name="exceptions",
    )
    occurrence_date = models.DateField()
    exception_type = models.CharField(max_length=30, choices=EXCEPTION_CHOICES)

    override_title = models.CharField(max_length=255, blank=True)
    override_start_time = models.TimeField(null=True, blank=True)
    override_end_time = models.TimeField(null=True, blank=True)
    override_venue = models.CharField(max_length=255, blank=True)
    override_city = models.CharField(max_length=100, blank=True)
    override_state = models.CharField(max_length=50, blank=True)
    override_location = models.CharField(max_length=255, blank=True)
    override_categories = models.JSONField(default=list, blank=True)
    override_summary = models.TextField(blank=True)
    override_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["occurrence_date"]
        constraints = [
            models.UniqueConstraint(
                fields=["recurring_event", "occurrence_date"],
                name="unique_recurring_exception_per_day",
            )
        ]

    def __str__(self):
        return f"{self.recurring_event.title} - {self.occurrence_date}"


class EventLog(models.Model):
    timestamp = models.DateTimeField(default=timezone.now)
    action_type = models.CharField(max_length=100)
    entity_type = models.CharField(max_length=100)
    entity_id = models.IntegerField(null=True, blank=True)
    details = models.JSONField(default=dict, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-timestamp"]

    def __str__(self):
        return f"{self.timestamp:%Y-%m-%d %H:%M:%S} - {self.action_type}"

class ScrapeRun(models.Model):
    STATUS_CHOICES = [
        ("started", "Started"),
        ("completed", "Completed"),
        ("failed", "Failed"),
    ]

    source_name = models.CharField(max_length=255)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="started")

    started_at = models.DateTimeField(default=timezone.now)
    completed_at = models.DateTimeField(null=True, blank=True)

    events_found = models.IntegerField(default=0)
    relevant_count = models.IntegerField(default=0)
    irrelevant_count = models.IntegerField(default=0)
    error_count = models.IntegerField(default=0)

    notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-started_at"]

    def __str__(self):
        return f"{self.source_name} - {self.started_at:%Y-%m-%d %H:%M} ({self.status})"


class ScrapedEvent(models.Model):
    RELEVANCE_CHOICES = [
        ("relevant", "Relevant"),
        ("irrelevant", "Irrelevant"),
        ("uncertain", "Uncertain"),
    ]

    REVIEW_STATUS_CHOICES = [
        ("unreviewed", "Unreviewed"),
        ("approved", "Approved"),
        ("corrected", "Corrected"),
        ("hidden", "Hidden"),
        ("canceled", "Canceled"),
        ("duplicate", "Duplicate"),
        ("bad_scrape", "Bad Scrape"),
    ]

    scrape_run = models.ForeignKey(
        ScrapeRun,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="scraped_events",
    )

    source_name = models.CharField(max_length=255)
    source_page = models.URLField(blank=True)
    event_url = models.URLField(blank=True)

    external_event_id = models.CharField(
        max_length=500,
        blank=True,
        help_text="Source-specific event ID if available."
    )

    title = models.CharField(max_length=500)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField(null=True, blank=True)

    venue = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    state = models.CharField(max_length=50, blank=True)
    location = models.CharField(max_length=500, blank=True)

    categories = models.JSONField(default=list, blank=True)
    summary = models.TextField(blank=True)

    relevance_status = models.CharField(
        max_length=20,
        choices=RELEVANCE_CHOICES,
        default="uncertain",
    )
    relevance_reason = models.TextField(blank=True)

    review_status = models.CharField(
        max_length=20,
        choices=REVIEW_STATUS_CHOICES,
        default="unreviewed",
    )
    review_notes = models.TextField(blank=True)

    raw_payload = models.JSONField(default=dict, blank=True)

    first_seen_at = models.DateTimeField(default=timezone.now)
    last_seen_at = models.DateTimeField(default=timezone.now)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_datetime", "title"]
        indexes = [
            models.Index(fields=["source_name", "external_event_id"]),
            models.Index(fields=["start_datetime"]),
            models.Index(fields=["review_status"]),
            models.Index(fields=["relevance_status"]),
        ]

    def __str__(self):
        return f"{self.title} ({self.start_datetime:%Y-%m-%d %H:%M})"


class ScrapedEventOverride(models.Model):
    ACTION_CHOICES = [
        ("correct", "Correct"),
        ("cancel", "Cancel"),
        ("hide", "Hide"),
        ("mark_irrelevant", "Mark Irrelevant"),
        ("mark_duplicate", "Mark Duplicate"),
    ]

    scraped_event = models.OneToOneField(
        ScrapedEvent,
        on_delete=models.CASCADE,
        related_name="override",
    )

    action = models.CharField(max_length=30, choices=ACTION_CHOICES)

    override_title = models.CharField(max_length=500, blank=True)
    override_start_datetime = models.DateTimeField(null=True, blank=True)
    override_end_datetime = models.DateTimeField(null=True, blank=True)

    override_venue = models.CharField(max_length=255, blank=True)
    override_city = models.CharField(max_length=100, blank=True)
    override_state = models.CharField(max_length=50, blank=True)
    override_location = models.CharField(max_length=500, blank=True)

    override_categories = models.JSONField(default=list, blank=True)
    override_summary = models.TextField(blank=True)

    override_event_url = models.URLField(blank=True)
    override_source_page = models.URLField(blank=True)

    reason = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-updated_at"]

    def __str__(self):
        return f"{self.scraped_event.title} override ({self.action})"

class ScrapeSource(models.Model):
    EXTRACTOR_CHOICES = [
        ("auto_calendar_check", "Auto calendar check"),
        ("zephyr", "Zephyr Wine Bar"),
        ("midtown", "Midtown Spirits"),
        ("max_casino", "Max Casino"),
    ]

    name = models.CharField(max_length=255, unique=True)
    url = models.URLField(blank=True)
    extractor_key = models.CharField(max_length=50, choices=EXTRACTOR_CHOICES)
    is_enabled = models.BooleanField(default=True)
    sort_order = models.IntegerField(default=0)

    notes = models.TextField(blank=True)

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["sort_order", "name"]

    def __str__(self):
        return self.name