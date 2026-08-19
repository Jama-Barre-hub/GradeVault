from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from schools.dashboards import dashboard
from schools.views import (
    class_ranking,
    mark_sheet,
    student_results,
    teacher_home,
)

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    # Teachers
    path("teacher/", teacher_home, name="teacher_home"),
    path(
        "teacher/marks/<int:classroom_id>/<int:subject_id>/<int:term_id>/",
        mark_sheet,
        name="mark_sheet",
    ),
    path(
        "teacher/class/<int:classroom_id>/<int:term_id>/",
        class_ranking,
        name="class_ranking",
    ),
    # Students
    path("results/", student_results, name="student_results"),
    path("admin/", admin.site.urls),
]
