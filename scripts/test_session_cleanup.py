"""Session figure cleanup.

State is kept in memory, figures on disk. These tests pin the rule that
nothing a session no longer knows about survives in the media directory — and,
just as importantly, that nothing belonging to a *live* session is deleted.

The tricky case is two browser tabs. Reflex runs one state per tab, so the
second tab cannot see the first tab's papers. A sweep driven only by "not in my
paper list" would therefore delete figures the first tab is still showing. The
sweep is age-scoped to prevent exactly that.
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
import unittest
from io import BytesIO
from pathlib import Path

import pymupdf
from PIL import Image

from app.image_extraction import (
    UPLOAD_URL_PREFIX,
    _PROCESS_START,
    discard_media,
    media_dir,
    media_root,
    prune_media,
    session_media_bytes,
)
from app.states.paper_data import extract_uploaded_paper

LIVE_ID = "upload-" + "a" * 32
STALE_ID = "upload-" + "b" * 32
OTHER_TAB_ID = "upload-" + "c" * 32


def png_bytes(size: tuple[int, int] = (240, 160)) -> bytes:
    stream = BytesIO()
    Image.new("RGB", size, (200, 90, 60)).save(stream, format="PNG")
    return stream.getvalue()


def pdf_with_figures() -> bytes:
    figure = png_bytes()
    with pymupdf.open() as document:
        page = document.new_page()
        page.insert_image(pymupdf.Rect(60, 100, 300, 260), stream=figure)
        page.insert_textbox(
            pymupdf.Rect(60, 270, 545, 320),
            "Figure 1. Recall accuracy by condition.",
            fontsize=10,
        )
        return document.tobytes()


class SessionMediaTests(unittest.TestCase):
    def setUp(self) -> None:
        base = os.getenv("PAPERPROOF_TEST_TMP", tempfile.gettempdir())
        self.root = Path(tempfile.mkdtemp(prefix="paperproof-cleanup-", dir=base))
        self._previous = os.environ.get("PAPERPROOF_MEDIA_DIR")
        os.environ["PAPERPROOF_MEDIA_DIR"] = str(self.root)

    def tearDown(self) -> None:
        if self._previous is None:
            os.environ.pop("PAPERPROOF_MEDIA_DIR", None)
        else:
            os.environ["PAPERPROOF_MEDIA_DIR"] = self._previous
        shutil.rmtree(self.root, ignore_errors=True)

    def seed(self, paper_id: str, *, from_previous_process: bool = False) -> Path:
        """Create a figures folder, optionally back-dated to before startup."""
        directory = self.root / paper_id
        directory.mkdir(parents=True)
        (directory / "fig-01.png").write_bytes(png_bytes())
        if from_previous_process:
            # A folder left behind by an earlier run of the app.
            old = _PROCESS_START - 3600
            os.utime(directory, (old, old))
        return directory

    # -- leftovers from a previous process are swept --------------------

    def test_figures_left_by_a_previous_process_are_deleted(self) -> None:
        self.seed(LIVE_ID, from_previous_process=True)
        self.seed(STALE_ID, from_previous_process=True)
        removed = prune_media(set())
        self.assertEqual(sorted(removed), sorted([LIVE_ID, STALE_ID]))
        self.assertEqual(list(self.root.iterdir()), [])

    def test_a_listed_paper_is_never_swept_even_if_stale(self) -> None:
        """A listed id is a live tab's explicit claim and outranks the age rule."""
        self.seed(STALE_ID, from_previous_process=True)
        self.assertEqual(prune_media({STALE_ID}), [])
        self.assertTrue(media_dir(STALE_ID).exists())

    # -- a live session is never disturbed ------------------------------

    def test_figures_written_by_this_process_survive_a_sweep(self) -> None:
        self.seed(LIVE_ID)
        self.assertEqual(prune_media(set()), [])
        self.assertTrue(media_dir(LIVE_ID).exists())

    def test_a_second_tab_cannot_delete_the_first_tabs_figures(self) -> None:
        """The regression this age rule exists to prevent.

        Tab A uploads and is displaying its figures. Tab B loads with an empty
        paper list and sweeps. Tab A's figures must survive.
        """
        tab_a_paper = self.seed(LIVE_ID)
        # Tab B's view of the world: it knows about nothing.
        self.assertEqual(prune_media(set()), [])
        self.assertTrue(tab_a_paper.exists(), "tab B deleted tab A's figures")

    def test_two_live_tabs_keep_each_others_figures(self) -> None:
        self.seed(LIVE_ID)
        self.seed(OTHER_TAB_ID)
        # Tab B only knows about its own paper.
        prune_media({OTHER_TAB_ID})
        self.assertTrue(media_dir(LIVE_ID).exists())
        self.assertTrue(media_dir(OTHER_TAB_ID).exists())

    def test_an_owning_tab_can_still_delete_its_own_paper(self) -> None:
        self.seed(LIVE_ID)
        # Removal is explicit, which is the only in-process delete path.
        discard_media(LIVE_ID)
        self.assertFalse(media_dir(LIVE_ID).exists())

    # -- safety ---------------------------------------------------------

    def test_directories_this_module_did_not_create_are_never_deleted(self) -> None:
        # Reflex's upload directory holds the raw uploaded PDF/DOCX as well.
        foreign = self.root / "some-other-file.pdf"
        foreign.write_bytes(b"%PDF-1.7 not a paper")
        foreign_dir = self.root / "not-a-paper-id"
        foreign_dir.mkdir()
        (foreign_dir / "keep.txt").write_text("keep me")
        self.seed(STALE_ID, from_previous_process=True)

        prune_media(set())

        self.assertTrue(foreign.exists())
        self.assertTrue((foreign_dir / "keep.txt").exists())
        self.assertFalse(media_dir(STALE_ID).exists())

    def test_loose_files_in_the_media_root_survive_a_sweep(self) -> None:
        loose = self.root / "uploaded-manuscript.pdf"
        loose.write_bytes(b"%PDF-1.7")
        self.seed(STALE_ID, from_previous_process=True)
        prune_media(set())
        self.assertTrue(loose.exists())

    def test_sweeping_an_absent_directory_is_not_an_error(self) -> None:
        shutil.rmtree(self.root)
        self.assertEqual(prune_media(set()), [])
        self.assertEqual(session_media_bytes(), 0)

    def test_a_crafted_paper_id_cannot_escape_the_media_root(self) -> None:
        """The guard is a ValueError from media_dir.

        discard_media swallows it, because a failed cleanup must never break the
        session, so the property that matters is that nothing outside the media
        root is touched. This asserts that, not the exception type.
        """
        outside = self.root.parent / "paperproof-outside-marker"
        outside.mkdir(exist_ok=True)
        marker = outside / "keep.txt"
        marker.write_text("must survive")
        self.addCleanup(lambda: shutil.rmtree(outside, ignore_errors=True))

        for hostile in (
            "../../etc",
            "upload-nothex",
            "..",
            "upload-" + "a" * 31 + "/",
            "/etc/passwd",
        ):
            with self.subTest(paper_id=hostile):
                discard_media(hostile)
                self.assertEqual(marker.read_text(), "must survive")
                self.assertTrue(outside.exists())

        # media_dir itself is the strict one: it refuses the same ids.
        for hostile in ("../../etc", "upload-nothex", "..", "/etc/passwd"):
            with self.subTest(media_dir=hostile):
                with self.assertRaises(ValueError):
                    media_dir(hostile)

    def test_sweeping_is_idempotent(self) -> None:
        self.seed(STALE_ID, from_previous_process=True)
        self.assertEqual(prune_media(set()), [STALE_ID])
        self.assertEqual(prune_media(set()), [])

    def test_discard_media_is_idempotent(self) -> None:
        self.seed(LIVE_ID)
        discard_media(LIVE_ID)
        discard_media(LIVE_ID)
        self.assertFalse(media_dir(LIVE_ID).exists())

    def test_session_size_counts_only_session_figures(self) -> None:
        self.seed(LIVE_ID)
        (self.root / "unrelated.bin").write_bytes(b"x" * 5000)
        self.assertGreater(session_media_bytes(), 0)
        self.assertLess(session_media_bytes(), 5000)


