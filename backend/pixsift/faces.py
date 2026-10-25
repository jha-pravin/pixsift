"""Face grouping, name matching and people management.

Matching compares a face with each person's *closest* confirmed faces (k nearest neighbours), not with an
average, so a 2026 photo of a child is matched against recent photos of that child rather than a blend of
every age. Similarities are weighted by how far apart in time the photos were taken, and faces the user said
were "not <person>" act as negative examples. Only user-confirmed faces are used as references, so automatic
matches can never reinforce their own mistakes.

Confident matches are named automatically (assigned_by='auto') and listed for review; everything else is a
suggestion the user confirms. Unnamed faces left over are grouped with HDBSCAN.
"""

from datetime import datetime

import numpy as np
from sklearn.cluster import HDBSCAN, AgglomerativeClustering

from .db import Database

SUGGEST_MIN_SIM = 0.45     # matching score needed to propose a name
AUTO_MIN_SIM = 0.60        # ...to name a face automatically
AUTO_MARGIN = 0.10         # ...and it must beat the runner-up person by this much
KNN = 3                    # closest confirmed faces per person that count
TIME_SCALE_YEARS = 4.0     # similarity weight halves to ~0.6 at 4 years apart (see _time_weight)
TIME_INFLUENCE = 0.3       # at most 30% of a similarity is lost to a large time gap
CONFIRMED = ("user", "carry")  # reference faces: named by the user (or kept from their naming across edits)
CARRY_MIN_SIM = 0.45       # keep a name across re-analysis of the same picture / edited copy
GROUP_MIN_SIM = 0.35       # member must be this close to its group centroid
MERGE_MIN_SIM = 0.6        # leaf groups whose centroids are this similar are the same person
LEFTOVER_MIN_SIM = 0.5     # faces HDBSCAN left ungrouped are paired up when at least this similar
LEFTOVER_MAX = 3000        # bound the O(n²) leftover pass; big libraries don't need it
MIN_GROUP = 2              # smallest group that can exist
ASK_MIN_DEFAULT = 3        # by default only ask about people seen in 3+ photos


def to_blob(v: np.ndarray) -> bytes:
    return np.asarray(v, dtype=np.float32).tobytes()


def from_blob(b: bytes) -> np.ndarray:
    return np.frombuffer(b, dtype=np.float32)


def recluster(db: Database) -> int:
    """Group unnamed, non-ignored faces. Returns number of groups."""
    rows = db.query("SELECT id, embedding FROM faces WHERE person_id IS NULL AND ignored=0")
    db.execute("UPDATE faces SET cluster_id=NULL WHERE person_id IS NOT NULL OR ignored=1")
    if len(rows) < MIN_GROUP:
        db.execute("UPDATE faces SET cluster_id=NULL")
        return 0
    x = np.stack([from_blob(r["embedding"]) for r in rows])
    # On unit vectors euclidean distance is monotonic in cosine distance, and allows tree-based search.
    # "leaf" gives small, tight groups (over-splitting is cheap to fix by naming; over-merging is not).
    # Don't use cluster_selection_epsilon: sklearn's epsilon search crashes with NumPy >= 2.5.
    labels = HDBSCAN(min_cluster_size=MIN_GROUP, min_samples=1, copy=True,
                     cluster_selection_method="leaf").fit_predict(x)
    labels = _group_leftovers(x, labels)
    labels = _merge_close_groups(x, labels)
    # Guard against chaining: members far from their group's centroid go back to "ungrouped".
    for lbl in set(labels) - {-1}:
        idx = np.flatnonzero(labels == lbl)
        cent = x[idx].mean(axis=0)
        cent /= np.linalg.norm(cent)
        labels[idx[x[idx] @ cent < GROUP_MIN_SIM]] = -1
    with db.conn() as c:
        c.executemany(
            "UPDATE faces SET cluster_id=? WHERE id=?",
            ((int(lbl) if lbl >= 0 else None, r["id"]) for lbl, r in zip(labels, rows)),
        )
    return int(labels.max() + 1) if len(labels) else 0


