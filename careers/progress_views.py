from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from careers.services.progress import progress_for


class ProgressAPI(APIView):
    """
    GET /me/progress/  - the Progress Tracker screen (BACKEND.md section 3.8):
    careers explored, total careers, saved and category counts, streak,
    achievements and an insight, all from the user's own records.
    """

    permission_classes = [IsAuthenticated]

    def get(self, request):
        return Response(progress_for(request.user), status=status.HTTP_200_OK)
