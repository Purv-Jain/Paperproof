"""Contracts for the rendered interface, not for handler logic.

These tests assert on the component tree Reflex actually produces. A scrollable
region is invisible to assistive technology and unreachable by keyboard unless it
carries `tabindex`, a landmark `role`, and a name -- and nothing in the Python
type system objects when those are dropped, so only a test on the rendered tree
catches it.
"""

import re
import unittest

from app.components.workspace import paper_reader, workspace


def iter_rendered(node):
    """Yield every rendered node in a Reflex component tree.

    Reflex renders a component tree into nested dicts of
    ``{name, props, children}``, with element attributes as strings in
    ``props``.
    """
    if isinstance(node, list):
        for child in node:
            yield from iter_rendered(child)
        return
    if not isinstance(node, dict):
        return
    yield node
    for value in node.values():
        yield from iter_rendered(value)


def scrollable_regions(tree):
    """Return every node in the tree that scrolls vertically."""
    found = []
    for node in iter_rendered(tree):
        props = [p for p in (node.get("props") or []) if isinstance(p, str)]
        if any("overflow-y-auto" in p for p in props):
            found.append((node, props))
    return found


def prop_map(props):
    """Parse Reflex attribute strings into a dict.

    Reflex renders each element attribute as a `key:value` string, sometimes
    wrapped in quotes, so `"aria-label":"Paper passages"` and `role:"region"`
    both have to parse to a key and a value.
    """
    parsed = {}
    for prop in props:
        match = re.match(r"""^["']?([\w-]+)["']?:(.*)$""", prop, re.DOTALL)
        if match:
            value = match.group(2).strip()
            if value.startswith('"') and value.endswith('"') and len(value) > 1:
                value = value[1:-1]
            parsed[match.group(1)] = value
    return parsed


def prop_present(props, key):
    return key in prop_map(props)


class ScrollRegionAccessibilityTests(unittest.TestCase):
    def test_every_scrollable_region_is_keyboard_reachable(self):
        regions = scrollable_regions(workspace().render())
        self.assertTrue(regions, "expected at least one scrollable region")
        for node, props in regions:
            tag = node.get("name", "")
            with self.subTest(tag=tag):
                # Without tabindex a scroll container is not in the tab order,
                # so the list is reachable by mouse only.
                self.assertTrue(
                    prop_present(props, "tabIndex"),
                    f"{tag} scrolls but has no tabIndex",
                )
                self.assertEqual(prop_map(props).get("tabIndex"), "0")

    def test_every_scrollable_region_is_a_named_landmark(self):
        for node, props in scrollable_regions(workspace().render()):
            tag = node.get("name", "")
            with self.subTest(tag=tag):
                self.assertTrue(
                    prop_present(props, "role"),
                    f"{tag} scrolls but has no role",
                )
                self.assertEqual(prop_map(props).get("role"), "region")
                label = prop_map(props).get("aria-label")
                self.assertTrue(
                    label, f"{tag} is a region landmark with no accessible name"
                )

    def test_the_reference_list_announces_its_state(self):
        """The reference list changes meaning once an audit has run.

        Its accessible name has to change with it, or a screen-reader user is
        told the same thing before and after verification.
        """
        labels = []
        for node, props in scrollable_regions(paper_reader().render()):
            label = prop_map(props).get("aria-label")
            if label:
                labels.append(label)
        self.assertEqual(len(labels), 2)
        # One branch is a static name, the other is a conditional in state.
        conditional = [p for p in labels if "?" in p]
        self.assertTrue(
            conditional,
            "the reference list's accessible name is not derived from state",
        )

    def test_scrollable_regions_show_a_visible_focus_ring(self):
        """A region that can be focused must also look focused."""
        for node, props in scrollable_regions(workspace().render()):
            classes = prop_map(props).get("className", "")
            with self.subTest(tag=node.get("name", "")):
                self.assertIn("focus-visible:outline", classes)


class FocusableControlTests(unittest.TestCase):
    def test_evidence_cards_expose_an_accessible_name(self):
        """Icon-only controls need a name, or they are silent to a screen reader."""
        tree = workspace().render()
        named = [
            props
            for _, props in scrollable_regions(tree)
            if prop_present(props, "aria-label")
        ]
        self.assertTrue(named)
        # The reader's own nav is the reference point for this contract.
        self.assertTrue(
            any("Paper passages" in " ".join(props) for props in named)
        )


if __name__ == "__main__":
    unittest.main()