def _group_leftovers(x: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """HDBSCAN never forms a group when *all* points belong to one person (e.g. the last unnamed person, or a
    small library), so faces it left ungrouped get a second, simpler pass: average-linkage clustering."""
    idx = np.flatnonzero(labels == -1)
    if not 2 <= len(idx) <= LEFTOVER_MAX:
        return labels
    sub = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                  distance_threshold=1 - LEFTOVER_MIN_SIM).fit_predict(x[idx])
    labels = labels.copy()
    next_label = labels.max() + 1
    for s in np.unique(sub):
        members = idx[sub == s]
        if len(members) >= MIN_GROUP:
            labels[members] = next_label
            next_label += 1
    return labels


def _merge_close_groups(x: np.ndarray, labels: np.ndarray) -> np.ndarray:
    """Join groups of the same person that HDBSCAN split apart (average linkage on group centroids)."""
    ids = np.array(sorted(set(labels.tolist()) - {-1}))
    if len(ids) < 2:
        return labels
    cents = np.stack([x[labels == i].mean(axis=0) for i in ids])
    merged = AgglomerativeClustering(n_clusters=None, metric="cosine", linkage="average",
                                     distance_threshold=1 - MERGE_MIN_SIM).fit_predict(cents)
    remap = dict(zip(ids.tolist(), merged.tolist()))
    return np.array([remap.get(int(lbl), -1) for lbl in labels])


def _years(iso: str | None) -> float:
    if not iso:
        return np.nan
    try:
        d = datetime.fromisoformat(iso)
    except ValueError:
        return np.nan
    return d.year + (d.timetuple().tm_yday - 1) / 365.25


def _time_weight(dq: np.ndarray, dr: np.ndarray) -> np.ndarray:
    """1.0 for photos taken together, falling towards (1 - TIME_INFLUENCE) for photos years apart.
    Unknown dates count as 'together' (no penalty)."""
    # float32 and in place: this runs on (faces x reference faces) matrices of tens of millions of cells.
    w = np.subtract.outer(dq.astype(np.float32), dr.astype(np.float32))
    np.abs(w, out=w)
    np.nan_to_num(w, copy=False, nan=0.0)
    w *= np.float32(-1.0 / TIME_SCALE_YEARS)
    np.exp(w, out=w)
    w *= np.float32(TIME_INFLUENCE)
    w += np.float32(1 - TIME_INFLUENCE)
    return w


class Matcher:
    """Scores faces against every named person. Build once, use for many faces."""

    def __init__(self, db: Database):
        refs = db.query(
            "SELECT f.person_id, f.embedding, i.taken_at FROM faces f JOIN images i ON i.id=f.image_id "
            f"WHERE f.person_id IS NOT NULL AND f.ignored=0 AND i.missing=0 "
            f"AND f.assigned_by IN ({','.join('?' * len(CONFIRMED))}) ORDER BY f.person_id", CONFIRMED,
        )
        self.person_ids: list[int] = []
        self._slices: list[slice] = []
        for i, r in enumerate(refs):
            if not self.person_ids or self.person_ids[-1] != r["person_id"]:
                if self._slices:
                    self._slices[-1] = slice(self._slices[-1].start, i)
                self.person_ids.append(r["person_id"])
                self._slices.append(slice(i, len(refs)))
        self._emb = np.stack([from_blob(r["embedding"]) for r in refs]) if refs else np.zeros((0, 128), np.float32)
        self._dates = np.array([_years(r["taken_at"]) for r in refs], dtype=np.float64)
        negs = db.query(
            "SELECT r.person_id, f.embedding FROM face_rejections r JOIN faces f ON f.id=r.face_id"
        )
        self._neg: dict[int, np.ndarray] = {}
        for r in negs:
            self._neg.setdefault(r["person_id"], []).append(from_blob(r["embedding"]))
        self._neg = {k: np.stack(v) for k, v in self._neg.items()}

    def __bool__(self) -> bool:
        return bool(self.person_ids)

    def refs_of(self, person_id: int) -> np.ndarray | None:
        """Confirmed face embeddings of one person."""
        try:
            return self._emb[self._slices[self.person_ids.index(person_id)]]
        except ValueError:
            return None

    def scores(self, q: np.ndarray, dates: list[str | None] | None = None, chunk: int = 512) -> np.ndarray:
        """(faces x persons) matching scores; -1 where a person is ruled out by a negative example."""
        q = np.atleast_2d(q).astype(np.float32)
        out = np.full((len(q), len(self.person_ids)), -1.0, dtype=np.float32)
        if not self:
            return out
        dq_all = np.array([_years(d) for d in dates] if dates else [np.nan] * len(q), dtype=np.float64)
        for start in range(0, len(q), chunk):
            qs, dq = q[start:start + chunk], dq_all[start:start + chunk]
            adj = qs @ self._emb.T
            adj *= _time_weight(dq, self._dates)  # time-adjusted similarity
            for p, sl in enumerate(self._slices):
                block = adj[:, sl]
                k = min(KNN, block.shape[1])
                top = -np.partition(-block, k - 1, axis=1)[:, :k] if block.shape[1] > k else block
                score = top.mean(axis=1)
                neg = self._neg.get(self.person_ids[p])
                if neg is not None:  # closer to a known lookalike than to the person: not them
                    score = np.where((qs @ neg.T).max(axis=1) >= score, -1.0, score)
                out[start:start + len(qs), p] = score
        return out

    def best(self, q: np.ndarray, dates: list[str | None] | None = None,
             exclude: list[set[int]] | None = None) -> list[tuple[int | None, float, float]]:
        """Per face: (best person, score, runner-up score), skipping excluded persons."""
        sc = self.scores(q, dates)
        res = []
        for i, row in enumerate(sc):
            order = np.argsort(-row)
            picks = [j for j in order if row[j] > -1 and not (exclude and self.person_ids[j] in exclude[i])]
            if not picks:
                res.append((None, 0.0, 0.0))
                continue
            second = float(row[picks[1]]) if len(picks) > 1 else 0.0
            res.append((self.person_ids[picks[0]], float(row[picks[0]]), second))
        return res


