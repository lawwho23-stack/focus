# Focus Bubble — an Android overlay that watches what you actually do

**Status:** designed, not built. Phase 5 of the Focus plan.
**Preserved from:** `~/.claude/plans/hey-i-want-to-kind-bee.md`, which was rewritten for the
Phase 3 cloud/mobile plan on 2026-09-08.
**Prerequisite:** Phase 3 Stage A (Tailscale + launchd) — see the current plan file.

> This design was revised after an adversarial review that found 8 factual errors in the first
> draft. Corrections are marked **[was wrong]** so the reasoning stays visible.

## What it is

A bubble that floats over every other app, runs in the background, and — once permission is
granted — knows which apps are in use. It shows commitment progress as a percent and interrupts
when an app has nothing to do with what was committed to.

## Locked decisions

| Question | Answer |
|---|---|
| Phone | **Android.** On iPhone this is impossible — no overlay, no foreground-app read. |
| Brand | **Oppo / Vivo / Realme / OnePlus** — the hard case. See § Step 0. |
| Progress percent | finished ÷ committed, kills beside it — **one open question, see § The percent** |
| Off-task warning | **Distraction list** — tag the bad apps once |
| What the warning does | **Full-screen interrupt, must be read for 5 seconds** |
| When | After `focus/` survives 7 real days |

## The honest platform facts

> **Re-check on build day.** Android's background rules tighten every release.

| Capability | Mechanism | Permission |
|---|---|---|
| A bubble over other apps | `WindowManager` overlay | `SYSTEM_ALERT_WINDOW` |
| Runs in the background | Foreground Service | `FOREGROUND_SERVICE_SPECIAL_USE` |
| Knows what apps are used | `UsageStatsManager.queryEvents()` | `PACKAGE_USAGE_STATS` |
| Reads app names and icons | `PackageManager` | **`QUERY_ALL_PACKAGES`** |
| Survives a reboot | Boot receiver | `RECEIVE_BOOT_COMPLETED` |
| Overnight upload not deferred | Battery exemption | `REQUEST_IGNORE_BATTERY_OPTIMIZATIONS` |

`SYSTEM_ALERT_WINDOW` and `PACKAGE_USAGE_STATS` are **special access** — the app can only open the
Settings screen; the user toggles by hand. The battery one *is* a normal dialog.

**[was wrong] The battery exemption does not keep the service alive.** Doze does not kill foreground
services — it defers alarms, jobs and network. And Doze only engages with the screen off, when this
design has already stopped polling. What it buys is that the **overnight session upload runs**
instead of waiting until morning. What really kills the service is the OEM — see Step 0.

**[was wrong] `QUERY_ALL_PACKAGES` was missing entirely.** Since Android 11,
`getApplicationLabel()`/`getApplicationIcon()` throw for invisible packages, and
`PACKAGE_USAGE_STATS` does *not* grant visibility. Without it the picker is empty and the interrupt
says *"You are in com.zhiliaoapp.musically."*

**Why `specialUse`, not `dataSync`.** Android 15 caps `dataSync` and `mediaProcessing` foreground
services at **6 hours per 24**, after which `onTimeout()` fires and restarting throws. `specialUse`
has **no timeout** and is still allowed to start from `BOOT_COMPLETED`. The manifest `<property>` is
Google Play review metadata only — inert for a sideloaded app.

### A PWA can never do this

| | PWA | Native Android |
|---|---|---|
| Draw over other apps | Impossible | Yes |
| Read the foreground app | Impossible | Yes |
| Run when closed | A service worker woken by push. Not a loop. | Yes |

## Architecture — the names

**Existing:** the API layer (`focus/app/`, owns every rule) · the schema (unbypassable rules) ·
the phone client (`focus/static/`, display only).

**New:** **the foreground service** (stays alive) · **the usage watcher** (what app is in front, for
how long, has it crossed a line) · **the overlay bubble** (the circle + the interrupt, display only)
· **the sync client** (the only thing that talks HTTP, owns the offline buffer).

**One deliberate exception to "the API layer owns every rule":** the *"you have been in TikTok too
long"* decision is made on the phone, because it must work with no network. Safe because it is a
**notification, not a state change** — nothing stored depends on it.

