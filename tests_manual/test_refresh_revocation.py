"""
Ended sessions must not be able to refresh (reported 2026-09-22).

Device B's refresh token used to keep working after "sign out other
devices", a password change or a password reset: the refresh endpoint ran
no revocation check, and the access token it minted was new enough to pass.
Every case goes through the real HTTP endpoints, as the app does.
"""
import os, django, time
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pathzi.settings'); django.setup()
from django.test import override_settings
from rest_framework.test import APIClient
from rest_framework_simplejwt.tokens import RefreshToken
from django.contrib.auth import get_user_model
from accounts.models import UserProfile
from accounts.sign_out_views import revoke_all_tokens

U = get_user_model(); P = 'rrv_'; PW = 'Zz!93kdlq77'
passed = failed = 0
def check(label, got, want=True):
    global passed, failed
    ok = got == want
    passed, failed = passed + ok, failed + (not ok)
    print('  %-62s %s' % (label, 'PASS' if ok else 'FAIL (got %r want %r)' % (got, want)))

def clean():
    for u in U.objects.filter(username__startswith=P):
        UserProfile.objects.filter(appuser=u).delete(); u.delete()

def mk(name):
    u = U.objects.create_user(username=P + name, email=P + name + '@example.com', password=PW)
    UserProfile.objects.create(appuser=u, age=0)
    return u

def device(u):
    r = RefreshToken.for_user(u)
    return {'refresh': str(r), 'access': str(r.access_token)}

def profile_status(access):
    c = APIClient(); c.credentials(HTTP_AUTHORIZATION='Bearer ' + access)
    return c.get('/accounts/user_profile/')

def refresh(tok):
    return APIClient().post('/accounts/api/token/refresh/', {'refresh': tok}, format='json')

def code_of(r):
    try: return r.json().get('code')
    except Exception: return None

def assert_ended(label, dev):
    r = profile_status(dev['access'])
    check('%s: old access rejected' % label, r.status_code in (401, 403))
    check('%s:   code is session_ended' % label, code_of(r), 'session_ended')
    r = refresh(dev['refresh'])
    check('%s: old REFRESH rejected (was 200)' % label, r.status_code in (401, 403))
    check('%s:   code is session_ended' % label, code_of(r), 'session_ended')
    check('%s:   no new access token handed out' % label, 'access' in (r.json() or {}), False)

clean()
try:
    with override_settings(ALLOWED_HOSTS=['testserver']):
        print('\n--- UNCHANGED: a user who never signed out anywhere ---')
        u0 = mk('plain'); d0 = device(u0)
        r = refresh(d0['refresh'])
        check('refresh -> 200', r.status_code, 200)
        check('new access works', profile_status(r.json()['access']).status_code, 200)
        check('garbage refresh still rejected as before', code_of(refresh('not.a.token')), 'token_not_valid')

        print('\n--- 1. sign out other devices (Saad\'s exact repro) ---')
        u = mk('so'); A = device(u); B = device(u)
        time.sleep(1.2)                         # B's tokens predate the sign-out
        cA = APIClient(); cA.credentials(HTTP_AUTHORIZATION='Bearer ' + A['access'])
        r = cA.post('/accounts/sign-out-other-devices/', {}, format='json')
        check('sign-out -> 200', r.status_code, 200)
        newA = r.json()['data']['token']
        assert_ended('device B', B)
        check('device A: NEW access works', profile_status(newA['access']).status_code, 200)
        r = refresh(newA['refresh'])
        check('device A: NEW refresh works', r.status_code, 200)
        check('device A:   and its new access works', profile_status(r.json()['access']).status_code, 200)
        check("device A: its OLD refresh is ended too (app must store the new pair)",
              code_of(refresh(A['refresh'])), 'session_ended')

        print('\n--- 2. change password ---')
        u = mk('cp'); A = device(u); B = device(u)
        time.sleep(1.2)
        cA = APIClient(); cA.credentials(HTTP_AUTHORIZATION='Bearer ' + A['access'])
        r = cA.post('/accounts/reset_password/', {'old_password': PW, 'new_password': 'Nn!55wordq9',
                    'new_password2': 'Nn!55wordq9'}, format='json')
        check('change password -> 200', r.status_code, 200)
        assert_ended('other device', B)
        newA = r.json()['data']['token']
        check('this device: new pair works', refresh(newA['refresh']).status_code, 200)

        print('\n--- 3. password reset (same revoke call the reset view makes) ---')
        u = mk('pr'); B = device(u)
        time.sleep(1.2)
        revoke_all_tokens(u, keep_current=False)
        assert_ended('every device', B)
        r = APIClient().post('/accounts/api/token/', {'username': P + 'pr', 'password': PW}, format='json')
        check('signing in again works', r.status_code, 200)
        check('  and that session refreshes', refresh(r.json()['refresh']).status_code, 200)
finally:
    clean()
    left = U.objects.filter(username__startswith=P).count()
    print('\n%s | %d checks | test users left: %d'
          % ('ALL PASS' if failed == 0 else '%d FAILED' % failed, passed + failed, left))
    raise SystemExit(1 if failed or left else 0)
