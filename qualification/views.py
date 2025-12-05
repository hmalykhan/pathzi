from django.shortcuts import render
from .models import Qualification
from .api.serializer import QualificationSerializer
from rest_framework import viewsets
from accounts.models import UserProfile
from rest_framework.exceptions import ValidationError

class QualificationVeiw(viewsets.ModelViewSet):
    queryset = Qualification.objects.all()
    serializer_class = QualificationSerializer

    def create_qualification(self, request,pk):
        user = UserProfile.objects.get(pk = pk)
        if not user:
            raise ValidationError("No user found")
        user.save(qualification = request.data)
        print("here you can create the qualification of a particular user right.")