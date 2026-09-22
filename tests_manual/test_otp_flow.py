"""
Forgot-password flow end to end (reported 2026-09-22: "the email arrives but
the app says the OTP is wrong").

The backend accepted correct codes, but the success response of verify_otp
had no "status" key while every failure had status=false - and the
integration guide promised status=true. An app checking `status` therefore
rejected every correct code. Also pins the two genuine "wrong code" cases:
re-sending the code after it was verified, and typing a code a resend replaced.
"""
import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pathzi.settings'); django.setup()
from unittest import mock
from django.test import override_settings
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from accounts.models import UserProfile, PasswordResetOTP

U = get_user_model(); E = 'otp_suite_x@example.com'; PW = 'Zz!93kdlq77'; NEW = 'Nn!55wordq9'
passed = failed = 0
def check(label, got, want=True):
    global passed, failed
    ok = got == want
    passed, failed = passed + ok, failed + (not ok)
    print('  %-60s %s' % (label, 'PASS' if ok else 'FAIL (got %r want %r)' % (got, want)))

def clean():
    for u in U.objects.filter(email=E):
        PasswordResetOTP.objects.filter(user=u).delete(); UserProfile.objects.filter(appuser=u).delete(); u.delete()

clean(); sent = []
u = U.objects.create_user(username='otp_suite_x', email=E, password=PW); UserProfile.objects.create(appuser=u, age=0)
code = lambda: sent[-1].split('Your OTP is: ')[1][:6]
try:
    with override_settings(ALLOWED_HOSTS=['testserver'],
                           CACHES={'default': {'BACKEND': 'django.core.cache.backends.locmem.LocMemCache'}}), \
         mock.patch('accounts.views.send_email_async', lambda **k: sent.append(k['message'])):
        c = APIClient()
        print('\n--- the happy path, as the app should run it ---')
        r = c.post('/accounts/forgot_password/', {'email': E}, format='json')
        check('forgot_password -> 200', r.status_code, 200)
        check('an email with a 6-digit code went out', len(code()), 6)
        r = c.post('/accounts/verify_otp/', {'email': E, 'otp': code()}, format='json'); b = r.json()
        check('verify_otp with the right code -> 200', r.status_code, 200)
        check('  status is TRUE (was missing)', b.get('status'), True)
        check('  valid is still true (older builds)', b.get('valid'), True)
        check('  reset_token handed back', str(b.get('reset_token', '')).startswith('rt_'))
        r = c.post('/accounts/forgot_password_confirmation/', {'email': E, 'reset_token': b['reset_token'],
                   'new_password': NEW, 'confirm_password': NEW}, format='json')
        check('confirmation with the token -> 200', r.status_code, 200)
        u.refresh_from_db(); check('  password actually changed', u.check_password(NEW))

        print('\n--- wrong code ---')
        c.post('/accounts/forgot_password/', {'email': E}, format='json')
        r = c.post('/accounts/verify_otp/', {'email': E, 'otp': '000000' if code() != '000000' else '111111'}, format='json')
        check('-> 400', r.status_code, 400)
        check('  status false, code otp_invalid',
              (r.json().get('status'), r.json().get('code')), (False, 'otp_invalid'))

        print('\n--- code sent as a number, not a string ---')
        c.post('/accounts/forgot_password/', {'email': E}, format='json')
        r = c.post('/accounts/verify_otp/', {'email': E, 'otp': int(code())}, format='json')
        check('-> 200', r.status_code, 200)

        print('\n--- the two genuine "Incorrect OTP" cases ---')
        c.post('/accounts/forgot_password/', {'email': E}, format='json'); cd = code()
        c.post('/accounts/verify_otp/', {'email': E, 'otp': cd}, format='json')
        r = c.post('/accounts/forgot_password_confirmation/', {'email': E, 'otp': cd,
                   'new_password': NEW, 'confirm_password': NEW}, format='json')
        check('re-sending a code already verified -> 400 Incorrect OTP',
              (r.status_code, r.json().get('message')), (400, 'Incorrect OTP'))
        c.post('/accounts/forgot_password/', {'email': E}, format='json'); first = code()
        c.post('/accounts/forgot_password/', {'email': E}, format='json'); second = code()
        r = c.post('/accounts/verify_otp/', {'email': E, 'otp': first}, format='json')
        check('code from the OLDER email after a resend -> 400',
              r.status_code, 400 if first != second else 200)
        r = c.post('/accounts/verify_otp/', {'email': E, 'otp': second}, format='json')
        check('code from the LATEST email -> 200', r.status_code, 200)

        print('\n--- UNCHANGED: older builds that send the code straight to confirmation ---')
        c.post('/accounts/forgot_password/', {'email': E}, format='json')
        r = c.post('/accounts/forgot_password_confirmation/', {'email': E, 'otp': code(),
                   'new_password': PW, 'confirm_password': PW}, format='json')
        check('-> 200', r.status_code, 200)

        print('\n--- UNCHANGED: unknown email looks exactly like a wrong code ---')
        r = c.post('/accounts/verify_otp/', {'email': 'nobody-zz@example.com', 'otp': '123456'}, format='json')
        check('-> 400 otp_invalid', (r.status_code, r.json().get('code')), (400, 'otp_invalid'))
finally:
    clean()
    print('\n%s | %d checks | test users left: %d'
          % ('ALL PASS' if failed == 0 else '%d FAILED' % failed, passed + failed, U.objects.filter(email=E).count()))
    raise SystemExit(1 if failed else 0)
