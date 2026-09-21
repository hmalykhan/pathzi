"""
Referral codes on Google and Apple sign-in.

Reported 2026-09-21: "codes don't apply on social sign-in". They do - but
only for an account that did not already exist, and until now a skipped code
came back as applied=false with no reason, which read as a rejected code.
"""
import os, django, json, uuid
os.environ.setdefault('DJANGO_SETTINGS_MODULE','pathzi.settings'); django.setup()
from unittest import mock
from django.test import override_settings
from django.conf import settings
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from accounts.models import UserProfile
from billing.models import ReferralCode, ReferralCredit
from billing.services import referrals
from billing.services.access import access_for

U = get_user_model(); P = 'socref_'
passed = failed = 0
def check(label, got, want=True):
    global passed, failed
    ok = got == want
    passed, failed = passed+ok, failed+(not ok)
    print('  %-60s %s' % (label, 'PASS' if ok else 'FAIL (got %r want %r)' % (got, want)))

def clean():
    us = set(list(U.objects.filter(email__startswith=P)) + list(U.objects.filter(username__startswith=P)))
    ReferralCredit.objects.filter(user__in=us).delete()
    ReferralCode.objects.filter(created_by__in=us).delete()
    for u in us:
        UserProfile.objects.filter(appuser=u).delete(); u.delete()

clean()
AUD = (settings.GOOGLE_WEB_CLIENT_ID or settings.GOOGLE_ANDROID_CLIENT_ID
       or settings.GOOGLE_IOS_CLIENT_ID or 'test-aud')

def google(c, email, code=None, sub=None):
    fake = {'email': email, 'email_verified': True, 'aud': AUD,
            'given_name': 'G', 'family_name': 'Y', 'sub': sub or uuid.uuid4().hex}
    body = {'id_token': 'stub'}
    if code: body['referral_code'] = code
    with mock.patch('accounts.views.google_id_token.verify_oauth2_token', return_value=fake):
        return c.post('/accounts/auth/google/', body, format='json')

def apple(c, email, code=None, sub=None):
    payload = {'email': email, 'sub': sub or uuid.uuid4().hex, 'email_verified': True}
    body = {'identity_token': 'stub'}
    if code: body['referral_code'] = code
    # Two stubs: the view first checks the token is a decodable JWT at all
    # (the guard added on 2026-09-21), then verifies it properly.
    with mock.patch('accounts.views.verify_apple_token', return_value=payload), \
         mock.patch('accounts.views.jwt.decode', return_value=payload):
        return c.post('/accounts/auth/apple/', body, format='json')

try:
    with override_settings(ALLOWED_HOSTS=['testserver'], GOOGLE_WEB_CLIENT_ID=AUD):
        c = APIClient()
        c.post('/accounts/signup/', {'username': P+'ref', 'email': P+'ref@example.com',
               'password': 'Zz!93kdlq77', 'password2': 'Zz!93kdlq77'}, format='json')
        ref = U.objects.get(email=P+'ref@example.com')

        for name, fn in [('GOOGLE', google), ('APPLE', apple)]:
            print('\n--- %s: brand-new account WITH a code ---' % name)
            code = referrals.create_code(ref).code
            before = access_for(ref)['days_remaining']
            em = '%s%s_new@example.com' % (P, name.lower())
            r = fn(c, em, code)
            check('sign-in -> 200', r.status_code, 200)
            d = r.json()['data']
            check('is_new_user true', d.get('is_new_user'), True)
            check('referral applied', (d.get('referral') or {}).get('applied'), True)
            nu = U.objects.get(email=em)
            check('invitee gets the plain 7-day trial', access_for(nu)['days_remaining'], 7)
            check('referrer gained 7 days', access_for(ref)['days_remaining'], before + 7)
            check('code marked used', ReferralCode.objects.get(code=code).used_at is not None)

            print('--- %s: account that ALREADY exists ---' % name)
            code2 = referrals.create_code(ref).code
            r = fn(c, em, code2)
            d = r.json()['data']
            check('is_new_user false', d.get('is_new_user'), False)
            blk = d.get('referral')
            check('a reason IS returned now (was null)', blk is not None)
            check('  reason is referral_not_new_user',
                  (blk or {}).get('code'), 'referral_not_new_user')
            check('  applied false', (blk or {}).get('applied'), False)
            check('the code was NOT spent',
                  ReferralCode.objects.get(code=code2).used_at is None)

            print('--- %s: existing account, no code at all ---' % name)
            r = fn(c, em)
            check('referral block is null', r.json()['data'].get('referral'), None)

            print('--- %s: brand-new account, BAD code ---' % name)
            em2 = '%s%s_bad@example.com' % (P, name.lower())
            r = fn(c, em2, 'PTH-NOTREAL')
            d = r.json()['data']
            check('sign-in still succeeds', r.status_code, 200)
            check('reason given', (d.get('referral') or {}).get('code'), 'referral_code_invalid')
finally:
    clean()
    left = U.objects.filter(email__startswith=P).count()
    print('\n%s | %d checks | test users left: %d'
          % ('ALL PASS' if failed == 0 else '%d FAILED' % failed, passed+failed, left))
    raise SystemExit(1 if failed or left else 0)
