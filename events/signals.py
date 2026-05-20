from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver
from .models import (
    ManualSingleEvent,
    ManualRecurringEvent,
    RecurringException,
    EventLog,
)


def write_log(action_type, instance, details=None):
    EventLog.objects.create(
        action_type=action_type,
        entity_type=instance.__class__.__name__,
        entity_id=instance.pk,
        details=details or {},
        note="",
    )


@receiver(post_save, sender=ManualSingleEvent)
def log_manual_single_event_save(sender, instance, created, **kwargs):
    action = "create" if created else "update"
    write_log(action, instance, {
        "title": instance.title,
        "status": instance.status,
    })


@receiver(post_save, sender=ManualRecurringEvent)
def log_manual_recurring_event_save(sender, instance, created, **kwargs):
    action = "create" if created else "update"
    write_log(action, instance, {
        "title": instance.title,
        "status": instance.status,
        "recurrence_type": instance.recurrence_type,
    })


@receiver(post_save, sender=RecurringException)
def log_recurring_exception_save(sender, instance, created, **kwargs):
    action = "create" if created else "update"
    write_log(action, instance, {
        "recurring_event_id": instance.recurring_event_id,
        "occurrence_date": str(instance.occurrence_date),
        "exception_type": instance.exception_type,
    })


@receiver(post_delete, sender=ManualSingleEvent)
def log_manual_single_event_delete(sender, instance, **kwargs):
    write_log("delete", instance, {
        "title": instance.title,
    })


@receiver(post_delete, sender=ManualRecurringEvent)
def log_manual_recurring_event_delete(sender, instance, **kwargs):
    write_log("delete", instance, {
        "title": instance.title,
    })


@receiver(post_delete, sender=RecurringException)
def log_recurring_exception_delete(sender, instance, **kwargs):
    write_log("delete", instance, {
        "recurring_event_id": instance.recurring_event_id,
        "occurrence_date": str(instance.occurrence_date),
        "exception_type": instance.exception_type,
    })