def _rejections(db: Database, face_ids: list[int]) -> dict[int, set[int]]:
    out: dict[int, set[int]] = {}
    for start in range(0, len(face_ids), 900):  # stay under SQLite's variable limit
        part = face_ids[start:start + 900]
        for r in db.query(f"SELECT face_id, person_id FROM face_rejections WHERE face_id IN ({','.join('?' * len(part))})", part):
            out.setdefault(r["face_id"], set()).add(r["person_id"])
    return out


def auto_assign(db: Database, person_id: int | None = None) -> int:
    """Name unnamed faces that clearly match one person. Returns how many were named.

    With person_id (just named/confirmed), only faces that could now match *that* person are re-scored.
    That's exact: a face's score for a person never exceeds its best similarity to that person's faces,
    and nobody else's scores changed. On a 20k-face library it turns ~5 s into well under a second."""
    matcher = Matcher(db)
    if not matcher:
        return 0
    rows = db.query(
        "SELECT f.id, f.embedding, i.taken_at FROM faces f JOIN images i ON i.id=f.image_id "
        "WHERE f.person_id IS NULL AND f.ignored=0 AND i.missing=0"
    )
    if not rows:
        return 0
    q = np.stack([from_blob(r["embedding"]) for r in rows])
    if person_id is not None:
        refs = matcher.refs_of(person_id)
        if refs is None:
            return 0
        keep = np.flatnonzero((q @ refs.T).max(axis=1) >= AUTO_MIN_SIM)
        rows, q = [rows[i] for i in keep], q[keep]
        if not rows:
            return 0
    rejected = _rejections(db, [r["id"] for r in rows])
    results = matcher.best(q, [r["taken_at"] for r in rows], [rejected.get(r["id"], set()) for r in rows])
    picks = [(pid, r["id"]) for r, (pid, score, second) in zip(rows, results)
             if pid is not None and score >= AUTO_MIN_SIM and score - second >= AUTO_MARGIN]
    with db.conn() as c:
        c.executemany("UPDATE faces SET person_id=?, assigned_by='auto', cluster_id=NULL WHERE id=?", picks)
    return len(picks)


