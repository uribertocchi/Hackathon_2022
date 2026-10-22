# Instagram Follower Tracker

Tracks who follows and unfollows your Instagram account over time.

## How it works

Instagram's API does not give personal accounts their follower lists, and scraping or
logging in with your password breaks Instagram's Terms of Use and can get the account locked.
This app uses Instagram's official **data export** instead:

1. Each export you import becomes a **snapshot** (followers + following) in a local SQLite database.
2. Comparing two snapshots shows **new followers**, **unfollowers**, and who *you* followed or unfollowed.
3. A single snapshot shows who **doesn't follow you back**, your **fans**, and your **mutuals**.

Nothing leaves your machine. The database is `~/.instagram_tracker.db` (change it with `--db`).

## Getting an export

Instagram → *Settings* → *Accounts Center* → *Your information and permissions* →
*Download your information* → choose **Some of your information** → **Followers and following**,
format **JSON**, date range **All time**. You'll get a `.zip` within minutes to hours.
Repeat this regularly (e.g. weekly) to build up a history.

## Usage

Run from the repository root (Python 3.10+, standard library only):

```bash
python -m instagram_tracker import ~/Downloads/instagram-export.zip --date 2026-10-01
python -m instagram_tracker import ~/Downloads/instagram-export-2.zip   # date defaults to today
python -m instagram_tracker list              # all snapshots with counts
python -m instagram_tracker diff              # changes between the latest two snapshots
python -m instagram_tracker diff 1 3          # changes between snapshots #1 and #3
python -m instagram_tracker status            # not following back / fans / mutuals
python -m instagram_tracker history someuser  # follow/unfollow timeline for one account
```

Example `diff` output:

```
changes from snapshot #1 to #2

New followers (1)
  @dave

Unfollowers (1)
  @alice
...
```

## Data model

| table       | columns                                                        |
|-------------|----------------------------------------------------------------|
| `snapshots` | `id`, `taken_at` (date of export), `source` (imported file)    |
| `members`   | `snapshot_id`, `relation` (`follower` / `following`), `username` |

Follow/unfollow events are computed from consecutive snapshots rather than stored, so
re-importing or deleting a snapshot never leaves the history inconsistent.

## Tests

```bash
python -m unittest discover -s instagram_tracker/tests -t .
```
