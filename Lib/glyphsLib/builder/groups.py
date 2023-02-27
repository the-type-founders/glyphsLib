# Copyright 2016 Google Inc. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from collections import defaultdict
import os

from glyphsLib import classes
from .constants import (
    UFO_ORIGINAL_KERNING_GROUPS_KEY,
    UFO_GROUPS_NOT_IN_FEATURE_KEY,
    UFO_KERN_GROUP_PATTERN,
    BRACKET_GLYPH_RE,
)


def _get_glyphs_with_rtl_kerning(font):
    # Return a set of all glyph names that are referenced from font.kerningRTL,
    # either directly as single glyphs or as part of kerning groups.

    rtl_glyphs = set()
    if not font.kerningRTL:
        return rtl_glyphs

    # sets of group names keyed by {left,right}KerningGroup
    rtl_groups = defaultdict(set)
    glyph_kerning_attr = {"R": "leftKerningGroup", "L": "rightKerningGroup"}

    def mark_as_rtl(s, side):
        if s.startswith(f"@MMK_{side}_"):
            rtl_groups[glyph_kerning_attr[side]].add(s[7:])
        else:  # single glyph
            assert not s.startswith("@MMK_"), f"unexpected key in kerningRTL: {s}"
            rtl_glyphs.add(s)

    for kerning_id in {
        m.id if m.metricsSource is None else m.metricsSource.id for m in font.masters
    }:
        for kern1, subtable in font.kerningRTL.get(kerning_id, {}).items():
            mark_as_rtl(kern1, side="R")
            for kern2 in subtable.keys():
                mark_as_rtl(kern2, side="L")

    for glyph in font.glyphs.values():
        if glyph.name not in rtl_glyphs and any(
            getattr(glyph, attr) in rtl_groups[attr]
            for attr in glyph_kerning_attr.values()
        ):
            rtl_glyphs.add(glyph.name)

    return rtl_glyphs


def to_ufo_groups(self):
    # Build groups once and then apply to all UFOs.
    groups = defaultdict(list)

    # Classes usually go to the feature file, unless we have our custom flag
    group_names = None
    if UFO_GROUPS_NOT_IN_FEATURE_KEY in self.font.userData.keys():
        group_names = set(self.font.userData[UFO_GROUPS_NOT_IN_FEATURE_KEY])
    if group_names:
        for gsclass in self.font.classes.values():
            if gsclass.name in group_names:
                if gsclass.code:
                    groups[gsclass.name] = gsclass.code.split(" ")
                else:
                    # Empty group: using split like above would produce ['']
                    groups[gsclass.name] = []

    # Rebuild kerning groups from `left/rightKerningGroup`s
    # Use the original list of kerning groups as a base, to recover
    #  - the original ordering
    #  - the kerning groups of glyphs that were not in the font (which can be
    #    stored in a UFO but not by Glyphs)
    recovered = set()
    orig_groups = self.font.userData.get(UFO_ORIGINAL_KERNING_GROUPS_KEY)
    if orig_groups:
        for group, glyphs in orig_groups.items():
            if not glyphs:
                # Restore empty group
                groups[group] = []
            for glyph_name in glyphs:
                # Check that the original value is still valid
                match = UFO_KERN_GROUP_PATTERN.match(group)
                side = match.group(1)
                group_name = match.group(2)
                glyph = self.font.glyphs[glyph_name]
                if not glyph or getattr(glyph, _glyph_kerning_attr(side)) == group_name:
                    # The original grouping is still valid
                    groups[group].append(glyph_name)
                    # Remember not to add this glyph again later
                    # Thus the original position in the list is preserved
                    recovered.add((glyph_name, int(side)))

    # Read new/modified grouping values.
    # For glyphs that are used in Glyphs3's kerningRTL dict, take the opposite side:
    # NOTE: Not only this breaks Glyphs<=>UFO round-tripping, but also it makes
    # impossible for the same glyph to be kerned in both LTR and RTL dictionaries.
    # While this is unfortunate, we believe it's better than completely ignoring
    # all Glyphs3's RTL kerning.
    # For more info: https://github.com/googlefonts/glyphsLib/pull/778
    rtl_glyphs = _get_glyphs_with_rtl_kerning(self.font)
    for glyph in self.font.glyphs.values():
        is_rtl = glyph.name in rtl_glyphs
        for side in 1, 2:
            if (glyph.name, side) not in recovered:
                attr = _glyph_kerning_attr(side, is_rtl)
                group = getattr(glyph, attr)
                if group:
                    group = f"public.kern{side}.{group}"
                    groups[group].append(glyph.name)

    # Update all UFOs with the same info
    for source in self._sources.values():
        for name, glyphs in groups.items():
            # Shallow copy to prevent unexpected object sharing
            source.font.groups[name] = glyphs[:]


