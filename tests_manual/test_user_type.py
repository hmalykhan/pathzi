"""
user_type across signup, GET, PATCH and the light profile.

Also pins the sign-up behaviour that must NOT have changed: a request that
never mentions user_type has to behave exactly as it did before.
"""
import os, django, json
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'pathzi.settings'); django.setup()

from django.test import override_settings
from rest_framework.test import APIClient
from django.contrib.auth import get_user_model
from accounts.models import UserProfile

U = get_user_model()
PREFIX = 'ut_suite_'
passed = failed = 0

def check(label, got, want=True):
    global passed, failed
    ok = (got == want)
    passed, failed = passed + ok, failed + (not ok)
    print('  %-62s %s' % (label, 'PASS' if ok else 'FAIL (got %r want %r)' % (got, want)))

def signup(c, name, body_extra=None):
    body = {'username': PREFIX + name, 'email': '%s%s@example.com' % (PREFIX, name),
            'password': 'Zz!93kdlq77', 'password2': 'Zz!93kdlq77'}
    body.update(body_extra or {})
    return c.post('/accounts/signup/', body, format='json')

def cleanup():
    for u in U.objects.filter(username__startswith=PREFIX):
        UserProfile.objects.filter(appuser=u).delete(); u.delete()
    U.objects.filter(email__startswith=PREFIX).delete()

cleanup()
try:
    with override_settings(ALLOWED_HOSTS=['testserver']):
        c = APIClient()

        print('\n--- signup now stores user_type ---')
        r = signup(c, 'a', {'user_type': 'student'})
        check('signup with a valid user_type -> 201', r.status_code, 201)
        u = U.objects.get(username=PREFIX + 'a')
        p = UserProfile.objects.get(appuser=u)
        check('it is actually stored (was silently dropped before)', p.user_type, 'student')
        check('it is echoed in the response', r.json()['data'].get('user_type'), 'student')

        print('\n--- skipping the question ---')
        for name, sent in [('b', ''), ('c', None)]:
            r = signup(c, name, {'user_type': sent})
            check('signup with user_type=%r -> 201' % sent, r.status_code, 201)
            p = UserProfile.objects.get(appuser=U.objects.get(username=PREFIX + name))
            check('  stored as NULL', p.user_type, None)

        print('\n--- UNCHANGED: signup that never mentions user_type ---')
        r = signup(c, 'd')
        check('still 201', r.status_code, 201)
        body = r.json()
        check('status flag unchanged', body.get('status'), True)
        check('message unchanged', body.get('message'), 'User created successfully.')
        check('data keys are the old ones plus user_type',
              sorted(body['data'].keys()),
              sorted(['id', 'username', 'email', 'user_type', 'referral', 'token']))
        check('tokens still issued', set(body['data']['token']) == {'refresh', 'access'})
        p = UserProfile.objects.get(appuser=U.objects.get(username=PREFIX + 'd'))
        check('user_type is NULL when not sent', p.user_type, None)
        check('trial still started at signup', p.trial_ends_at is not None)
        check('account_uuid still assigned', p.account_uuid is not None)

        print('\n--- invalid value is rejected, not silently dropped ---')
        r = signup(c, 'e', {'user_type': 'astronaut'})
        check('signup with a bad user_type -> 400', r.status_code, 400)
        check('no user was created', U.objects.filter(username=PREFIX + 'e').exists(), False)
        check('message names the problem', 'not a valid choice' in r.json().get('message', ''))

        print('\n--- all four personas accepted at signup ---')
        for i, persona in enumerate(['student', 'parent_guardian', 'career_changer', 'reskilling']):
            nm = 'p%d' % i
            rr = signup(c, nm, {'user_type': persona})
            got = UserProfile.objects.get(appuser=U.objects.get(username=PREFIX + nm)).user_type
            check('%-16s stored' % persona, got, persona)

        print('\n--- GET and PATCH still work ---')
        # Re-fetch: `p` was rebound to other users' profiles by the loops above.
        p = UserProfile.objects.get(appuser=u)
        c.force_authenticate(user=u)
        g = c.get('/accounts/user_profile/')
        check('GET /accounts/user_profile/ -> 200', g.status_code, 200)
        check('  returns the stored value', g.json().get('user_type'), 'student')
        check('  access block still present', 'access' in g.json())

        pr = c.patch('/accounts/user_profile/', {'user_type': 'reskilling'}, format='json')
        check('PATCH -> 200', pr.status_code, 200)
        check('  response shows the new value', pr.json().get('user_type'), 'reskilling')
        p.refresh_from_db(); check('  stored', p.user_type, 'reskilling')

        pr = c.patch('/accounts/user_profile/', {'user_type': ''}, format='json')
        p.refresh_from_db()
        check('PATCH "" clears it -> 200', pr.status_code, 200)
        check('  stored as NULL', p.user_type, None)

        pr = c.patch('/accounts/user_profile/', {'user_type': 'astronaut'}, format='json')
        p.refresh_from_db()
        check('PATCH invalid -> 400', pr.status_code, 400)
        check('  value left alone', p.user_type, None)

        print('\n--- light profile now carries it ---')
        c.patch('/accounts/user_profile/', {'user_type': 'parent_guardian'}, format='json')
        lr = c.get('/accounts/user_profile/light/')
        check('GET /accounts/user_profile/light/ -> 200', lr.status_code, 200)
        lb = lr.json()
        check('  includes user_type', lb.get('user_type'), 'parent_guardian')
        check('  old light fields still present',
              all(k in lb for k in ['id', 'name', 'age', 'discipline', 'education_level']))

        print('\n--- PATCH of other fields is unaffected ---')
        pr = c.patch('/accounts/user_profile/',
                     {'discipline': 'Engineering', 'category': ['it']}, format='json')
        check('unrelated PATCH -> 200', pr.status_code, 200)
        p.refresh_from_db()
        check('  discipline written', p.discipline, 'Engineering')
        check('  user_type untouched by it', p.user_type, 'parent_guardian')
finally:
    cleanup()
    left = U.objects.filter(username__startswith=PREFIX).count()
    print('\n%s | %d checks | test users left: %d'
          % ('ALL PASS' if failed == 0 else '%d FAILED' % failed, passed + failed, left))
    raise SystemExit(1 if failed or left else 0)