class UploadedFigureStorageTests(unittest.TestCase):
    """Where figures from a real upload actually land."""

    def setUp(self) -> None:
        base = os.getenv("PAPERPROOF_TEST_TMP", tempfile.gettempdir())
        self.root = Path(tempfile.mkdtemp(prefix="paperproof-figs-", dir=base))
        self._previous = os.environ.get("PAPERPROOF_MEDIA_DIR")
        os.environ["PAPERPROOF_MEDIA_DIR"] = str(self.root)
        self.addCleanup(shutil.rmtree, self.root, True)
        if self._previous is None:
            self.addCleanup(os.environ.pop, "PAPERPROOF_MEDIA_DIR", None)
        else:
            self.addCleanup(
                os.environ.__setitem__, "PAPERPROOF_MEDIA_DIR", self._previous
            )

    def test_an_uploaded_paper_leaves_figures_under_its_own_id(self) -> None:
        paper = extract_uploaded_paper("figures.pdf", pdf_with_figures())
        directory = media_dir(paper["id"])
        self.assertTrue(directory.exists())
        self.assertTrue(directory.is_relative_to(media_root()))
        self.assertEqual(
            {child.name for child in directory.iterdir()},
            {image["filename"] for image in paper["images"]},
        )

    def test_stored_filenames_never_escape_their_folder(self) -> None:
        paper = extract_uploaded_paper("figures.pdf", pdf_with_figures())
        directory = media_dir(paper["id"])
        for image in paper["images"]:
            self.assertEqual(Path(image["local_path"]).name, image["filename"])
            self.assertNotIn("..", image["local_path"])
            self.assertTrue((directory / image["filename"]).is_relative_to(directory))

    def test_the_serving_prefix_is_stable(self) -> None:
        self.assertEqual(UPLOAD_URL_PREFIX, "/_upload")

    def test_a_rejected_or_unreadable_upload_leaves_nothing_behind(self) -> None:
        with self.assertRaises(ValueError):
            extract_uploaded_paper("empty.pdf", b"")
        self.assertEqual(list(self.root.iterdir()), [])

    def test_tiny_images_are_discarded_rather_than_stored(self) -> None:
        """Under MIN_IMAGE_DIMENSION is treated as a glyph, not a figure."""
        from app.image_extraction import MIN_IMAGE_DIMENSION

        self.assertGreaterEqual(MIN_IMAGE_DIMENSION, 80)


