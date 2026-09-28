from rest_framework import serializers

from apps.common.fields import PasswordField, PhoneField, TextField

from .models import Language, TrustMode, User


class RegisterIn(serializers.Serializer):
    phone = PhoneField()
    password = PasswordField()
    full_name = TextField(max_length=120)
    preferred_language = serializers.ChoiceField(
        Language.choices,
        required=False,
        help_text="Language of SMS and messages. Defaults to the request's Accept-Language.",
    )


class PhoneCodeIn(serializers.Serializer):
    phone = PhoneField()
    code = serializers.CharField(max_length=16)


class PhoneIn(serializers.Serializer):
    phone = PhoneField()


class AcceptedOut(serializers.Serializer):
    detail = serializers.CharField()
    resend_after = serializers.IntegerField()


class LoginIn(serializers.Serializer):
    phone = PhoneField()
    password = PasswordField()
    device_token = serializers.CharField(required=False, max_length=512)
    trust_mode = serializers.ChoiceField(
        [TrustMode.PERSONAL, TrustMode.SHARED],
        default=TrustMode.SHARED,
        help_text="PERSONAL only when this is the citizen's own phone; staff ignore it.",
    )


class TokensOut(serializers.Serializer):
    access = serializers.CharField()
    refresh = serializers.CharField()
    session_id = serializers.UUIDField()
    token_type = serializers.CharField()
    expires_in = serializers.IntegerField()


class LoginOut(serializers.Serializer):
    device_token = serializers.CharField(help_text="Keep it and send it on later logins.")
    mfa_required = serializers.BooleanField()
    mfa_token = serializers.CharField(required=False)
    access = serializers.CharField(required=False)
    refresh = serializers.CharField(required=False)
    session_id = serializers.UUIDField(required=False)
    token_type = serializers.CharField(required=False)
    expires_in = serializers.IntegerField(required=False)


class SecondFactorIn(serializers.Serializer):
    mfa_token = serializers.CharField(max_length=2048)
    code = serializers.CharField(max_length=32)


class RefreshIn(serializers.Serializer):
    refresh = serializers.CharField(max_length=128)


class ResetConfirmIn(serializers.Serializer):
    phone = PhoneField()
    code = serializers.CharField(max_length=16)
    new_password = PasswordField()


class ChangePasswordIn(serializers.Serializer):
    current_password = PasswordField()
    new_password = PasswordField()


class TotpSetupOut(serializers.Serializer):
    secret = serializers.CharField()
    otpauth_uri = serializers.CharField()


class TotpConfirmIn(serializers.Serializer):
    current_password = PasswordField()
    code = serializers.CharField(max_length=16)


class TotpConfirmOut(TokensOut):
    recovery_codes = serializers.ListField(child=serializers.CharField())


class EmailTokenIn(serializers.Serializer):
    token = serializers.CharField(max_length=512)


class MeOut(serializers.ModelSerializer):
    id = serializers.UUIDField(source="public_id")
    department = serializers.SlugRelatedField(slug_field="code", read_only=True)
    phone_verified = serializers.SerializerMethodField()
    email_verified = serializers.SerializerMethodField()
    two_step_login = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "phone",
            "full_name",
            "email",
            "preferred_language",
            "role",
            "department",
            "phone_verified",
            "email_verified",
            "two_step_login",
        ]

    def get_phone_verified(self, user) -> bool:
        return user.phone_verified_at is not None

    def get_email_verified(self, user) -> bool:
        return user.email_verified_at is not None

    def get_two_step_login(self, user) -> bool:
        return user.totp_enabled_at is not None


class MeIn(serializers.Serializer):
    full_name = TextField(max_length=120, required=False)
    preferred_language = serializers.ChoiceField(Language.choices, required=False)
    email = serializers.EmailField(
        max_length=254, required=False, allow_null=True, allow_blank=True
    )


class SessionOut(serializers.Serializer):
    id = serializers.UUIDField(source="family_id")
    trust_mode = serializers.CharField()
    user_agent = serializers.CharField()
    last_used_at = serializers.DateTimeField()
    expires_at = serializers.DateTimeField(source="absolute_expires_at")
    current = serializers.SerializerMethodField()

    def get_current(self, session) -> bool:
        return str(session.family_id) == self.context.get("sid")


class DemoSmsOut(serializers.Serializer):
    body = serializers.CharField()
    created_at = serializers.DateTimeField()