## What may be queued offline

**[was wrong]** The first draft disabled `finish` and `kill` offline. But `main.py:135` and `151`
are both `UPDATE ... SET active_slot = NULL WHERE id = ? AND status = 'active'` — they **free** a
slot and cannot create a 4th commitment under any interleaving. The `rowcount == 0 → 409` check
already makes a replay harmless.

> **A write that could violate a constraint if it lands late cannot be queued.**

| Action | Offline | Why |
|---|---|---|
| Show primary, slots, percent | Cached, greyed, "as of 2h ago" | Display only. |
| **Finish / kill** | **Queued and retried** | They free slots. A replay returns 409 → "already done". |
| **Promote** | **Disabled, with the reason** | The only one that *takes* a slot. |
| Usage sessions | Buffered, batched | Pure facts, no rule to judge. |

## Server additions

```sql
CREATE TABLE IF NOT EXISTS distraction_app (
    package_name  TEXT PRIMARY KEY,
    label         TEXT NOT NULL,
    mode          TEXT NOT NULL CHECK (mode IN ('on_sight', 'daily_limit')),
    limit_minutes INTEGER,
    added_at      TEXT NOT NULL,
    removed_at    TEXT            -- never DELETE: sessions reference this
);

CREATE TABLE IF NOT EXISTS app_session (
    client_id     TEXT PRIMARY KEY,   -- generated on the phone (idempotency)
    package_name  TEXT NOT NULL,
    started_at    TEXT NOT NULL,      -- UTC instant
    ended_at      TEXT NOT NULL,      -- closed sessions only
    uploaded_at   TEXT NOT NULL       -- set by the SERVER
);
CREATE INDEX IF NOT EXISTS app_session_by_app ON app_session(package_name, started_at);
```

**Upload only closed sessions.** A nullable `ended_at` plus `ON CONFLICT DO NOTHING` means the
follow-up upload carrying the end time is silently discarded forever.

**Endpoints — all ABOVE the `StaticFiles` mount:**

| Route | Purpose |
|---|---|
| `GET /api/bubble/state` | Everything the bubble draws in one call, **including `used_minutes_today` per app** — without it, a reboot resets the day's budget. |
| `POST /api/usage/sessions` | Batch, `ON CONFLICT(client_id) DO NOTHING`. |
| `GET`/`POST`/`PATCH /api/distractions` | Managed from the web page. |

`finish` and `kill` are reused unchanged.

## The percent — one open decision

`finished ÷ (finished + active + killed)` has a problem: **killing becomes permanently expensive**,
so the winning move is leaving dead commitments in `status='active'` forever — which occupies a
slot, blocks `promote`, and destroys the 3-slot cap the app is built on. Also, `active` in the
denominator means starting work lowers the score, and as a lifetime ratio it stops moving.

| Option | Shape | Cost |
|---|---|---|
| A. As chosen | `finished ÷ (finished + active + killed)` | Simple. Carries the hoarding incentive. |
| **B. Recommended** | `finished ÷ (finished + active)`, "1 killed this month" beside it | Killing stays honest. Kills still visible. |
| C. Rolling 30 days | B, last 30 days only | Actually moves. One more query. |

Edges either way: **zero commitments** is a division by zero; **0 finished / 1 active** reads 0%
for the first fortnight.

## What gets built on the phone

**Kotlin, native, one Gradle module.** Every hard part is a platform API you must call natively
anyway; a cross-platform layer adds translation cost and teaches Dart.

| Piece | What |
|---|---|
| Onboarding | Compose, 4 permission steps. `registerForActivityResult` always returns `RESULT_CANCELED` — re-check state in the callback. |
| Foreground service | `specialUse`. Notification with primary + percent. |
| Usage watcher | Poll while screen on; `ACTION_SCREEN_OFF`/`ON` receiver stops it. |
| The bubble | Classic `View` in `WindowManager`. |
| Expanded state | **[was wrong]** A transparent **Activity**, not an overlay — the first draft said "Compose is fine here" one clause after warning Compose-in-overlay is a trap. An Activity gets real lifecycle owners free. |
| The interrupt | Full-screen `TYPE_APPLICATION_OVERLAY`, 5-second countdown. An overlay, **not** an Activity — Android 12+ blocks background Activity starts. |
| Local buffer | Room. |
| Sync drain | `WorkManager`, batched, backoff. |
| Boot receiver | `RECEIVE_BOOT_COMPLETED`. Allowed for `specialUse`. |