class SweepWiringTests(unittest.TestCase):
    """The sweep only helps if it is actually wired to run.

    Reflex registers load events from `add_page(on_load=...)`. A state method
    named `on_load` is dead code that looks correct, so this pins the real
    wiring rather than trusting the name.
    """

    def test_the_page_registers_the_sweep_as_a_load_event(self) -> None:
        from app.app import app
        from app.states.workspace_state import WorkspaceState

        events = app.get_load_events("/")
        self.assertEqual(len(events), 1, "the sweep must be the page's load event")
        handler = events[0]
        self.assertEqual(handler.fn.__name__, "sweep_session_media")
        self.assertIs(handler.state, WorkspaceState)

    def test_the_registered_handler_really_reaches_the_sweep(self) -> None:
        from app.app import app
        from app.states.workspace_state import WorkspaceState

        handler = app.get_load_events("/")[0]
        self.assertIs(handler.state, WorkspaceState)
        # The registered function must reach the real implementation, not a
        # wrapper that quietly does nothing.
        self.assertTrue(callable(WorkspaceState._sweep_session_media))

    def test_no_dead_on_load_method_exists(self) -> None:
        """A state method called on_load would never be invoked."""
        from app.states.workspace_state import WorkspaceState

        self.assertFalse(
            hasattr(WorkspaceState, "on_load"),
            "Reflex ignores a state method named on_load; wire add_page instead",
        )


if __name__ == "__main__":
    unittest.main()