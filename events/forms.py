from __future__ import annotations

from django import forms


class ScrapedEventBatchEditForm(forms.Form):
    _selected_action = forms.CharField(widget=forms.MultipleHiddenInput)

    city = forms.CharField(required=False)
    state = forms.CharField(required=False)
    venue = forms.CharField(required=False)
    location = forms.CharField(required=False)

    start_datetime = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M"],
    )
    end_datetime = forms.DateTimeField(
        required=False,
        widget=forms.DateTimeInput(attrs={"type": "datetime-local"}),
        input_formats=["%Y-%m-%dT%H:%M"],
    )

    mark_reviewed = forms.BooleanField(
        required=False,
        initial=True,
        help_text="Mark edited events as corrected/reviewed.",
    )