"""Message texts, Bangla first.

Outbound SMS and email leave our infrastructure, so they carry only a code, a tracking number,
a status or an instruction: never names, descriptions or other personal detail (decision 12).
Keep SMS within one Unicode segment (70 characters) where possible.
"""

from html import escape

TEMPLATES = {
    "otp": {
        "bn": "আপনার যাচাই কোড {code}। ১০ মিনিট বৈধ। কাউকে জানাবেন না।",
        "en": "Your verification code is {code}. Valid 10 min. Do not share it.",
    },
    # Staff never choose a password through anyone else: the link opens a page to set one.
    # Longer than one segment, but a new officer has nothing else to go on.
    "staff_welcome": {
        "bn": "GRS: আপনাকে কর্মকর্তা হিসেবে যুক্ত করা হয়েছে। পাসওয়ার্ড ঠিক করুন: {link} কোড {code}। "
        "২৪ ঘণ্টা বৈধ। কাউকে জানাবেন না।",
        "en": "GRS: you were added as an officer. Set your password: {link} Code {code}. "
        "Valid 24 h. Do not share it.",
    },
    "staff_reset": {
        "bn": "GRS: প্রশাসক আপনার পাসওয়ার্ড রিসেট করেছেন। নতুন পাসওয়ার্ড দিন: {link} কোড {code}। "
        "২৪ ঘণ্টা বৈধ। কাউকে জানাবেন না।",
        "en": "GRS: an administrator reset your password. Set a new one: {link} Code {code}. "
        "Valid 24 h. Do not share it.",
    },
    "register_attempt": {
        "bn": "আপনার নম্বরে নিবন্ধনের চেষ্টা হয়েছে। আপনি হলে লগইন করুন বা পাসওয়ার্ড রিসেট করুন।",
        "en": "A new account was attempted on your number. You already have one: log in, or "
        "reset your password.",
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
        # No raw token in the text: the link carries it, and a long random string is what spam
        # filters look for.
        "bn": (
            "কেউ (সম্ভবত আপনি) একটি GRS অ্যাকাউন্টে এই ইমেইল ঠিকানা যোগ করেছেন। নিশ্চিত করতে "
            "২৪ ঘণ্টার মধ্যে এই লিংকে যান:\n{link}\n\n"
            "এটি আপনি না করে থাকলে এই ইমেইল উপেক্ষা করুন: লিংক না খুললে কিছুই বদলাবে না।"
        ),
        "en": (
            "Someone (most likely you) added this address to a GRS account. To confirm it, open "
            "this link within 24 hours:\n{link}\n\n"
            "If this wasn't you, ignore this email: nothing changes unless the link is opened."
        ),
        "button": {"bn": "ইমেইল নিশ্চিত করুন", "en": "Confirm email"},
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
    "request_overdue": {
        "bn": "আবেদন {tracking_no}: সময়সীমা পেরিয়ে গেছে। দ্রুত ব্যবস্থা নিন।",
        "en": "Request {tracking_no} is past its deadline. Please act on it now.",
    },
    "request_reopened": {
        "bn": "আবেদন {tracking_no}: পর্যালোচনার পর আবার খোলা হয়েছে।",
        "en": "Request {tracking_no} was reviewed and reopened.",
    },
    "request_withdrawn": {
        "bn": "আবেদন {tracking_no} প্রত্যাহার করা হয়েছে।",
        "en": "Request {tracking_no} was withdrawn.",
    },
}

SUBJECT = {"bn": "আবেদন {tracking_no}", "en": "Request {tracking_no}"}

# Payloads of these templates hold a secret; it is erased once the message has gone out.
SENSITIVE = {"otp", "staff_welcome", "staff_reset", "verify_email"}


def render_html(template: str, language: str, payload: dict) -> str | None:
    """An HTML part for emails that carry a link to press, beside the text part. Mail clients
    and spam filters both expect the pair from a real sender; a bare text email with a long
    link looks like the other kind."""
    entry = TEMPLATES[template]
    if "button" not in entry or "link" not in payload:
        return None
    lang = language if language in ("bn", "en") else "bn"
    text = entry[lang].format(**payload).split("\n")
    link = escape(payload["link"])
    return (
        f'<!doctype html><html lang="{lang}"><body style="margin:0;padding:24px;'
        'font-family:Arial,sans-serif;font-size:15px;line-height:1.5;color:#1e293b">'
        f"<p>{escape(text[0])}</p>"
        f'<p><a href="{link}" style="display:inline-block;padding:10px 18px;border-radius:6px;'
        f'background:#0f766e;color:#ffffff;text-decoration:none">{escape(entry["button"][lang])}'
        "</a></p>"
        f'<p style="font-size:13px;color:#475569">{escape(text[-1])}</p>'
        "</body></html>"
    )


def render(template: str, language: str, payload: dict) -> tuple[str, str]:
    """(subject, body) in the recipient's language. Request updates sent by email use the
    tracking number as the subject."""
    entry = TEMPLATES[template]
    lang = language if language in ("bn", "en") else "bn"
    subject = entry.get("subject", {}).get(lang, "")
    if not subject and "tracking_no" in payload:
        subject = SUBJECT[lang].format(**payload)
    return subject, entry[lang].format(**payload)
