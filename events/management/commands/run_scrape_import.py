from django.core.management.base import BaseCommand

from events.scraper_import import run_scrape_import


class Command(BaseCommand):
    help = "Run scraper import in preview or commit mode."

    def add_arguments(self, parser):
        parser.add_argument(
            "--commit",
            action="store_true",
            help="Write scraped events to the database. Default is preview-only.",
        )

    def handle(self, *args, **options):
        preview_only = not options["commit"]
        result = run_scrape_import(preview_only=preview_only)
        self.stdout.write(self.style.SUCCESS("Scrape run complete."))
        self.stdout.write(str(result))