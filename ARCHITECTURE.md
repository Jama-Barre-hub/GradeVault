# Architecture

How GradeVault is put together, and why. [README.md](README.md) covers running
it; [PROPOSAL.md](PROPOSAL.md) covers what it is for and what was decided.

This document is aimed at someone reading the code for the first time — a
reviewer, a contributor, or the author in six months.

---

## The one-sentence version

A server-rendered Django application in which **raw marks are facts** and
**everything else is derived**, permissions live in exactly one module, and no
query is allowed to leave the signed-in user's own school.

---

## Three apps, three responsibilities

| App | Owns | Key files |
|---|---|---|
| `accounts` | Who someone is and what they may do | `models.py`, `permissions.py`, `demo.py` |
| `schools` | The academic domain and every page | `models.py`, `results.py`, `views.py`, `publishing.py`, `setup.py` |
| `audit` | The permanent record of grade changes | `models.py` |

The split is by **responsibility**, not by layer. There is no `services/` or
`repositories/` directory, because at this size those add indirection without
adding safety. What does add safety — a single home for permission rules, a
single home for the tenancy filter — is done rigorously.

---

## Four decisions worth defending

### 1. `Score` is separate from `TermResult`

A `Score` is what a teacher typed: 32 out of 40. A result — percentage, letter
grade, class position — is **computed on read** by `schools/results.py`, never
stored.

This costs a little query work on every results page. It buys the ability for a
school to change its grading scale and have every historical result recompute
correctly. Stored grades would freeze a school's past into whatever scale
happened to be configured on the day the marks were entered, and nothing would
reveal the inconsistency.

### 2. Marks are stored out of their own total, not as percentages

`Assessment.max_marks` holds 40 or 60, and marks are recorded against it
exactly as they appear in a paper mark book. Converting to a percentage at
entry time would introduce rounding error into the stored record — the one
value that must stay exactly what the teacher wrote.

It also means a school defining Homework 10 + Mid-term 30 + Final 60 needs no
code change. The 40/60 split is seeded data, not a rule.

### 3. The grading scale is data, not code

`GradingScale` and `GradeBand` are rows owned by an `Institution`. Somali
schools set their own boundaries, so hardcoding them would make the software
usable by one school and wrong for the next.

Moving from five bands to eleven — adding plus and minus grades — required no
code change at all. That is the test of whether this decision was real.

### 4. The audit log is append-only

Nothing in the application deletes or amends an `AuditLog` row. A results
system's core duty is proving that a grade is the grade the teacher entered,
and a log that can be edited proves nothing.

---

## Where the safety properties live

Each of these is enforced in **one** place. A rule copied into ten views is a
rule that will be wrong in one of them, and the wrong one is the one nobody
notices until a student sees another student's marks.

| Property | Enforced in | Proven by |
|---|---|---|
| A role cannot open another role's pages | `accounts/permissions.py` → `role_required` | `tests/test_views_permissions.py` |
| A teacher cannot mark a subject they do not teach | `accounts/permissions.py` → `require_teaches`, which asks `TeacherProfile.teaches()` | `tests/test_marks.py` |
| A student sees only their own results | `schools/views.py` → derived from the session, never from a URL parameter | `tests/test_views_permissions.py` |
| One school cannot read another's data | `schools/admin_scoping.py` → `InstitutionScopedAdmin` | `tests/test_tenancy.py` |
| Results stay hidden until released | `Term.is_published`, checked on every student-facing query | `tests/test_results.py` |
| Every grade change is attributable | `audit/models.py` | `tests/test_audit.py` |
| The public demo cannot be damaged | `accounts/demo.py` → `DemoReadOnlyMiddleware` | `tests/test_demo_mode.py` |
| Publication cannot happen unrecorded | `schools/publishing.py`, and `is_published` readonly in the admin | `tests/test_publishing.py` |
| One school cannot set up another's structure | `schools/setup.py` → `institution_of`, and every lookup re-filtered | `tests/test_setup.py` |
| A term picker cannot reveal an unpublished term | `schools/views.py` → the id is matched inside the published set, never fetched | `tests/test_student_portal.py` |
| An account's role cannot be posted | `schools/people.py` → role is set by the view, never read from the request | `tests/test_people_screens.py` |
| A password reset only ever points downwards | `accounts/passwords.py` → scoped by institution *and* restricted to teacher/student roles | `tests/test_passwords.py` |
| A PDF cannot be downloaded where the page is refused | `schools/report_cards.py` → `?format=pdf` is served by the same view, after the same checks, rather than from a URL of its own | `tests/test_report_pdf.py` |

