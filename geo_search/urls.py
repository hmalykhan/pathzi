from django.urls import path
from .views import (
    LocationAutocompleteAPI,
    NearbySearchAPI,
    CitiesListAPI,
    PostcodesListAPI,
)

urlpatterns = [
    path("autocomplete/", LocationAutocompleteAPI.as_view(), name="geo-autocomplete"),
    path("nearby/", NearbySearchAPI.as_view(), name="geo-nearby"),

    # ✅ NEW: full DB lists
    path("cities/", CitiesListAPI.as_view(), name="geo-cities"),
    path("postcodes/", PostcodesListAPI.as_view(), name="geo-postcodes"),
]
