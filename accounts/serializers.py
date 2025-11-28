# from rest_framework import serializers
# from django.contrib.auth.models import User
# class UserSerializer(serializers.ModelSerializer ):
#     class Meta:
#         model = User
#         fields = ['username', 'email', 'password', 'password2']

# class SignUpSerializer(serializers.Serializer):
#     username = serializers.CharField()
#     email = serializers.CharField()
#     password = serializers.CharField(write_only = True, min_length = 8)
#     password2 = serializers.CharField(write_only = True, min_length = 8)

# class LoginSerializer(serializers.Serializer):
#     email = serializers.CharField()
#     password = serializers.CharField()




from rest_framework import serializers
from django.contrib.auth.models import User


class UserSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "username", "email"]  # don't expose password!


class SignUpSerializer(serializers.Serializer):
    username = serializers.CharField()
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True, min_length=8)
    password2 = serializers.CharField(write_only=True, min_length=8)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)

class ResetPasswordSerializer(serializers.Serializer):
    old_password = serializers.CharField(write_only=True)
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password2 = serializers.CharField(write_only=True, min_length=8)

class ForgotPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()


class ForgotPasswordConfirmSerializer(serializers.Serializer):
    uidb64 = serializers.CharField()
    token = serializers.CharField()
    new_password = serializers.CharField(write_only=True, min_length=8)
    new_password2 = serializers.CharField(write_only=True, min_length=8)

class GoogleAuthSerializer(serializers.Serializer):
    id_token = serializers.CharField()


class UserDataSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    username = serializers.CharField()
    email = serializers.EmailField()
    name = serializers.CharField()

class GoogleLoginResponseSerializer(serializers.Serializer):
    status = serializers.BooleanField()
    message = serializers.CharField()
    token = serializers.CharField()
    user = UserDataSerializer()