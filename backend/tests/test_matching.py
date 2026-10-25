"""Name matching on synthetic embeddings: aging, lookalikes, no self-reinforcement, ambiguity, time weighting."""

import numpy as np
import pytest

from pixsift import faces as F
from pixsift.db import Database


def vec(*parts: tuple[int, float]) -> np.ndarray:
    v = np.zeros(128, np.float32)
    for axis, weight in parts:
        v[axis] = weight
    return v / np.linalg.norm(v)


class Lib:
    def __init__(self, db: Database):
        self.db = db
        self.n = 0

    def face(self, emb, year=2020, person=None, by="user") -> int:
        self.n += 1
        img = self.db.execute(
            "INSERT INTO images(path, folder, filename, ext, size, mtime, taken_at, thumb, analyzed_at) "
            "VALUES (?, '/x', ?, '.jpg', 1, 0, ?, 't', 'now')",
            (f"/x/{self.n}.jpg", f"{self.n}.jpg", f"{year}-06-01T12:00:00"),
        ).lastrowid
        return self.db.execute(
            "INSERT INTO faces(image_id, x, y, w, h, score, embedding, person_id, assigned_by) "
            "VALUES (?, 0, 0, .2, .2, .99, ?, ?, ?)",
            (img, F.to_blob(emb), person, by if person else None),
        ).lastrowid

    def person(self, name) -> int:
        return F.get_or_create_person(self.db, name)

    def owner(self, face_id):
        r = self.db.query_one("SELECT person_id, assigned_by FROM faces WHERE id=?", (face_id,))
        return r["person_id"], r["assigned_by"]


@pytest.fixture
def lib(tmp_path):
    return Lib(Database(tmp_path / "t.db"))


def test_child_growing_up_matches_recent_photos_not_the_average(lib):
    young, old = vec((0, 1)), vec((0, 0.1), (1, 0.995))  # same person 10 years apart look very different
    kid, other = lib.person("Kid"), lib.person("Other")
    for i in range(5):
        lib.face(vec((0, 1), (10 + i, 0.15)), 2012, kid)
    for i in range(3):
        lib.face(vec((0, 0.1), (1, 0.995), (20 + i, 0.15)), 2021, kid)
    lib.face(vec((3, 1)), 2021, other)
    new = lib.face(vec((0, 0.1), (1, 0.995), (30, 0.1)), 2022)

    # The old single-average approach would score this face below the auto threshold.
    cent = np.mean([F.from_blob(r["embedding"]) for r in lib.db.query(
        "SELECT embedding FROM faces WHERE person_id=?", (kid,))], axis=0)
    assert float(old @ (cent / np.linalg.norm(cent))) < F.AUTO_MIN_SIM < float(young @ young)

    assert F.auto_assign(lib.db) == 1
    assert lib.owner(new) == (kid, "auto")


def test_rejected_lookalike_is_not_suggested_again(lib):
    anna = lib.person("Anna")
    for i in range(3):
        lib.face(vec((0, 1), (10 + i, 0.1)), 2020, anna)
    sister = lib.face(vec((0, 1), (2, 0.6)), 2020, anna)  # wrongly named, then corrected
    F.reject_face(lib.db, sister)
    sister2 = lib.face(vec((0, 1), (2, 0.62), (40, 0.05)), 2021)  # another photo of the lookalike
    anna2 = lib.face(vec((0, 1), (41, 0.1)), 2021)                 # another photo of Anna

    F.auto_assign(lib.db)
    assert lib.owner(sister2) == (None, None)
    assert F.suggest_for_face(lib.db, sister2) is None
    assert lib.owner(anna2) == (anna, "auto")


def test_automatic_matches_do_not_teach_themselves(lib):
    bob = lib.person("Bob")
    lib.face(vec((0, 1)), 2020, bob)
    step1 = lib.face(vec((0, 0.8), (1, 0.6)), 2020)   # 0.8 like Bob -> auto
    step2 = lib.face(vec((0, 0.3), (1, 0.95)), 2020)  # like step1, not like Bob
    F.auto_assign(lib.db)
    assert lib.owner(step1) == (bob, "auto") and lib.owner(step2) == (None, None)
    F.auto_assign(lib.db)  # running again must not chain through the automatic match
    assert lib.owner(step2) == (None, None)


def test_ambiguous_match_is_only_a_suggestion(lib):
    a, b = lib.person("A"), lib.person("B")
    lib.face(vec((0, 1)), 2020, a)
    lib.face(vec((1, 1)), 2020, b)
    q = lib.face(vec((0, 1), (1, 0.9)), 2020)  # equally like both
    assert F.auto_assign(lib.db) == 0
    assert F.suggest_for_face(lib.db, q)["name"] in {"A", "B"}


def test_photos_from_the_same_time_count_more(lib):
    then, now = lib.person("Then"), lib.person("Now")
    lib.face(vec((0, 1)), 2005, then)
    lib.face(vec((1, 1)), 2024, now)
    q = lib.face(vec((0, 1), (1, 1)), 2024)  # equally similar to both; taken in 2024
    assert F.suggest_for_face(lib.db, q)["name"] == "Now"


def test_confirming_auto_matches_makes_them_references(lib):
    eve = lib.person("Eve")
    lib.face(vec((0, 1)), 2020, eve)
    f = lib.face(vec((0, 0.8), (1, 0.6)), 2020)
    F.auto_assign(lib.db)
    F.confirm_auto(lib.db, eve)
    assert lib.owner(f) == (eve, "user")
    assert len(F.Matcher(lib.db)._emb) == 2


def test_a_single_unnamed_person_still_forms_a_group(lib):
    # HDBSCAN alone leaves everything ungrouped when all faces are one person.
    ids = [lib.face(vec((0, 1), (10 + i, 0.2))) for i in range(4)]
    stranger = lib.face(vec((5, 1)))
    F.recluster(lib.db)
    groups = F.unnamed_groups(lib.db)
    assert len(groups) == 1 and {f["id"] for f in groups[0]["faces"]} == set(ids)
    assert stranger not in {f["id"] for f in groups[0]["faces"]}


def test_targeted_auto_assign_matches_the_full_run(lib):
    a, b = lib.person("A"), lib.person("B")
    lib.face(vec((0, 1)), 2020, a)
    lib.face(vec((1, 1)), 2020, b)
    near_a = lib.face(vec((0, 1), (9, 0.3)))
    near_b = lib.face(vec((1, 1), (9, 0.3)))
    assert F.auto_assign(lib.db, a) == 1  # only A's candidates
    assert lib.owner(near_a) == (a, "auto") and lib.owner(near_b) == (None, None)
    assert F.auto_assign(lib.db) == 1      # the full run finds the rest
    assert lib.owner(near_b) == (b, "auto")