### [was wrong] `ACTIVITY_RESUMED` alone cannot measure minutes

Resume events give **starts** only. A session ends on `ACTIVITY_PAUSED`, `SCREEN_NON_INTERACTIVE`
or `KEYGUARD_SHOWN`. Without them: open TikTok 23:00, screen off 23:05, reopen 08:00 → the watcher
reports **nine hours**, and the daily limit is computed from exactly that.

Second bug: a 5-second poll asking for *the last 5 seconds* returns nothing when no app switch
happened. Query from the last-seen event timestamp and carry the last-known package forward.

### No watchdog is possible

Since Android 15 the `SYSTEM_ALERT_WINDOW` exemption from background service-start restrictions
requires a **currently visible overlay window**. So "WorkManager restarts the dead service" throws
whenever the bubble is not drawn. A watchdog must be a notification the user taps.

### Toolchain (none installed as of 2026-09-08)

JDK 17+ (the `/usr/bin/java` stub is not a JDK), Android Studio, Android SDK + `adb`. No Flutter/RN
needed. **Install with `adb install`, not by tapping the APK** — see risk 2. Generate a release
keystore with `-validity 10000` on day one and back it up off-machine: lose it and the app can
never be updated in place, only uninstalled — wiping the Room buffer and all four permissions.

## Step 0 — the one-day spike that decides everything

ColorOS/FuntouchOS kills background services **regardless of every permission here**, behind a
hidden per-app "Autostart" toggle and a separate "high background power" setting that **no app can
request in code**. Some builds reset them after a system update.

1. Install the toolchain. Half a day.
2. Build a **50-line app**: foreground service, notification, a timestamp appended to a file every
   60 seconds. Nothing else.
3. Turn on Autostart + battery exemption. Unplug. **Leave it overnight.**
4. Read the file in the morning. Gaps?

- **No gaps** → build the rest.
- **Gaps** → a persistent bubble is not reliable on this phone. Fall back to the
  **notification-only version** (progress + finish/kill buttons, no overlay, no usage watching),
  which survives being killed because Android restarts it from the notification.

## Risks

1. **OEM service killers — see Step 0.** Risk #1.
2. **[was missing] The `AccessibilityService` fallback may be locked out.** Android 13+ "restricted
   settings" greys out Accessibility for apps installed by tapping an APK. Escapes: **`adb install`
   is exempt** (session installer), or App info → ⋮ → *Allow restricted settings*, which only
   appears **after** a failed attempt.
3. **`queryEvents()` is unreliable on some ROMs** — returns nothing until Usage Access is toggled
   off and on. Fallback: `AccessibilityService` on `TYPE_WINDOW_STATE_CHANGED` — real-time, no
   polling. Play would reject it; irrelevant for a sideload.
4. **The interrupt is what you will want to delete in week two.** Make the limit easy to *tune*,
   hard to *turn off*.
5. **This app watches everything you do.** Keeping the server off the public internet is the
   mitigation.
6. **Trivial bypasses exist** — work profile / Android 15 private space copies are invisible.
7. **The bubble will log itself.** Filter to tagged apps or upload ~50 rows/day of noise.

## Verification

- Server: `pytest` (needs `DB_PATH` from env first), duplicate `client_id` proving idempotency, a
  queued-`finish` replay returning 409, `used_minutes_today` correct across local midnight.
- Phone — none provable by a green build:
  - Every permission **denied** → explain, do not crash.
  - Screen off 30 min → confirm polling stopped (battery stats).
  - **The nine-hour bug:** open a distraction, screen off, wait, reopen. Minutes, not hours.
  - **Reboot** → the bubble comes back.
  - Airplane mode: display stale-and-greyed, finish/kill **queue**, promote disabled, sessions
    buffer, all drains on reconnect.
  - End to end: open TikTok, pass the limit, **see the interrupt**, read the session row from the DB.
  - The interrupt while **locked** and during **an incoming call**.
