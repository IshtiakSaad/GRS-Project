from django.urls import path

from . import views

urlpatterns = [
    path("requests/<uuid:request_id>/comments", views.CommentsView.as_view()),
    path("requests/<uuid:request_id>/attachments", views.AttachmentsView.as_view()),
    path("attachments/<uuid:attachment_id>", views.AttachmentView.as_view()),
    path("attachments/<uuid:attachment_id>/confirm", views.AttachmentConfirmView.as_view()),
    path("attachments/<uuid:attachment_id>/download", views.AttachmentDownloadView.as_view()),
]
