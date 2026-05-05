from rest_framework.throttling import UserRateThrottle


class InteractionThrottle(UserRateThrottle):
    scope = "interaction"