def confirm_auto(db: Database, person_id: int, face_ids: list[int] | None = None) -> None:
    """Turn automatic matches into confirmed ones (they then help recognise this person too)."""
    if face_ids:
        db.execute(f"UPDATE faces SET assigned_by='user' WHERE person_id=? AND assigned_by='auto' "
                   f"AND id IN ({','.join('?' * len(face_ids))})", [person_id, *face_ids])
    else:
        db.execute("UPDATE faces SET assigned_by='user' WHERE person_id=? AND assigned_by='auto'", (person_id,))


def ask_min_photos(db: Database) -> int:
    """Only ask about people seen in at least this many photos (keeps one-off strangers out of the questions)."""
    try:
        return max(MIN_GROUP, int(db.setting("ask_min_photos", str(ASK_MIN_DEFAULT))))
    except ValueError:
        return MIN_GROUP


def unnamed_groups(db: Database, limit: int = 300) -> list[dict]:
    """Unnamed face groups, largest first, with sample faces and a name suggestion."""
    groups = db.query(
        "SELECT cluster_id, COUNT(*) AS n FROM faces WHERE cluster_id IS NOT NULL AND person_id IS NULL "
        "AND ignored=0 GROUP BY cluster_id HAVING n >= ? ORDER BY n DESC LIMIT ?", (ask_min_photos(db), limit)
    )
    if not groups:
        return []
    matcher = Matcher(db)
    people = {r["id"]: r for r in db.query("SELECT id, name, hidden FROM persons")}
    out = []
    # One query and one scoring pass for all shown groups (not one per group).
    ids = [g["cluster_id"] for g in groups]
    rows = db.query(
        "SELECT f.id, f.image_id, f.embedding, f.cluster_id, i.taken_at FROM faces f JOIN images i ON i.id=f.image_id "
        f"WHERE f.cluster_id IN ({','.join('?' * len(ids))}) AND f.person_id IS NULL AND f.ignored=0 "
        "ORDER BY f.cluster_id, f.score DESC", ids)
    scores = (matcher.scores(np.stack([from_blob(r["embedding"]) for r in rows]), [r["taken_at"] for r in rows])
              if matcher and rows else None)
    by_group: dict[int, list[int]] = {}
    for n, r in enumerate(rows):
        by_group.setdefault(r["cluster_id"], []).append(n)
    for g in groups:
        members = by_group.get(g["cluster_id"], [])
        suggestion = None
        if scores is not None and members:
            # Each face votes; the group's suggestion is the person with the best average score.
            sc = scores[members]
            mean = np.where(sc > -1, sc, 0).mean(axis=0)
            j = int(np.argmax(mean))
            if mean[j] >= SUGGEST_MIN_SIM:
                pid = matcher.person_ids[j]
                suggestion = {"person_id": pid, "name": people[pid]["name"], "hidden": bool(people[pid]["hidden"]),
                              "similarity": round(float(mean[j]), 3)}
        out.append({
            "cluster_id": g["cluster_id"],
            "count": g["n"],
            "faces": [{"id": rows[n]["id"], "image_id": rows[n]["image_id"]} for n in members[:8]],
            "suggestion": suggestion,
        })
    return out


def suggest_for_face(db: Database, face_id: int) -> dict | None:
    face = db.query_one(
        "SELECT f.embedding, i.taken_at FROM faces f JOIN images i ON i.id=f.image_id WHERE f.id=?", (face_id,)
    )
    if not face:
        return None
    matcher = Matcher(db)
    if not matcher:
        return None
    rejected = _rejections(db, [face_id]).get(face_id, set())
    (pid, score, _), = matcher.best(from_blob(face["embedding"]), [face["taken_at"]], [rejected])
    if pid is None or score < SUGGEST_MIN_SIM:
        return None
    p = db.query_one("SELECT name, hidden FROM persons WHERE id=?", (pid,))
    return {"person_id": pid, "name": p["name"], "hidden": bool(p["hidden"]), "similarity": round(score, 3)}


def hide_faces(db: Database, face_ids: list[int]) -> int:
    """'Don't ask me about this person': file the faces under a new hidden person. They stay references, so
    this person's future photos are recognised and filed there quietly too."""
    n = (db.query_one("SELECT COALESCE(MAX(id), 0) + 1 AS n FROM persons")["n"])
    person_id = db.execute("INSERT INTO persons(name, hidden) VALUES (?, 1)", (f"Hidden person {n}",)).lastrowid
    assign_faces(db, face_ids, person_id)
    return person_id


