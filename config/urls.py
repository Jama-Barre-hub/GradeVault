from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import include, path
from django.utils.translation import gettext_lazy as _

from schools.dashboards import dashboard
from schools.report_cards import class_report_card, my_report_card
from schools.views import (
    class_ranking,
    mark_sheet,
    student_results,
    teacher_home,
)

admin.site.site_header = _("GradeVault administration")
admin.site.site_title = _("GradeVault")
admin.site.index_title = _("School records")

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
    path(
        "teacher/class/<int:classroom_id>/<int:term_id>/card/<int:enrollment_id>/",
        class_report_card,
        name="class_report_card",
    ),
    # Students
    path("results/", student_results, name="student_results"),
    path("results/<int:term_id>/card/", my_report_card, name="my_report_card"),
    path("i18n/", include("django.conf.urls.i18n")),
    path("admin/", admin.site.urls),
]
