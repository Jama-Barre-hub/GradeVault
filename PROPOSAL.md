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
Institution                        Every table below hangs off this, so a
 └── AcademicYear                  second school can be added without a rewrite
      └── Term                     (2 per year; carries the published flag)

ClassRoom     belongs to one AcademicYear; name is free text (see §10.6)
Subject       e.g. "Mathematics"
GradingScale  owned by the institution  (see §10.3)
 └── GradeBand   letter, min %, max %, remark

User            (custom model, role: admin / teacher / student)
 ├── TeacherProfile
 └── StudentProfile  (unique student username + admission number)

Enrollment          Student ↔ ClassRoom
TeachingAssignment  Teacher ↔ Subject ↔ ClassRoom ↔ Term

Assessment   Term ↔ Subject ↔ ClassRoom, with max_marks (40, 60, …)
Score        Student ↔ Assessment ↔ marks   ← the central record

TermResult   Computed: per-subject total, percentage, grade, class position
AuditLog     Who changed which score, from what to what, when
```

Three deliberate choices worth defending in an interview:

- **`Score` is separate from `TermResult`.** Raw marks are facts entered by a
  human; results are derived values. Keeping them apart means the grading scale
  can change and every historical result can be recomputed correctly.
- **`Assessment.max_marks` rather than a percentage weight.** Marks are stored
  exactly as a teacher writes them in a mark book — 32 out of 40. No rounding
  error is introduced at entry time, and a school can define any number of
  assessments summing to any total.
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
parents · mobile applications · offline mode.

> **Correction, 18 August 2026.** Multi-school tenancy was previously listed
> here as out of scope. It is not: GradeVault is intended for schools across
> Somalia, so one deployment must serve many schools with each seeing only its
> own data. `Institution` is already a key on every table, which was the
> expensive half. What remains is enforcing it on every query and permission
> check, which lands in **M4** and is covered by tests that attempt to read
> another school's records and must fail.

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

## 10. Decisions

Resolved 18 August 2026, based on how Somali schools actually operate.

### 10.1 Academic calendar — two terms

A year has **two terms** (also called semesters), not three:

| Term | Runs |
|---|---|
| Term 1 | September → 15 January |
| Term 2 | early February → June |

Dates are stored per term and set by each school, since they shift year to year.

### 10.2 Marks are recorded out of their weight

A term's assessments carry **marks, not percentages**. The default structure is:

| Assessment | Out of |
|---|---|
| Mid-term (CAT) | 40 |
| Final | 60 |
| **Term total** | **100** |

A student scoring 32/40 and 51/60 has a term total of **83**.

The 40/60 split is a *default*, not a rule — some schools weight the mid-term at
30. Each assessment therefore stores its own `max_marks`, and the term total is
whatever they sum to.

This single design also covers schools that want more than two assessments.
A school may define Homework 10 + Mid-term 30 + Final 60, and nothing else in
the system needs to change. **Mid-term and final are the defaults, not a
constraint.**

### 10.3 Grading — percentage to letter grade

Percentage converts to a letter grade using a **grading scale owned by the
institution**. Somali schools each set their own boundaries, so this is
configurable data, never hardcoded. GPA points are out of scope for v1 but the
scale reserves a field for them.

Grades use **plus and minus bands**, twelve in total:

| | | | |
|---|---|---|---|
| A 90–100 | A- 85–89.99 | B+ 80–84.99 | B 75–79.99 |
| B- 70–74.99 | C+ 65–69.99 | C 60–64.99 | C- 55–59.99 |
| D+ 50–54.99 | D 45–49.99 | D- 40–44.99 | F 0–39.99 |

These are the **seeded default, not a standard**. Going from five bands to
twelve required no code change at all, which is the point of holding the scale
as data: a school that grades differently edits rows.

*Open: the pass mark is assumed to be 40. This needs confirming against Somali
practice.*

### 10.4 Class position — ranked within the class

Rank is computed **within a class**. That is the figure schools actually use.

Some schools also announce a single top student for the whole school. The
computation makes this derivable, but no interface for it is built in v1.

### 10.5 Publication — results are hidden until released

A term carries a published flag. Students see nothing until an administrator
publishes it. Teachers may enter and revise marks freely before that point.

Schools do not want marks visible the instant a teacher types them, and this is
one field that would otherwise touch every results query if added later.

### 10.6 Class levels are free text

Somali schools name levels differently:

- Primary: **Class 1 … Class 8**
- Secondary: **Form 1 … Form 4**, or **9 … 12**

There is no single national convention to encode, so a class level is **text
chosen by the school**. GradeVault stores "Class 5" or "Form 2" without
interpreting it.

### 10.7 Still open

**The name.** `GradeVault` is in use and the repository is published under it.
Domain and trademark availability have **not** been verified.

---

*This document is version-controlled and will be updated as decisions are made.*
