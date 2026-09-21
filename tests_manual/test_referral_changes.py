"""
The two referral changes asked for on 2026-09-21:
  1. the invitee earns nothing (7-day trial only, not 14)
  2. sign-up without a referral_code returns no referral block

Plus the thing neither request mentions: the invitee credit row must still
be written, because it is what stops one account redeeming a second code.
"""
import os, django, json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pathzi.settings'); django.setup()

from django.test import override_settings
from django.utils import timezone
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from accounts.models import UserProfile
from billing.models import ReferralCode, ReferralCredit
from billing.services import referrals
from billing.services.access import access_for

U = get_user_model()
PREFIX = 'rc_suite_'
passed = failed = 0

def check(label, got, want=True):
    global passed, failed
    ok = (got == want)
    passed, failed = passed + ok, failed + (not ok)
    print('  %-62s %s' % (label, 'PASS' if ok else 'FAIL (got %r want %r)' % (got, want)))

def signup(c, name, extra=None):
    body = {'username': PREFIX + name, 'email': '%s%s@example.com' % (PREFIX, name),
            'password': 'Zz!93kdlq77', 'password2': 'Zz!93kdlq77'}
    body.update(extra or {})
    return c.post('/accounts/signup/', body, format='json')

def cleanup():
    users = list(U.objects.filter(username__startswith=PREFIX))
    ReferralCredit.objects.filter(user__in=users).delete()
    ReferralCode.objects.filter(created_by__in=users).delete()
    for u in users:
        UserProfile.objects.filter(appuser=u).delete(); u.delete()

cleanup()
try:
    with override_settings(ALLOWED_HOSTS=['testserver']):
        c = APIClient()

        print('\n--- the constant ---')
        check('INVITEE_DAYS is 0', referrals.INVITEE_DAYS, 0)
        check('REFERRER_DAYS still 7', referrals.REFERRER_DAYS, 7)

        # User A signs up and makes a code
        signup(c, 'a')
        a = U.objects.get(username=PREFIX + 'a')
        pa = UserProfile.objects.get(appuser=a)
        a_days_before = access_for(a)['days_remaining']
        check('referrer starts on the 7-day trial', a_days_before, 7)

        c.force_authenticate(user=a)
        r = c.post('/me/referral/codes/', {}, format='json')
        check('POST /me/referral/codes/ -> 201', r.status_code, 201)
        code = r.json()['data']['code']
        check('a code came back', bool(code))

        print('\n--- User B signs up WITH the code ---')
        c2 = APIClient()
        r = signup(c2, 'b', {'referral_code': code})
        check('signup -> 201', r.status_code, 201)
        b = U.objects.get(username=PREFIX + 'b')
        pb = UserProfile.objects.get(appuser=b)

        body = r.json()['data']
        check('referral block present when a code WAS sent', body.get('referral') is not None)
        check('  applied is true', body['referral'].get('applied'), True)
        check('  days_awarded is 0', body['referral'].get('days_awarded'), 0)
        check('  message no longer promises bonus days',
              'bonus days' not in (body['referral'].get('message') or ''))

        acc_b = access_for(b)
        check('INVITEE gets 7 days, not 14', acc_b['days_remaining'], 7)
        check('  source is the trial, not a referral', acc_b['source'], 'trial')
        pb.refresh_from_db()
        check('  no referral access window granted', pb.referral_access_until, None)
        check('  nothing banked', pb.referral_days_banked, 0)

        print('\n--- the referrer still gets +7 ---')
        acc_a = access_for(a)
        check('REFERRER now has 14 days', acc_a['days_remaining'], 14)
        pa.refresh_from_db()
        check('  referral window was extended', pa.referral_access_until is not None)

        print('\n--- credit rows ---')
        inv = ReferralCredit.objects.filter(user=b, kind='invitee').first()
        check('invitee credit row STILL written', inv is not None)
        check('  but worth 0 days', getattr(inv, 'days_awarded', None), 0)
        ref = ReferralCredit.objects.filter(user=a, kind='referrer').first()
        check('referrer credit row written', ref is not None)
        check('  worth 7 days', getattr(ref, 'days_awarded', None), 7)

        print('\n--- one account still cannot redeem a SECOND code ---')
        c.force_authenticate(user=a)
        r2 = c.post('/me/referral/codes/', {}, format='json')
        code2 = r2.json()['data']['code']
        try:
            referrals.redeem(code2, b)
            check('second code refused', False, 'it was allowed')
        except referrals.ReferralError as e:
            check('second code refused', e.code, 'referral_already_credited')

        print('\n--- sign-up WITHOUT a code returns no referral block ---')
        c3 = APIClient()
        r = signup(c3, 'd')
        check('signup -> 201', r.status_code, 201)
        d = r.json()['data']
        check('referral is null (was applied:false)', d.get('referral'), None)
        check('the key is still present, so the shape is stable', 'referral' in d)
        check('everything else unchanged',
              sorted(d.keys()), sorted(['id','username','email','user_type','referral','token']))

        print('\n--- a BAD code still reports the failure ---')
        c4 = APIClient()
        r = signup(c4, 'e', {'referral_code': 'NOPE-NOT-REAL'})
        check('signup still succeeds -> 201', r.status_code, 201)
        blk = r.json()['data'].get('referral')
        check('referral block IS returned for a bad code', blk is not None)
        check('  applied false', blk.get('applied'), False)
        check('  with a reason', blk.get('code'), 'referral_code_invalid')

        print('\n--- the referral summary reports the new numbers ---')
        c.force_authenticate(user=a)
        s = c.get('/me/referral/').json()['data']
        check('invitee_days reported as 0', s.get('invitee_days'), 0)
        check('referrer_days still 7', s.get('referrer_days'), 7)
        check('friends_joined counted', s.get('friends_joined'), 1)
finally:
    cleanup()
    left = U.objects.filter(username__startswith=PREFIX).count()
    print('\n%s | %d checks | test users left: %d'
          % ('ALL PASS' if failed == 0 else '%d FAILED' % failed, passed + failed, left))
    raise SystemExit(1 if failed or left else 0)