def to_glyphs_groups(self):
    # Build the GSClasses from the groups of the first UFO.
    groups = []
    for source in self._sources.values():
        for name, glyphs in source.font.groups.items():
            # Filter out all BRACKET glyphs first, as they are created at
            # to_designspace time to inherit glyph kerning to their bracket
            # variants. They need to be removed because Glpyhs.app handles that
            # on its own.
            glyphs = [name for name in glyphs if not BRACKET_GLYPH_RE.match(name)]
            if _is_kerning_group(name):
                _to_glyphs_kerning_group(self, name, glyphs)
            else:
                gsclass = classes.GSClass(name, " ".join(glyphs))
                self.font.classes.append(gsclass)
                groups.append(name)
        if self.minimize_ufo_diffs:
            self.font.userData[UFO_GROUPS_NOT_IN_FEATURE_KEY] = groups
        break

    # Check that other UFOs are identical and print a warning if not.
    for index, source in enumerate(self._sources.values()):
        if index == 0:
            reference_ufo = source.font
        else:
            _assert_groups_are_identical(self, reference_ufo, source.font)


def _is_kerning_group(name):
    return name.startswith(("public.kern1.", "public.kern2."))


def _to_glyphs_kerning_group(self, name, glyphs):
    if self.minimize_ufo_diffs:
        # Preserve ordering when going from UFO group
        # to left/rightKerningGroup disseminated in GSGlyphs
        # back to UFO group.
        if not self.font.userData.get(UFO_ORIGINAL_KERNING_GROUPS_KEY):
            self.font.userData[UFO_ORIGINAL_KERNING_GROUPS_KEY] = {}
        self.font.userData[UFO_ORIGINAL_KERNING_GROUPS_KEY][name] = glyphs

    match = UFO_KERN_GROUP_PATTERN.match(name)
    side = match.group(1)
    group_name = match.group(2)
    for glyph_name in glyphs:
        glyph = self.font.glyphs[glyph_name]
        if glyph:
            setattr(glyph, _glyph_kerning_attr(side), group_name)


def _glyph_kerning_attr(side, is_rtl=False):
    """Return rightKerningGroup or leftKerningGroup depending on the UFO
    group's side (1 or 2).

    Flip values for RTL kerning.
    """
    side = int(side)
    assert side in (1, 2), f"invalid kerning side: {side}"
    if is_rtl:
        side = 2 if side == 1 else 1
    if side == 1:
        return "rightKerningGroup"
    else:
        return "leftKerningGroup"


def _assert_groups_are_identical(self, reference_ufo, ufo):
    first_time = [True]  # Using a mutable as a non-local for closure below

    def _warn(message, *args):
        if first_time:
            self.logger.warning(
                "Using UFO `%s` as a reference for groups:",
                _ufo_logging_ref(reference_ufo),
            )
            first_time.clear()
        self.logger.warning("   " + message, *args)

    # Check for inconsistencies
    for group, glyphs in ufo.groups.items():
        if group not in reference_ufo.groups:
            _warn(
                "group `%s` from `%s` will be lost because it's not "
                "defined in the reference UFO",
                group,
                _ufo_logging_ref(ufo),
            )
            continue
        reference_glyphs = reference_ufo.groups[group]
        if set(glyphs) != set(reference_glyphs):
            _warn(
                "group `%s` from `%s` will not be stored accurately because "
                "it is different from the reference UFO",
                group,
                _ufo_logging_ref(ufo),
            )
            _warn("    reference = %s", " ".join(sorted(reference_glyphs)))
            _warn("    current   = %s", " ".join(sorted(glyphs)))


def _ufo_logging_ref(ufo):
    """Return a string that can identify this UFO in logs."""
    if ufo.path:
        return os.path.basename(ufo.path)
    return ufo.info.styleName
