from django.apps import AppConfig


class BillingConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'billing'

    def ready(self):
        import stripe
        from django.conf import settings
        from stripe._http_client import RequestsClient

        stripe.api_key = settings.STRIPE_SECRET_KEY
        stripe.default_http_client = RequestsClient(timeout=20)
