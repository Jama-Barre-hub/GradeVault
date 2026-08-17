# GradeVault — Project Proposal

> **Status:** Draft v0.1 · **Author:** Jama Barre · **Date:** 17 August 2026
> **Working name:** GradeVault *(not yet final — see §10)*

---

## 1. Summary

**GradeVault is a web-based academic results management system for schools.**

It replaces paper mark books and scattered spreadsheets with a single secure
system where teachers record marks, the system computes grades and rankings
automatically, and each student signs in with a unique username to view only
their own results.

One sentence for a CV or LinkedIn post:

> A role-based school results platform where teachers record marks, grades and
> class positions are computed automatically, and every change to a grade is
> permanently audited.

---

## 2. The problem

In a great many primary and secondary schools, student results live on paper
registers or in isolated Excel files on one teacher's laptop. That causes real,
repeated harm:

| Problem | Consequence |
|---|---|
| Records held on paper or a single laptop | A lost file or damaged register destroys a term's records permanently |
| Averages, totals and positions computed by hand | Arithmetic errors change a student's reported standing |
| Results distributed physically | Students and parents wait days or weeks to learn outcomes |
| No linked history between terms | Nobody can see whether a struggling student is improving |
| No record of who changed a mark | Grade tampering is undetectable and unprovable |
| Every term rebuilt from scratch | Teachers repeat the same setup work three times a year |

The last two matter more than they first appear. A results system's core duty is
**trustworthiness** — a school must be able to prove a grade is the grade the
teacher actually entered.

---

## 3. The solution

A web application with four clearly separated responsibilities:

**The administrator** sets up the institution once — academic years, terms,
classes, subjects, the grading scale — then manages teacher and student accounts.

**Teachers** see only the classes and subjects they are assigned to, and record
marks against defined assessments. Every entry is validated and every change is
logged with author and timestamp.

**The system** computes subject grades, weighted term averages and class
positions automatically from a grading scale the school configures itself. No
manual arithmetic, no spreadsheet formulas to break.

**Students** sign in with a unique username and see their own results only —
current term, full history across terms and years, and a printable report card.

---

## 4. Users and permissions

| Role | Can do | Cannot do |
|---|---|---|
| **Administrator** | Manage institution setup, accounts, classes, subjects, grading scale; view all results; publish results | Silently edit a grade — all changes are audited |
| **Teacher** | Enter and amend marks for **their assigned subjects and classes only**; view their own class analytics | See or edit marks for subjects they do not teach |
| **Student** | View **their own** results, history and report card | See any other student's data, or edit anything |
| **Parent** *(Phase 2)* | View a linked child's results | See unlinked students; edit anything |

This permission matrix is the heart of the project. Enforcing it correctly — and
**proving it with automated tests** — is what raises this above a typical
portfolio CRUD app.

---

## 5. Data model (initial design)

```
Institution
 └── AcademicYear
      └── Term                    (Term 1 / 2 / 3, with start + end dates)

ClassRoom          (e.g. "Form 4A")     Subject      (e.g. "Mathematics")
GradingScale       (A/B/C/D/F boundaries, configurable per institution)

User               (custom model, one of: admin / teacher / student)
 ├── TeacherProfile
 └── StudentProfile (unique student username + admission number)

Enrollment          Student  ↔ ClassRoom ↔ AcademicYear
TeachingAssignment  Teacher  ↔ Subject   ↔ ClassRoom ↔ Term

Assessment          A gradeable item (CAT 1, Midterm, Final) with a weight
Score               Student ↔ Assessment ↔ mark  ← the central record

TermResult          Computed: per-subject grade, average, class position
AuditLog            Who changed which score, from what to what, when
```

Two deliberate choices worth defending in an interview:

- **`Score` is separate from `TermResult`.** Raw marks are facts entered by a
  human; results are derived values. Keeping them apart means the grading scale
  can change and every historical result can be recomputed correctly.
- **`AuditLog` is append-only.** Nothing in the application is permitted to
  delete or amend an audit row.

---

## 6. Scope

### In scope for v1

1. Secure authentication with role-based access control
2. Institution setup: years, terms, classes, subjects, grading scale
3. Account management, with auto-generated unique student usernames
4. Teacher mark entry, with validation and full audit logging
5. Automatic computation of grades, weighted averages and class positions
6. Student portal: current results plus history across terms
7. Printable / PDF report cards
8. Responsive interface with light and dark themes
9. Automated test suite, with permission enforcement explicitly covered
10. Live public deployment with read-only demo accounts for each role

### Explicitly out of scope for v1

Attendance tracking · fee management · timetabling · messaging between staff and
parents · mobile applications · multi-school tenancy · offline mode.

*Each of these is a reasonable Phase 3 addition. Naming them here is deliberate —
knowing what you are not building is part of the proposal.*