def unhide_person(db: Database, person_id: int, name: str | None) -> int | None:
    """Stop hiding someone. With a name: they become a normal person (merged into an existing one of that
    name); photos collected while hidden keep 'auto' status for review. Without: back into the questions."""
    if name and name.strip():
        name = " ".join(name.split())
        existing = db.query_one("SELECT id FROM persons WHERE name=? AND id<>?", (name, person_id))
        if existing:
            merge_persons(db, person_id, existing["id"])
            db.execute("UPDATE persons SET hidden=0 WHERE id=?", (existing["id"],))
            return existing["id"]
        db.execute("UPDATE persons SET name=?, hidden=0 WHERE id=?", (name, person_id))
        return person_id
    db.execute("UPDATE faces SET person_id=NULL, assigned_by=NULL WHERE person_id=?", (person_id,))
    db.execute("DELETE FROM persons WHERE id=?", (person_id,))
    return None  # caller regroups (slow on big libraries, so it runs as a background job)


def get_or_create_person(db: Database, name: str) -> int:
    name = " ".join(name.split())
    if not name:
        raise ValueError("name is empty")
    row = db.query_one("SELECT id FROM persons WHERE name=?", (name,))
    if row:
        return row["id"]
    return db.execute("INSERT INTO persons(name) VALUES (?)", (name,)).lastrowid


def assign_faces(db: Database, face_ids: list[int], person_id: int | None) -> None:
    """Name faces (person_id) or clear their name (None). User decisions always win."""
    if not face_ids:
        return
    marks = ",".join("?" * len(face_ids))
    if person_id is None:
        db.execute(f"UPDATE faces SET person_id=NULL, assigned_by=NULL WHERE id IN ({marks})", face_ids)
    else:
        db.execute(
            f"UPDATE faces SET person_id=?, assigned_by='user', cluster_id=NULL, ignored=0 WHERE id IN ({marks})",
            [person_id, *face_ids],
        )
        db.execute(f"DELETE FROM face_rejections WHERE person_id=? AND face_id IN ({marks})", [person_id, *face_ids])
        db.execute(
            "UPDATE persons SET cover_face_id=COALESCE(cover_face_id, ?) WHERE id=?", (face_ids[0], person_id)
        )


def reject_face(db: Database, face_id: int) -> None:
    """'Not this person': unname the face and remember not to suggest that person for it again."""
    row = db.query_one("SELECT person_id FROM faces WHERE id=?", (face_id,))
    if row and row["person_id"]:
        db.execute("INSERT OR IGNORE INTO face_rejections(face_id, person_id) VALUES (?, ?)",
                   (face_id, row["person_id"]))
    db.execute("UPDATE faces SET person_id=NULL, assigned_by=NULL, cluster_id=NULL WHERE id=?", (face_id,))
    db.execute("UPDATE persons SET cover_face_id=NULL WHERE cover_face_id=?", (face_id,))


def merge_persons(db: Database, source_id: int, target_id: int) -> None:
    db.execute("UPDATE faces SET person_id=? WHERE person_id=?", (target_id, source_id))
    db.execute("INSERT OR IGNORE INTO face_rejections(face_id, person_id) "
               "SELECT face_id, ? FROM face_rejections WHERE person_id=?", (target_id, source_id))
    db.execute("DELETE FROM persons WHERE id=?", (source_id,))


def carry_over(embeddings: list[np.ndarray], refs: list[dict]) -> list[int | None]:
    """For newly detected faces, keep names from reference faces (same picture before re-analysis,
    or the original of an edited copy) when the embeddings clearly match."""
    out: list[int | None] = [None] * len(embeddings)
    if not refs or not embeddings:
        return out
    ref_emb = np.stack([from_blob(r["embedding"]) for r in refs])
    sims = np.stack(embeddings) @ ref_emb.T
    used: set[int] = set()
    for i in np.argsort(-sims.max(axis=1)):
        for j in np.argsort(-sims[i]):
            if sims[i, j] < CARRY_MIN_SIM:
                break
            if j not in used:
                out[i] = refs[j]["person_id"]
                used.add(j)
                break
    return out
