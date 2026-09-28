"""Message texts, Bangla first.

Outbound SMS and email leave our infrastructure, so they carry only a code, a tracking number,
a status or an instruction: never names, descriptions or other personal detail (decision D1).
Keep SMS within one Unicode segment (70 characters) where possible.
"""

TEMPLATES = {
    "otp": {
        "bn": "আপনার যাচাই কোড {code}। ১০ মিনিট বৈধ। কাউকে জানাবেন না।",
        "en": "Your verification code is {code}. Valid 10 min. Do not share it.",
    },
    "register_attempt": {
        "bn": "আপনার নম্বরে নিবন্ধনের চেষ্টা হয়েছে। আপনি হলে লগইন করুন বা পাসওয়ার্ড রিসেট করুন।",
        "en": "Someone tried to register with your number. If this was you, log in or reset "
        "your password.",
    },
    "password_changed": {
        "bn": "আপনার পাসওয়ার্ড পরিবর্তন হয়েছে। আপনি না করলে হেল্প ডেস্কে যোগাযোগ করুন।",
        "en": "Your password was changed. If this was not you, contact the help desk.",
    },
    "session_reuse": {
        "bn": "সন্দেহজনক লগইন শনাক্ত হয়েছে; সব ডিভাইস থেকে লগআউট করা হয়েছে।",
        "en": "Suspicious sign-in detected; you were logged out on all devices.",
    },
    "verify_email": {
        "subject": {"bn": "ইমেইল যাচাই করুন", "en": "Verify your email"},
        "bn": "আপনার ইমেইল যাচাই করতে এই লিংকে যান (২৪ ঘণ্টা বৈধ):\n{link}\n\nকোড: {token}",
        "en": "To verify your email, open this link (valid 24 hours):\n{link}\n\nCode: {token}",
    },
}

# Payloads of these templates hold a secret; it is erased once the message has gone out.
SENSITIVE = {"otp", "verify_email"}


def render(template: str, language: str, payload: dict) -> tuple[str, str]:
    """(subject, body) in the recipient's language; subject is empty for SMS templates."""
    entry = TEMPLATES[template]
    lang = language if language in ("bn", "en") else "bn"
    subject = entry.get("subject", {}).get(lang, "")
    return subject, entry[lang].format(**payload)
