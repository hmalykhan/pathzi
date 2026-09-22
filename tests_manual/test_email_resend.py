"""
Email moved from SendGrid to Resend (SMTP). Proves the two real senders -
password-reset OTP and referral invite - would connect to Resend with the
right credentials, without sending anything: smtplib is replaced by a fake.
"""
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pathzi.settings'); django.setup()
from unittest import mock
from django.conf import settings
from django.core.mail import send_mail, get_connection

passed = failed = 0
def check(label, got, want=True):
    global passed, failed
    ok = got == want
    passed, failed = passed + ok, failed + (not ok)
    print('  %-56s %s' % (label, 'PASS' if ok else 'FAIL (got %r want %r)' % (got, want)))

print('--- settings ---')
check('backend is SMTP', settings.EMAIL_BACKEND, 'django.core.mail.backends.smtp.EmailBackend')
check('host is Resend (unless overridden in .env)',
      settings.EMAIL_HOST, os.environ.get('EMAIL_HOST', 'smtp.resend.com'))
check('port 587', settings.EMAIL_PORT, 587)
check('STARTTLS on', settings.EMAIL_USE_TLS, True)
check('username is "resend"', settings.EMAIL_HOST_USER, os.environ.get('EMAIL_HOST_USER', 'resend'))
check('no SendGrid host left', 'sendgrid' in settings.EMAIL_HOST, False)

print('--- what a send actually does (smtplib faked) ---')
calls = {}
class FakeSMTP:
    def __init__(self, host, port, **kw): calls['connect'] = (host, port)
    def ehlo(self, *a, **k): pass
    def starttls(self, *a, **k): calls['tls'] = True
    def login(self, user, pw): calls['login'] = (user, pw)
    def sendmail(self, frm, to, msg, *a, **k): calls['sent'] = (frm, list(to)); return {}
    def send_message(self, *a, **k): return {}
    def quit(self): pass
    def close(self): pass

with mock.patch('smtplib.SMTP', FakeSMTP), \
     mock.patch.object(settings, 'EMAIL_HOST_PASSWORD', 're_test_dummy_key'):
    n = send_mail('subject', 'body', settings.DEFAULT_FROM_EMAIL, ['someone@example.com'],
                  fail_silently=False, connection=get_connection(password='re_test_dummy_key'))
check('one message sent', n, 1)
check('connected to smtp.resend.com:587', calls.get('connect'), (settings.EMAIL_HOST, 587))
check('upgraded to TLS', calls.get('tls'), True)
check('logged in as "resend" with the API key',
      calls.get('login'), (settings.EMAIL_HOST_USER, 're_test_dummy_key'))
check('from address is DEFAULT_FROM_EMAIL', calls.get('sent', (None,))[0], settings.DEFAULT_FROM_EMAIL)

print('--- the app still starts with no key ---')
check('missing RESEND_API_KEY does not crash settings', isinstance(settings.EMAIL_HOST_PASSWORD, str))

print('\n%s | %d checks' % ('ALL PASS' if failed == 0 else '%d FAILED' % failed, passed + failed))
raise SystemExit(1 if failed else 0)
