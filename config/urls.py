from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path
from django.utils.translation import gettext_lazy as _

from accounts.passwords import change_my_password, reset_password
from config.health import healthz
from schools.dashboards import dashboard, home
from schools.people import (
    move_student,
    people_overview,
    people_students,
    people_teachers,
    people_teaching,
)
from schools.publishing import term_publication
from schools.report_cards import class_report_card, my_report_card
from schools.setup import (
    setup_classes,
    setup_overview,
    setup_scale,
    setup_scales,
    setup_subjects,
    setup_terms,
    setup_years,
)
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
    path("", home, name="home"),
    path("home/", dashboard, name="dashboard"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="registration/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("password/", change_my_password, name="change_my_password"),
    path(
        "manage/people/<int:user_id>/reset-password/",
        reset_password,
        name="reset_password",
    ),
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
    # Administrators
    # Under manage/ rather than admin/, which belongs to the Django admin.
    path("manage/results/", term_publication, name="term_publication"),
    path("manage/people/", people_overview, name="people_overview"),
    path("manage/people/teachers/", people_teachers, name="people_teachers"),
    path("manage/people/students/", people_students, name="people_students"),
    path(
        "manage/people/students/<int:student_id>/move/",
        move_student,
        name="move_student",
    ),
    path("manage/people/teaching/", people_teaching, name="people_teaching"),
    path("manage/setup/", setup_overview, name="setup_overview"),
    path("manage/setup/years/", setup_years, name="setup_years"),
    path("manage/setup/years/<int:year_id>/", setup_terms, name="setup_terms"),
    path("manage/setup/classes/", setup_classes, name="setup_classes"),
    path("manage/setup/subjects/", setup_subjects, name="setup_subjects"),
    path("manage/setup/grading/", setup_scales, name="setup_scales"),
    path("manage/setup/grading/<int:scale_id>/", setup_scale, name="setup_scale"),
    # Students
    path("results/", student_results, name="student_results"),
    path("results/<int:term_id>/card/", my_report_card, name="my_report_card"),
    # Polled by the hosting platform, not by a person.
    path("healthz", healthz, name="healthz"),
    path("admin/", admin.site.urls),
]
