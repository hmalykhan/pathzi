from django.shortcuts import render
from .models import Qualification
from .api.serializer import QualificationSerializer
from rest_framework import viewsets
from accounts.models import UserProfile
from rest_framework.exceptions import ValidationError
from rest_framework.decorators import action
from rest_framework import status
from rest_framework.response import Response
from rest_framework import permissions
class QualificationVeiw(viewsets.ModelViewSet):
    queryset = Qualification.objects.all()
    serializer_class = QualificationSerializer
    authentication_classes = [permissions.IsAuthenticated]

    @action(detail=True, methods=["POST"])
    def add(self, request, pk=None):
        try:
            user_profile = UserProfile.objects.get(pk = pk)
        except UserProfile.DoesNotExist:
            return Response({'error': 'UserProfile not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(data = request.data)
        serializer.is_valid(raise_exception = True)
        serializer.save(user_profile = user_profile)
        return Response({
            "Message":f"""qualification has been added to the {user_profile.appuser.username}""",
            "data":serializer.data
        }, status = status.HTTP_201_CREATED)
    
    @action(detail=True, methods=["GET"])
    def all(self, request, pk = None):
        try:
            user_profile = UserProfile.objects.get(pk = pk)
        except UserProfile.DoesNotExist:
            return Response({'error': 'UserProfile not found.'}, status=status.HTTP_404_NOT_FOUND)
        try:
            qualificaitons = Qualification.objects.filter(user_profile = user_profile)
        except Qualification.DoesNotExist:
            return Response({'error': 'No qualification found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(qualificaitons, many=True)
        return Response({"data":serializer.data})
    
    @action(detail=True, methods=["GET","PATCH"], url_path="edit/(?P<qk>[^/.]+)")
    def edit(self, request, pk=None, qk=None):
        try:
            qualification = Qualification.objects.get(pk = qk)
        except Qualification.DoesNotExist:
            return Response({'error': 'qualification not found.'}, status=status.HTTP_404_NOT_FOUND)
        if request.method  == "GET":
            serializer = self.get_serializer(qualification)
            return Response({"data":serializer.data})
        serializer = self.get_serializer(qualification, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save()
        return Response({"message":"data has been updated","data":serializer.data},status=status.HTTP_200_OK)
    
    @action(detail=True, methods=["DELETE","GET"], url_path="delete/(?P<qk>[^/.]+)")
    def delete(self, request, pk=None, qk=None):
        try:
            qualification = Qualification.objects.get(pk = qk)
        except Qualification.DoesNotExist:
            return Response({'error': 'qualification not found.'}, status=status.HTTP_404_NOT_FOUND)
        if request.method  == "GET":
            serializer = self.get_serializer(qualification)
            return Response({"data":serializer.data})
        qualification.delete()
        return Response({"message":"qualification has been deleted"},status=status.HTTP_200_OK)