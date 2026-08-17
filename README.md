# GradeVault

**A role-based school results management system for Somali schools.**

Teachers record marks. Grades, averages and class positions are computed
automatically. Students sign in with a unique username and see only their own
results. Every change to a grade is permanently audited.

> **Status:** In development — Milestone M0 (Foundations) complete.
> See [PROPOSAL.md](PROPOSAL.md) for the full plan and roadmap.

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

Not yet selected.

---

*Built by Jama Barre.*
