# GradeVault

[![CI](https://github.com/Jama-Barre-hub/GradeVault/actions/workflows/ci.yml/badge.svg)](https://github.com/Jama-Barre-hub/GradeVault/actions/workflows/ci.yml)
[![Licence: MIT](https://img.shields.io/badge/licence-MIT-blue.svg)](LICENSE)
[![Python 3.13](https://img.shields.io/badge/python-3.13-blue.svg)](https://www.python.org/)
[![Django 6.1](https://img.shields.io/badge/django-6.1-0C4B33.svg)](https://www.djangoproject.com/)

**A role-based school results management system for Somali schools.**

Teachers record marks. Grades, averages and class positions are computed
automatically. Students sign in with a unique username and see only their own
results. Every change to a grade is permanently audited.

> **Status:** In development. Data model, computation, web interface and
> multi-school isolation are complete and tested; not yet publicly deployed.
> See [PROPOSAL.md](PROPOSAL.md) for the full plan and roadmap.

| Done | |
|---|---|
| **Data model** | institutions, years, terms, classes, subjects, grading scales, students, teachers, enrolment, teaching assignments, assessments, marks |
| **Audit trail** | append-only; every grade change attributable and unremovable |
| **Computation** | subject totals, percentages, letter grades, term averages, class position |
| **Web interface** | portal layout, role dashboards, teacher mark entry, class rankings, student results |
| **Report cards** | printable, per student per term, with signature lines |
| **Isolation** | each school sees only its own data, enforced and tested |
| **Tests** | 225, including permission and tenancy tests that pass only when access is refused |

| Not done | |
|---|---|
| **Somali wording** | switcher works and the catalogue exists; strings await translation |
| **Public deployment** | configuration ready, not yet hosted |

---

## Why this exists

In many Somali primary and secondary schools, results live on paper registers or
in a spreadsheet on a single laptop. Files are lost, averages are computed by
hand and contain errors, students wait weeks for results, and there is no record
of who changed a mark. GradeVault addresses all four.

---

## Roles

| Role | Can do |
|---|---|
| **Administrator** | Set up academic years, terms, classes, subjects and grading scales; manage accounts; publish results |
| **Teacher** | Enter and amend marks for their assigned subjects and classes only |
| **Student** | View their own results, history and report card — nothing else |

---

## Tech stack

- **Django 6.1** (Python 3.13) — audited authentication, permissions and ORM
- **SQLite** in development, **PostgreSQL** in production
- **Django templates + HTML/CSS/JS** — server-rendered, so pages stay small on
  mobile connections, which is how most Somali users will access this
- **pytest + pytest-django** — permission rules are worthless unless proven
- **GitHub Actions** — tests run on every push

---

## Running locally

Requires **Python 3.13+** and **Git**. No Node.js needed.

```bash
git clone <repository-url>
cd GradeVault

# 1. Create and populate a virtual environment
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -r requirements.txt

# 2. Create your environment file
cp .env.example .env

# 3. Generate a secret key and paste it into .env as DJANGO_SECRET_KEY
python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"

# 4. Set up the database and run
python manage.py migrate
python manage.py runserver
```

Open <http://127.0.0.1:8000>.

### If you intend to commit

```bash
pip install -r requirements-dev.txt
pre-commit install
```

`pre-commit install` is what activates the checks in
`.pre-commit-config.yaml`. Without it, nothing runs on commit and secrets or
lint errors can reach the repository.

Useful commands:

```bash
pytest                      # run the tests
ruff check .                # find problems
ruff format .               # fix formatting
pre-commit run --all-files  # run every check manually
```

### Demo data

```bash
python manage.py seed_demo --reset
```

Builds a complete school — 12 teachers, 120 students, 6 classes, 8 subjects,
mid-term and final assessments, and marks — in a couple of seconds. It prints
sign-in details when it finishes.

**Every name, admission number and mark it produces is fictional.** No real
student record is ever used, in development, in tests, or in the public demo.
The command only touches its own demo institution, so a school entered by hand
is left alone.

---

## Project layout

```
GradeVault/
├── config/            Django project configuration
│   ├── settings.py    Reads all secrets from the environment
│   └── urls.py
├── templates/         Shared HTML templates
├── static/            CSS, JavaScript, images
├── locale/            Translations (English, Somali)
├── .env.example       Environment template — safe to commit
├── .env               Real secrets — git-ignored, never committed
└── manage.py
```

---

## Deployment

The service and its database are described in [render.yaml](render.yaml), so a
deployment is reviewable in the repository rather than a set of dashboard
settings someone once clicked.

```
build:  ./build.sh                → install, collectstatic, migrate
start:  gunicorn config.wsgi:application
```

### Configuration

Everything is read from the environment. Nothing is hardcoded.

| Variable | Purpose |
|---|---|
| `DJANGO_SECRET_KEY` | Required. The app refuses to start without it |
| `DJANGO_DEBUG` | Must be `False` in production. Defaults to `False` |
| `DJANGO_ALLOWED_HOSTS` | Comma-separated hostnames |
| `DATABASE_URL` | PostgreSQL. Falls back to SQLite when unset |
| `EMAIL_HOST` etc. | Optional. Without it, mail goes to the console |

### What `DEBUG=False` switches on

Production hardening is tied to `DEBUG` rather than a separate flag, so there is
no way to deploy with it accidentally left off:

HTTPS enforced · HSTS for one year including subdomains · session and CSRF
cookies restricted to HTTPS · session cookie hidden from JavaScript · framing
refused · content-type sniffing disabled · referrers kept same-origin · static
files hashed and compressed.

Sixteen tests load `settings.py` with `DEBUG` off and assert each of these,
because a security setting that only applies in production is the easiest kind
to get wrong — nothing in development exercises it.

---

## Continuous integration

Every push runs [the CI workflow](.github/workflows/ci.yml):

lint and format · Django template lint · **check for missing migrations** ·
the full test suite **against real PostgreSQL** · `collectstatic` with the
production storage backend · `check --deploy` with warnings treated as failures.

Tests run on PostgreSQL rather than SQLite because the two differ in ways that
matter — case sensitivity, constraint timing, ordering of nulls — so passing on
SQLite alone would not prove production is safe. This gives that parity without
installing a database server on a laptop.

---

## Language

The interface is offered in English and Somali. Every string is wrapped for
translation, the switcher works, and the choice is remembered in a cookie.

**Somali is selectable; most strings are not translated yet.** An untranslated
string falls back to English, which is deliberate — a half-blank interface would
be far worse than an English one.

### Translating

The catalogue lives at `locale/so/LC_MESSAGES/django.po` and holds every
translatable string in the project. Fill in the `msgstr` lines:

```po
msgid "My results"
msgstr "Natiijadayda"        # example only — wording to be confirmed
```

Then compile and restart:

```bash
python manage.py compilemessages -l so
```

After changing any English text in the code, re-extract before translating:

```bash
python manage.py makemessages -l so --ignore=.venv --ignore=staticfiles
```

Requires GNU gettext (`winget install --id mlocati.GetText -e` on Windows).

The compiled `.mo` is committed alongside the `.po`, because the deployment
target is not guaranteed to have gettext available at build time.

> **Wording is not guesswork.** On a report card, mistranslating *pass*, *fail*
> or *position* is not cosmetic — a parent reads it and believes it. The Somali
> should be written by a Somali speaker, not inferred.

---

## Data protection

This system holds educational records belonging to **minors**. Three rules apply
without exception:

1. **Only synthetic data** is used in development, tests, screenshots and the
   public demo. No real student's name, admission number or grade ever enters
   this repository.
2. **No hand-rolled security.** Password hashing, sessions and CSRF protection
   use Django's audited implementations.
3. **No secrets in Git.** Configuration is read from environment variables.
   `settings.py` raises an error and refuses to start if `DJANGO_SECRET_KEY` is
   missing, rather than falling back to an insecure default.

---

## Licence

[MIT](LICENSE) — free to use, modify and distribute, provided the copyright
notice is retained.

---

*Built by Jama Barre.*
