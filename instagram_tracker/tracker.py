"""
Instagram follower / unfollower tracker.

Works from Instagram's official "Download your information" export (JSON format),
so it never needs your password and does not scrape Instagram. Every export you
import is stored as a snapshot in a local SQLite database; comparing snapshots
tells you who followed you, who unfollowed you, and who doesn't follow you back.
"""
import argparse
import datetime as dt
import json
import re
import sqlite3
import zipfile
from pathlib import Path

DEFAULT_DB = Path.home() / ".instagram_tracker.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    taken_at TEXT NOT NULL,          -- ISO date the export was taken
    source TEXT NOT NULL             -- file the snapshot was imported from
);
CREATE TABLE IF NOT EXISTS members (
    snapshot_id INTEGER NOT NULL REFERENCES snapshots(id) ON DELETE CASCADE,
    relation TEXT NOT NULL CHECK (relation IN ('follower', 'following')),
    username TEXT NOT NULL,
    PRIMARY KEY (snapshot_id, relation, username)
);
"""


# ---------------------------------------------------------------- parsing

def _username(entry: dict) -> str | None:
    """
    extract the username from one export entry. Instagram changed the format over the years:
    older exports put it in string_list_data[0]['value'], newer ones in 'title' or only in the href
    """
    for item in entry.get("string_list_data", []):
        if item.get("value"):
            return item["value"].lower()
        match = re.search(r"instagram\.com/(?:_u/)?([^/?#]+)", item.get("href", ""))
        if match:
            return match.group(1).lower()
    return entry.get("title", "").lower() or None


def _entries(data) -> list:
    """the entries are either a top-level list or wrapped in a 'relationships_*' key"""
    if isinstance(data, list):
        return data
    for key, value in data.items():
        if key.startswith("relationships_") and isinstance(value, list):
            return value
    return []


def _usernames(json_blobs: list) -> set[str]:
    names = set()
    for blob in json_blobs:
        for entry in _entries(json.loads(blob)):
            name = _username(entry)
            if name:
                names.add(name)
    return names


def parse_export(path: Path) -> tuple[set[str], set[str]]:
    """
    read an Instagram export (the .zip, or the unzipped folder)
    :return: (followers, following) as sets of lowercase usernames
    """
    path = Path(path)
    if path.is_dir():
        files = {str(p.relative_to(path)).replace("\\", "/"): p.read_bytes() for p in path.rglob("*.json")}
    elif zipfile.is_zipfile(path):
        with zipfile.ZipFile(path) as zf:
            files = {n: zf.read(n) for n in zf.namelist() if n.endswith(".json")}
    else:
        raise ValueError(f"{path} is neither an export folder nor a .zip file")

    follower_files = [b for n, b in files.items() if re.search(r"(^|/)followers(_\d+)?\.json$", n)]
    following_files = [b for n, b in files.items() if re.search(r"(^|/)following\.json$", n)]
    if not follower_files:
        raise ValueError("no followers_*.json found - request the export in JSON format, "
                         "including 'Followers and following'")
    return _usernames(follower_files), _usernames(following_files)


# ---------------------------------------------------------------- storage

class Tracker:
    """
    Class Tracker stores snapshots of followers/following and compares them
    """
    def __init__(self, db_path: Path = DEFAULT_DB):
        self.db = sqlite3.connect(db_path)
        self.db.execute("PRAGMA foreign_keys = ON")
        self.db.executescript(SCHEMA)

    def add_snapshot(self, followers: set, following: set, taken_at: str, source: str = "") -> int:
        with self.db:
            cur = self.db.execute("INSERT INTO snapshots (taken_at, source) VALUES (?, ?)", (taken_at, source))
            sid = cur.lastrowid
            self.db.executemany("INSERT INTO members VALUES (?, ?, ?)",
                                [(sid, "follower", u) for u in followers] +
                                [(sid, "following", u) for u in following])
        return sid

    def snapshots(self) -> list[tuple]:
        """:return: [(id, taken_at, source, n_followers, n_following)] oldest first"""
        return self.db.execute("""
            SELECT s.id, s.taken_at, s.source,
                   SUM(m.relation = 'follower'), SUM(m.relation = 'following')
            FROM snapshots s LEFT JOIN members m ON m.snapshot_id = s.id
            GROUP BY s.id ORDER BY s.taken_at, s.id""").fetchall()

    def members(self, snapshot_id: int, relation: str) -> set[str]:
        rows = self.db.execute("SELECT username FROM members WHERE snapshot_id = ? AND relation = ?",
                               (snapshot_id, relation))
        return {r[0] for r in rows}

    def diff(self, old_id: int, new_id: int) -> dict[str, set]:
        """compare two snapshots"""
        old_f, new_f = self.members(old_id, "follower"), self.members(new_id, "follower")
        old_g, new_g = self.members(old_id, "following"), self.members(new_id, "following")
        return {
            "new_followers": new_f - old_f,
            "unfollowers": old_f - new_f,
            "you_followed": new_g - old_g,
            "you_unfollowed": old_g - new_g,
        }

    def status(self, snapshot_id: int) -> dict[str, set]:
        """relationship status within a single snapshot"""
        followers, following = self.members(snapshot_id, "follower"), self.members(snapshot_id, "following")
        return {
            "not_following_back": following - followers,  # you follow them, they don't follow you
            "fans": followers - following,                # they follow you, you don't follow them
            "mutual": followers & following,
        }

    def history(self, username: str) -> list[tuple[str, str, str]]:
        """:return: [(date, relation, 'started'/'stopped')] - every change for one user across all snapshots"""
        username = username.lower().lstrip("@")
        events, prev = [], {"follower": False, "following": False}
        for sid, taken_at, *_ in self.snapshots():
            for relation in prev:
                now = username in self.members(sid, relation)
                if now != prev[relation]:
                    events.append((taken_at, relation, "started" if now else "stopped"))
                    prev[relation] = now
        return events


# ---------------------------------------------------------------- CLI

def _print_group(title: str, names: set) -> None:
    print(f"\n{title} ({len(names)})")
    for name in sorted(names):
        print(f"  @{name}")


def _pick(tracker: Tracker, ids: list[int] | None) -> tuple[int, int]:
    snaps = [s[0] for s in tracker.snapshots()]
    if ids:
        return ids[0], ids[1]
    if len(snaps) < 2:
        raise SystemExit("need at least two snapshots - import another export later")
    return snaps[-2], snaps[-1]


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(prog="instagram-tracker", description=__doc__.strip().splitlines()[0])
    parser.add_argument("--db", type=Path, default=DEFAULT_DB, help="database file (default: %(default)s)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("import", help="import an Instagram export (.zip or folder) as a snapshot")
    p.add_argument("export", type=Path)
    p.add_argument("--date", default=dt.date.today().isoformat(), help="date of the export (default: today)")
    sub.add_parser("list", help="list snapshots")
    p = sub.add_parser("diff", help="who followed / unfollowed between two snapshots (default: latest two)")
    p.add_argument("ids", nargs="*", type=int, metavar="ID")
    p = sub.add_parser("status", help="who doesn't follow you back, fans, mutuals (default: latest snapshot)")
    p.add_argument("id", nargs="?", type=int)
    p = sub.add_parser("history", help="follow/unfollow timeline for one user")
    p.add_argument("username")
    args = parser.parse_args(argv)

    tracker = Tracker(args.db)
    if args.cmd == "import":
        followers, following = parse_export(args.export)
        sid = tracker.add_snapshot(followers, following, args.date, str(args.export))
        print(f"snapshot #{sid} ({args.date}): {len(followers)} followers, {len(following)} following")
    elif args.cmd == "list":
        for sid, taken_at, source, n_f, n_g in tracker.snapshots():
            print(f"#{sid:<4} {taken_at}  followers={n_f or 0:<6} following={n_g or 0:<6} {source}")
    elif args.cmd == "diff":
        if len(args.ids) not in (0, 2):
            parser.error("diff takes zero or two snapshot ids")
        old, new = _pick(tracker, args.ids)
        print(f"changes from snapshot #{old} to #{new}")
        for title, names in tracker.diff(old, new).items():
            _print_group(title.replace("_", " ").capitalize(), names)
    elif args.cmd == "status":
        snaps = tracker.snapshots()
        if not snaps:
            raise SystemExit("no snapshots yet - run `import` first")
        sid = args.id or snaps[-1][0]
        for title, names in tracker.status(sid).items():
            _print_group(title.replace("_", " ").capitalize(), names)
    elif args.cmd == "history":
        events = tracker.history(args.username)
        if not events:
            print(f"@{args.username} never appears in your snapshots")
        for date, relation, change in events:
            who = f"@{args.username} {change} following you" if relation == "follower" \
                else f"you {change} following @{args.username}"
            print(f"{date}  {who}")


if __name__ == "__main__":
    main()
