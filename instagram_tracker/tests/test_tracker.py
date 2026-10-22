import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from instagram_tracker.tracker import Tracker, parse_export


def make_export(folder: Path, followers: list, following: list, new_format: bool = False) -> Path:
    """write a fake Instagram export zip in the old or the newer JSON format"""
    def entry(name):
        if new_format:  # newer exports: name in 'title', value omitted
            return {"title": name, "string_list_data": [{"href": f"https://www.instagram.com/_u/{name}"}]}
        return {"title": "", "string_list_data": [{"href": f"https://www.instagram.com/{name}", "value": name}]}
    path = folder / f"export_{len(list(folder.iterdir()))}.zip"
    base = "connections/followers_and_following/"
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr(base + "followers_1.json", json.dumps([entry(n) for n in followers]))
        zf.writestr(base + "following.json", json.dumps({"relationships_following": [entry(n) for n in following]}))
    return path


class TrackerTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp())
        self.tracker = Tracker(self.tmp / "db.sqlite")

    def test_parse_both_formats(self):
        for new_format in (False, True):
            d = self.tmp / str(new_format)
            d.mkdir()
            followers, following = parse_export(make_export(d, ["Alice", "bob"], ["bob", "carol"], new_format))
            self.assertEqual(followers, {"alice", "bob"})
            self.assertEqual(following, {"bob", "carol"})

    def test_diff_status_history(self):
        s1 = self.tracker.add_snapshot({"alice", "bob"}, {"bob", "carol"}, "2026-01-01")
        s2 = self.tracker.add_snapshot({"bob", "dave"}, {"bob", "dave"}, "2026-02-01")
        self.assertEqual(self.tracker.diff(s1, s2), {
            "new_followers": {"dave"}, "unfollowers": {"alice"},
            "you_followed": {"dave"}, "you_unfollowed": {"carol"},
        })
        self.assertEqual(self.tracker.status(s1),
                         {"not_following_back": {"carol"}, "fans": {"alice"}, "mutual": {"bob"}})
        self.assertEqual(self.tracker.history("@Alice"),
                         [("2026-01-01", "follower", "started"), ("2026-02-01", "follower", "stopped")])


if __name__ == "__main__":
    unittest.main()
