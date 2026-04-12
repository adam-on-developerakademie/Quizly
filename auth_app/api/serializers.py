from rest_framework import serializers
from django.contrib.auth.models import User

class RegistrationSerializer(serializers.ModelSerializer):
    repeated_password = serializers.CharField(write_only=True)

    class Meta:
        model = User
        fields = ['username', 'email', 'password', 'repeated_password']
        extra_kwargs = {
            'password': {
                'write_only': True
            },
            'email': {
                'required': True
            }
        }

    def validate_repeated_password(self, value):
        password = self.initial_data.get('password')
        if password and value and password != value:
            raise serializers.ValidationError('Passwords do not match')
        return value

    def validate_email(self, value):
        if User.objects.filter(email=value).exists():
            raise serializers.ValidationError('Email already exists')
        return value

    def save(self):
        pw = self.validated_data['password']

        account = User(email=self.validated_data['email'], username=self.validated_data['username'])
        account.set_password(pw)
        account.save()
        return account
    
    
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth import get_user_model

User = get_user_model()
class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    
    # Wenn man E-Mail und Passwort anstelle von Benutzername und Passwort verwenden möchte,
    # muss man den username aus dem Standard Serializer entfernen :
    # E
    def __init__(self, *args, **kwargs):                                #E
        super().__init__(*args, **kwargs)                               #E
        # Standardmäßige 'username'-Feld entfernen                      #E                        
        if 'username' in self.fields:                                   #E
            self.fields.pop('username')                                 #E pop entfernt das standardmäßige 'username'-Feld, da wir stattdessen die E-Mail verwenden wollen.    

 
    def validate(self, attrs):
        # Hier können Sie die Validierung der Anmeldedaten durchführen
        # und zusätzliche Informationen zurückgeben, wenn ein Token erstellt wird.
        email = attrs.get('email')
        password = attrs.get('password')
        
        try:
            user = User.objects.get(email=email)
        except User.DoesNotExist:
            raise serializers.ValidationError('ungültige Anmeldedaten')
        
        if not user.check_password(password):
            raise serializers.ValidationError('ungültige Anmeldedaten')
        
        data = super().validate({"username": user.username, "password": password})
        return data