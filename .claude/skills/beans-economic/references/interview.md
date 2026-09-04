# The interview

Six lines. Two can be estimated from the ledger; four exist only in the user's
head. This is the agenda, in the order that works — the two ledger-backed lines
first, because seeing their own run-rate calibrates every answer that follows.

Nothing here is a form. If an answer is "I don't know", that is a legitimate
answer and it maps to `Mode: none` **with the reason recorded** — never to a
plausible-looking default.

---

## Before you start

Open with the two numbers from preflight that anchor everything:

> Your ledger says you take home about **$6,300/month** and spend about
> **$3,150/month**, based on the last 12 months. Accounting net worth is
> **$63,142**. Everything else we're about to do is assumptions on top of that.

If the run-rate is drifting (preflight says so), name it now, because it
changes what "use the run-rate" means:

> Your grocery spend rose about 40% across that window, so a flat annuity off
> today's number will drift too. Do you want the current level, or something
> closer to where it's heading?

---

## 1. Human capital — future income

**Ask:** *When do you expect to stop working, and does your income change
before then?*

| Answer | Mode | Shape |
|---|---|---|
| "Same as now until I retire in 2046" | `stream` | two segments: today's amount, then `0` at the retirement date |
| "About what I earn now, I haven't thought about the end date" | `auto` | with `work_years` — but push once, see below |
| "It steps up when I make partner in 2029" | `stream` | three segments |
| "I'm already retired" | `none` | and say so |

**The follow-up that matters:** an `auto` human capital runs income flat to the
`work_years` horizon and then stops abruptly. A `stream` with an explicit `0`
segment at the retirement date says the same thing more honestly and makes the
date visible — which matters, because it is usually the second-largest driver
in the whole model. Prefer `stream` whenever the user has a date at all.

**Growth:** ask for a *real* wage growth number, not a nominal one, and use the
same basis for inflation. Mixing them is the most common modelling error here.

---

## 2. Future consumption — spending

**Ask:** *Does your spending change when you stop working?*

| Answer | Mode | Shape |
|---|---|---|
| "Roughly what I spend now" | `auto` | fine for a first pass |
| "About 70% of now, after the mortgage ends" | `stream` | two segments |
| "More at first, then less" | `stream` | three segments |

**Push back once on `auto` over a long horizon.** `auto` with `live_years: 40`
models someone whose spending never changes for forty years — no mortgage
ending, no children leaving, no care costs. It is a reasonable *first* pass and
a poor final answer. Say that.

**This is usually the largest single line on the statement.** On the worked
example it is $1.24m against $1.30m of human capital. Treat it with the same
care as income.

---

## 3. Pension / benefits

**Ask:** *Is there a pension, annuity or state benefit — from when, how much,
and is it indexed?*

| Answer | Mode | Shape |
|---|---|---|
| "$2,400/month from 2046, index-linked" | `stream` | one segment at the start date, growth = inflation |
| "State pension, I don't know the amount" | `none` | and say it is excluded |
| "A lump sum at 65" | `stream` | a `flows` table (Date/Amount), not a schedule |

**Indexed or not is a real question.** An unindexed pension over a 40-year
horizon loses most of its value; growth `0%` vs growth `2%` on this line is
often worth six figures. Ask rather than assume.

---

## 4. Expected inheritance

**Ask:** *Is there an inheritance you would genuinely plan around?*

This one needs the most care, and the honest default is `none`. Include it only
if the user would actually change a decision because of it. Two reasons:

- It is other people's money and other people's timing.
- Including it makes the plan look robust in exactly the scenario where it may
  not be.

If included: `stream` with a `flows` table — a dated lump sum, not a monthly
schedule. If the user is unsure of the date, model it later rather than
earlier, and say that you did.

---

## 5. Bequests

**Ask:** *Do you intend to leave a specific amount?*

Most answers are "no" → `none`. If yes, it is a liability: a `scalar` monthly
provision, or a `flows` lump sum at the end of the horizon. Note that a bequest
and a long `live_years` are partly the same statement, so do not let the user
double-count "leave something behind" and "plan to age 100".

---

## 6. Other obligations

**Ask:** *Anything else large and in the future — care costs for a parent,
tuition, a settlement, a known repair?*

The stock `beans economic create-template` has **no section for this line at
all**; `build_config.py` writes one. It is worth asking about explicitly for
that reason — it is the line most likely never to have been considered.

`scalar` for a recurring commitment with an end (`years`), `flows` for dated
one-offs.

---

## Closing the interview

Read back the excluded lines before building anything:

> To be clear about what we're *not* modelling: no bequest, and no other
> obligations. Both are treated as zero. Is that right?

That sentence is the guardrail. An excluded pension is a claim that there is no
pension, and it is far easier to correct now than after the number exists.

## Settings

Three that need a decision, not a default:

- **`discount_rate`** — read `sensitivity.md` before advising on this one. It
  discounts *both* sides, and the answer is not monotonic in it.
- **`live_years`** — a planning horizon, not a life expectancy. Longer is more
  conservative for consumption and less conservative for a pension.
- **`inflation`** vs **`income_growth`** — keep both real or both nominal.
  Inflation is usually the single largest driver in the whole model.