Two habits make these hold in practice:

**Permission before query.** `mark_sheet` checks access before reading
anything, so a teacher cannot learn even the size of a class they do not teach
by guessing an id.

**Missing means nothing, not everything.** An account with no institution sees
an empty list, never the whole database. Failing closed is the difference
between a bug and a breach.

---

## Multi-tenancy

`Institution` is a key on every table. One deployment serves many schools, and
each reaches `Institution` by a different path — a `Score` through its
enrolment, class and year; a `Subject` directly.

`InstitutionScopedAdmin` handles this by having each admin class declare its own
lookup while the filtering itself is written once. It filters **dropdowns as
well as lists**: restricting the list while leaving foreign-key pickers open
would still let one school attach its records to another's classes, and leak
their names in the process.

A superuser has no institution and is treated as the person operating the
deployment rather than a member of any school, so they see everything. This is
why the demo administrator is deliberately **not** a superuser — it should see
what a real head teacher sees.

---

## The request path

Middleware order in `config/settings.py` is load-bearing:

- **WhiteNoise** must sit directly after `SecurityMiddleware`.
- **LocaleMiddleware** must sit after sessions and before `CommonMiddleware`.
- **DemoReadOnlyMiddleware** must sit after `MessageMiddleware`, since it
  explains a refusal through a message.
- **AxesMiddleware** must be last, because it wraps authentication.

`DemoReadOnlyMiddleware` uses `process_view` rather than `__call__` because only
after URL resolution can it tell `login` and `logout` apart from every other
`POST` — and it matches on **URL name**, not path, so a renamed or newly added
URL cannot silently slip past.

---

## Frontend

Server-rendered Django templates. One hand-written stylesheet, no framework, no
web fonts, no build step, and a single inline `window.print()` that the page
works without.

This is a deliberate constraint, not a limitation accepted reluctantly. Most
users arrive on a phone over a mobile connection and pay for every kilobyte. A
React bundle would cost them money to load a table of eight numbers.

Navigation is a sidebar on a wide screen and a scrolling strip under the header
on a narrow one — no drawer and no toggle, so there is nothing that can fail to
open and one less tap to reach anything.

---

## Testing

`pytest` + `pytest-django`, 379 tests, run in CI against **real PostgreSQL**.
SQLite and PostgreSQL differ in case sensitivity, constraint timing and null
ordering, so passing on SQLite alone would not prove production is safe.

Three conventions:

**Permission tests pass only when access is refused.** A test that asserts a
403 fails loudly the day someone widens a queryset.

**The negative case is tested too.** `test_demo_mode.py` proves writes are
blocked when `DEMO_MODE` is on *and* that they still save when it is off. The
second is the one that would otherwise break a real school.

**Tests hash passwords cheaply.** `conftest.py` swaps in MD5 for the suite only.
Production PBKDF2 took the suite from 4 seconds to over 9 minutes, and a slow
suite stops being run — which quietly removes the protection it exists to give.

---

## What is deliberately not here

Attendance, fees, timetabling, parent messaging, a mobile app, offline mode, and
a REST API. Each is a reasonable later addition. Naming them is the point:
knowing what you are not building is part of the design.

The nearest gap worth closing is the rest of the **administrator interface**.
Publishing and academic setup have moved into the portal. What remains in the
Django admin is **accounts and enrolment**: creating teachers and students,
enrolling them into classes, and assigning who teaches what. That is the
largest and most security-sensitive slice, because it creates the accounts
every other permission rule is written about.

Setup screens answer a question the admin cannot: `schools/setup.py`'s
`readiness()` checks the pieces *against each other* rather than listing them
separately. A year with no terms, a class nobody teaches, a grading scale with
a gap — each looks fine on its own screen and each stops results working.