---

## 7. Technical approach

| Layer | Choice | Why |
|---|---|---|
| Backend | **Django (Python)** | Python 3.13 already installed. Ships with audited authentication, password hashing, permissions, CSRF and SQL-injection protection — none of which should ever be hand-written for a system holding minors' records |
| Database | **SQLite → PostgreSQL** | SQLite while developing, PostgreSQL in production. Django's ORM makes this a configuration change |
| Frontend | **Django templates + HTML/CSS/JS** | Builds directly on skills already demonstrated in Smart Student Planner, with no React learning curve competing for attention |
| Admin tooling | **Django admin** | A full staff back-office for free — a genuine advantage for a system school staff must operate |
| Testing | **pytest + pytest-django** | Permission rules are worthless unless proven |
| CI | **GitHub Actions** | Tests run on every push |
| Hosting | **Render** (free tier) | Free PostgreSQL and web hosting, straightforward Django deployment |

### Data protection commitments

This system holds educational records belonging to **minors**. Three rules apply
throughout development, without exception:

1. **Only synthetic data.** Every name, admission number and grade used in
   development, testing, screenshots and the public demo is fabricated. No real
   student record ever enters the repository or the demo deployment.
2. **No hand-rolled security.** Password hashing, sessions and CSRF protection
   use the framework's audited implementations.
3. **No secrets in Git.** Keys and database credentials live in environment
   variables from the very first commit, never in tracked files.

---

## 8. Roadmap

Nine milestones. Each ends in something demonstrable, and each is reviewed before
the next begins.

| # | Milestone | What exists at the end | Est. |
|---|---|---|---|
| **M0** | **Foundations** | Git repository, virtual environment, Django project running locally, CI pipeline green, README and this proposal committed | 1–2 days |
| **M1** | **Data model** | Every model from §5 migrated, visible and editable in Django admin, with a seed script generating a fake school | 4–6 days |
| **M2** | **Authentication & roles** | Custom user model; admin, teacher and student can log in and each sees a different dashboard; unauthorised access blocked and **tested** | 4–6 days |
| **M3** | **Institution setup** | Admin can create years, terms, classes, subjects and grading scales, and enrol students through the interface | 5–7 days |
| **M4** | **Mark entry** | Teachers enter marks for their assigned subjects only, with validation; every change written to the audit log | 5–7 days |
| **M5** | **Computation engine** | Grades, weighted averages and class positions computed automatically; covered by unit tests including tie-handling and edge cases | 4–6 days |
| **M6** | **Student portal** | Students sign in and view their own current and historical results, with a progress view | 4–6 days |
| **M7** | **Report cards** | Printable, downloadable PDF report card per student per term | 3–5 days |
| **M8** | **Hardening & polish** | Responsive UI, light/dark themes, accessibility pass, security review, full permission test suite | 5–7 days |
| **M9** | **Launch** | Deployed publicly on PostgreSQL, demo accounts for all three roles, screenshots, architecture diagram, documented README | 3–4 days |

**Realistic total: 10–14 weeks part-time** alongside coursework.

The order is deliberate — permissions (M2) come *before* features, because
retrofitting access control onto an existing application is how real security
breaches happen.

---

## 9. Definition of success

This project succeeds if all of the following are true:

- [ ] A stranger can open a live URL, log in as a demo teacher, enter a mark, then log in as a demo student and see the resulting grade
- [ ] An automated test proves a student cannot retrieve another student's results
- [ ] An automated test proves a teacher cannot edit a subject they do not teach
- [ ] Every grade change is attributable to a named user with a timestamp
- [ ] Report cards export as PDF and print correctly
- [ ] The test suite passes in CI on every push
- [ ] The README explains the architecture well enough for another developer to run it locally in under five minutes
- [ ] No real student's personal data appears anywhere in the repository or demo

The first three matter most. **A working demo link with credentials that a
recruiter can actually use** is worth more than any amount of code.

---

## 10. Open decisions

Before M0 begins:

1. **Final name.** `GradeVault` is the working title. Alternatives considered:
   Marksheet, ResultDesk, Attainly, MeritBook. Domain and trademark availability
   has **not** yet been verified.
2. **Assessment structure.** Does a term hold a fixed set of assessments
   (CAT 1, CAT 2, Final) or should teachers define their own per subject?
3. **Grading scale.** Percentage-based letter grades, GPA points, or both?
4. **Class position.** Ranked within a class only, or across the whole year group?
5. **Publication control.** Should results stay hidden from students until an
   administrator explicitly publishes the term?

*Question 5 is more consequential than it looks — schools rarely want marks
visible the instant a teacher types them.*

---

*This document is version-controlled and will be updated as decisions are made.*
