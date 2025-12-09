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
from .api.permissions import AdminOnlyForCrud
class QualificationVeiw(viewsets.ModelViewSet):
    queryset = Qualification.objects.all()
    serializer_class = QualificationSerializer
    permission_classes = [AdminOnlyForCrud]
    
    @action(detail=False, methods=["POST"])
    def add(self, request):
        try:
            user_profile = UserProfile.objects.get(appuser = request.user)
        except UserProfile.DoesNotExist:
            return Response({'error': 'UserProfile not found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(data = request.data)
        serializer.is_valid(raise_exception = True)
        serializer.save(user_profile = user_profile)
        return Response({
            "Message":f"""qualification has been added to the {user_profile.appuser.username}""",
            "data":serializer.data
        }, status = status.HTTP_201_CREATED)
    
    @action(detail=False, methods=["GET"])
    def all(self, request):
        try:
            qualificaitons = Qualification.objects.filter(user_profile__appuser = request.user)
        except Qualification.DoesNotExist:
            return Response({'error': 'No qualification found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(qualificaitons, many=True)
        return Response({"data":serializer.data})

    @action(detail=False, methods=["GET","PATCH"], url_path=r"edit(?:/(?P<pk>[^/.]+))?")
    def edit(self, request, pk=None):
        if request.method  == "GET":
            try:
                qualificaitons = Qualification.objects.filter(pk = pk, user_profile__appuser = request.user)
            except Qualification.DoesNotExist:
                return Response({'error': 'No qualification found.'}, status=status.HTTP_404_NOT_FOUND)
            serializer = self.get_serializer(qualificaitons, many=True)
            return Response({"data":serializer.data})
        try:
            qualification = Qualification.objects.get(pk=pk, user_profile__appuser = request.user)
        except Qualification.DoesNotExist:
                return Response({'error': 'No qualification found.'}, status=status.HTTP_404_NOT_FOUND)
        serializer = self.get_serializer(qualification, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        serializer.save(user_profile = UserProfile.objects.get(appuser = request.user))
        return Response({"message":"data has been updated","data":serializer.data},status=status.HTTP_200_OK)

    @action(detail=False, methods=["DELETE","GET"], url_path=r"delete(?:/(?P<pk>[^/.]+))?")
    def delete(self, request, pk=None):
        try:
            qualificaitons = Qualification.objects.get(pk=pk, user_profile__appuser = request.user)
        except Qualification.DoesNotExist:
            return Response({'error': 'No qualification found.'}, status=status.HTTP_404_NOT_FOUND)
        if request.method  == "GET":
            serializer = self.get_serializer(qualificaitons)
            return Response({"data":serializer.data})
        qualification = Qualification.objects.get(pk=pk)
        qualification.delete()
        return Response({"message":"qualification has been deleted"},status=status.HTTP_200_OK)