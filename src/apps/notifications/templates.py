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
    # Requests: the tracking number and what happened, nothing else.
    "request_submitted": {
        "bn": "আবেদন জমা হয়েছে। ট্র্যাকিং নম্বর {tracking_no}।",
        "en": "Request received. Tracking number {tracking_no}.",
    },
    "request_started": {
        "bn": "আবেদন {tracking_no}: কাজ শুরু হয়েছে।",
        "en": "Request {tracking_no}: work has started.",
    },
    "request_info_needed": {
        "bn": "আবেদন {tracking_no}: আপনার কাছে তথ্য চাওয়া হয়েছে। লগইন করে উত্তর দিন।",
        "en": "Request {tracking_no}: information is needed from you. Log in to reply.",
    },
    "request_resolved": {
        "bn": "আবেদন {tracking_no}: নিষ্পত্তি হয়েছে। বিস্তারিত দেখতে লগইন করুন।",
        "en": "Request {tracking_no}: resolved. Log in for details.",
    },
    "request_rejected": {
        "bn": "আবেদন {tracking_no}: গ্রহণ করা হয়নি। কারণ দেখতে লগইন করুন।",
        "en": "Request {tracking_no}: not accepted. Log in to see why.",
    },
    "request_assigned": {
        "bn": "আবেদন {tracking_no} আপনাকে দেওয়া হয়েছে।",
        "en": "Request {tracking_no} has been assigned to you.",
    },
    "request_comment": {
        "bn": "আবেদন {tracking_no}: অফিস থেকে নতুন বার্তা। দেখতে লগইন করুন।",
        "en": "Request {tracking_no}: a new message from the office. Log in to read it.",
    },
    "request_withdrawn": {
        "bn": "আবেদন {tracking_no} প্রত্যাহার করা হয়েছে।",
        "en": "Request {tracking_no} was withdrawn.",
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
