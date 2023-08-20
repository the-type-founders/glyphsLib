#
# Copyright 2017 Google Inc. All Rights Reserved.
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


import os.path
import shutil
import sys
import tempfile
import unittest
import xml.etree.ElementTree as etree
from xmldiff import main, formatting

import defcon
from glyphsLib.builder.constants import GLYPHS_PREFIX
from glyphsLib.builder.instances import set_weight_class, set_width_class
from glyphsLib.classes import GSFont, GSFontMaster, GSInstance, GSFontInfoValue
from glyphsLib import to_designspace, to_glyphs
import ufoLib2


# Current limitation of glyphsLib for designspace to designspace round-trip:
# the designspace's axes, sources and instances must be as such:
#  - the axes' min, max must match extreme masters
#  - the axes' default must match the "regular master"
#  - the axes' mapping must have as many pairs as instances, each pair
#    matching the (userLoc, designLoc) of an instance. If there are no
#    instances, same requirement but with 1 pair/master
#
# Basically this is to say that the designspace must have been generated by
# glyphsLib in the first place.
#
# More general designspaces (like: axes that go farther than extreme masters,
# mapping with arbitrary numbers of pairs...) might be supported later, if/when
# Glyphs gets a UI to setup this information.
#
# REVIEW: check that the above makes sense


def makeFamily():
    m1 = makeMaster("Regular", weight=90.0)
    m2 = makeMaster("Black", weight=190.0)
    instances = [
        makeInstance("Regular", weight=("Regular", 400, 90)),
        makeInstance("Semibold", weight=("SemiBold", 600, 128)),
        makeInstance("Bold", weight=("Bold", 700, 151), is_bold=True),
        makeInstance("Black", weight=("Black", 900, 190)),
    ]
    return [m1, m2], instances


def makeMaster(styleName, weight=None, width=None):
    m = GSFontMaster()
    m.name = styleName
    if weight is not None:
        m.weightValue = weight
    if width is not None:
        m.widthValue = width
    return m


def makeInstance(
    name, weight=None, width=None, is_bold=None, is_italic=None, linked_style=None
):
    inst = GSInstance()
    inst.name = name
    if weight is not None:
        # Glyphs 2.5 stores the instance weight in two to three places:
        # 1. as a textual weight (such as “Bold”; no value defaults to
        #    "Regular");
        # 2. (optional) as numeric customParameters.weightClass (such as 700),
        #    which corresponds to OS/2.usWeightClass where 100 means Thin,
        #    400 means Regular, 700 means Bold, and 900 means Black;
        # 3. as numeric weightValue (such as 66.0), which typically is
        #    the stem width but can be anything that works for interpolation
        #    (no value defaults to 100).
        weightName, weightClass, interpolationWeight = weight
        if weightName is not None:
            inst.weight = weightName
        if weightClass is not None:
            inst.customParameters["weightClass"] = weightClass
        if interpolationWeight is not None:
            inst.weightValue = interpolationWeight
    if width is not None:
        # Glyphs 2.5 stores the instance width in two to three places:
        # 1. as a textual width (such as “Condensed”; no value defaults
        #    to "Medium (normal)");
        # 2. (optional) as numeric customParameters.widthClass (such as 5),
        #    which corresponds to OS/2.usWidthClass where 1 means Ultra-
        #    condensed, 5 means Medium (normal), and 9 means Ultra-expanded;
        # 3. as numeric widthValue (such as 79), which typically is
        #    a percentage of whatever the font designer considers “normal”
        #    but can be anything that works for interpolation (no value
        #    defaults to 100).
        widthName, widthClass, interpolationWidth = width
        if widthName is not None:
            inst.width = widthName
        if widthClass is not None:
            inst.customParameters["widthClass"] = widthClass
        if interpolationWidth is not None:
            inst.widthValue = interpolationWidth
    # TODO: Support custom axes; need to triple-check how these are encoded in
    # Glyphs files. Glyphs 3 will likely overhaul the representation of axes.
    if is_bold is not None:
        inst.isBold = is_bold
    if is_italic is not None:
        inst.isItalic = is_italic
    if linked_style is not None:
        inst.linkStyle = linked_style
    return inst


def makeInstanceDescriptor(*args, **kwargs):
    """Same as makeInstance but return the corresponding InstanceDescriptor."""
    ginst = makeInstance(*args, **kwargs)
    font = makeFont([makeMaster("Regular")], [ginst], "Family")
    doc = to_designspace(font)
    return doc, doc.instances[0]


def makeFont(masters, instances, familyName):
    font = GSFont()
    font.familyName = familyName
    font.masters = masters
    font.instances = instances
    return font


class DesignspaceTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.tmpdir)

    def write_to_tmp_path(self, doc, name):
        path = os.path.join(self.tmpdir, name)
        doc.write(path)
        return path

    def expect_designspace(self, doc, expected_name):
        dirname = os.path.dirname(__file__)
        expected_path = os.path.join(dirname, "..", "data", expected_name)
        return self._expect_designspace(doc, expected_path)

    def _expect_designspace(self, doc, expected_path):
        actual_path = self.write_to_tmp_path(doc, "generated.designspace")
        actual_diff = main.diff_files(
            actual_path, expected_path, formatter=formatting.DiffFormatter()
        )
        if len(actual_diff) != 0:
            expected_name = os.path.basename(expected_path)
            sys.stderr.write("%s discrepancies (per xmldiff):\n" % (expected_name))
            for line in actual_diff.split("\n"):
                sys.stderr.write("  %s" % (line))
            self.fail("*.designspace file is different from expected")

    def expect_designspace_roundtrip(self, doc):
        actual_path = self.write_to_tmp_path(doc, "original.designspace")
        font = to_glyphs(doc, minimize_ufo_diffs=True)
        rtdoc = to_designspace(font)
        return self._expect_designspace(rtdoc, actual_path)

    def test_basic(self):
        masters, instances = makeFamily()
        font = makeFont(masters, instances, "DesignspaceTest Basic")
        doc = to_designspace(font, instance_dir="out")
        self.expect_designspace(doc, "DesignspaceTestBasic.designspace")
        self.expect_designspace_roundtrip(doc)

    def test_inactive_from_exports(self):
        # Glyphs.app recognizes exports=0 as a flag for inactive instances.
        # https://github.com/googlefonts/glyphsLib/issues/129
        masters, instances = makeFamily()
        for inst in instances:
            if inst.name != "Semibold":
                inst.exports = False
        font = makeFont(masters, instances, "DesignspaceTest Inactive")
        doc = to_designspace(font, instance_dir="out")
        self.expect_designspace(doc, "DesignspaceTestInactive.designspace")
        self.expect_designspace_roundtrip(doc)

        # Although inactive instances are not exported by default,
        # all instances are exported when intending to roundtrip Glyphs->Glyphs
        doc = to_designspace(font, minimize_glyphs_diffs=True)
        self.assertEqual(4, len(doc.instances))

    def test_familyName(self):
        masters, _ = makeFamily()
        customFamily = makeInstance("Regular", weight=("Bold", 600, 151))
        customFamily.customParameters["familyName"] = "Custom Family"
        instances = [makeInstance("Regular", weight=("Regular", 400, 90)), customFamily]
        font = makeFont(masters, instances, "DesignspaceTest FamilyName")
        doc = to_designspace(font, instance_dir="out")
        self.expect_designspace(doc, "DesignspaceTestFamilyName.designspace")
        self.expect_designspace_roundtrip(doc)

    def test_fileName(self):
        masters, _ = makeFamily()
        customFileName = makeInstance("Regular", weight=("Bold", 600, 151))
        customFileName.customParameters["fileName"] = "Custom FileName"
        instances = [
            makeInstance("Regular", weight=("Regular", 400, 90)),
            customFileName,
        ]
        font = makeFont(masters, instances, "DesignspaceTest FamilyName")
        doc = to_designspace(font, instance_dir="out")
        self.expect_designspace(doc, "DesignspaceTestFileName.designspace")
        self.expect_designspace_roundtrip(doc)

    def test_noRegularMaster(self):
        # Currently, fontTools.varLib fails to build variable fonts
        # if the default axis value does not happen to be at the
        # location of one of the interpolation masters.
        # glyhpsLib tries to work around this downstream limitation.
        masters = [makeMaster("Thin", weight=26), makeMaster("Black", weight=190)]
        instances = [
            makeInstance("Black", weight=("Black", 900, 190)),
            makeInstance("Regular", weight=("Regular", 400, 90)),
            makeInstance("Bold", weight=("Thin", 100, 26)),
        ]
        font = makeFont(masters, instances, "NoRegularMaster")
        designspace = to_designspace(font, instance_dir="out")
        path = self.write_to_tmp_path(designspace, "noregular.designspace")
        doc = etree.parse(path)
        weightAxis = doc.find('axes/axis[@tag="wght"]')
        self.assertEqual(weightAxis.attrib["minimum"], "100")
        self.assertEqual(weightAxis.attrib["default"], "100")  # not 400
        self.assertEqual(weightAxis.attrib["maximum"], "900")

        self.expect_designspace_roundtrip(designspace)

    def test_postscriptFontNameCustomParameter(self):
        master = makeMaster("Master")
        thin, black = makeInstance("Thin"), makeInstance("Black")
        black.customParameters["postscriptFontName"] = "PSNameTest-Superfat"
        font = makeFont([master], [thin, black], "PSNameTest")
        designspace = to_designspace(font, instance_dir="out")
        path = self.write_to_tmp_path(designspace, "psname.designspace")
        d = etree.parse(path)

        def psname(doc, style):
            inst = doc.find('instances/instance[@stylename="%s"]' % style)
            return inst.attrib.get("postscriptfontname")

        self.assertIsNone(psname(d, "Thin"))
        self.assertEqual(psname(d, "Black"), "PSNameTest-Superfat")

        self.expect_designspace_roundtrip(designspace)

    def test_postscriptFontNameProperty(self):
        master = makeMaster("Master")
        thin, black = makeInstance("Thin"), makeInstance("Black")
        black.properties.append(
            GSFontInfoValue("postscriptFontName", "PSNameTest-Superfat")
        )
        font = makeFont([master], [thin, black], "PSNameTest")
        designspace = to_designspace(font, instance_dir="out")
        path = self.write_to_tmp_path(designspace, "psname.designspace")
        d = etree.parse(path)

        def psname(doc, style):
            inst = doc.find('instances/instance[@stylename="%s"]' % style)
            return inst.attrib.get("postscriptfontname")

        self.assertIsNone(psname(d, "Thin"))
        self.assertEqual(psname(d, "Black"), "PSNameTest-Superfat")

        self.expect_designspace_roundtrip(designspace)

    def test_instanceOrder(self):
        # The generated *.designspace file should place instances
        # in the same order as they appear in the original source.
        # https://github.com/googlefonts/glyphsLib/issues/113
        masters, _ = makeFamily()
        instances = [
            makeInstance("Black", weight=("Black", 900, 190)),
            makeInstance("Regular", weight=("Regular", 400, 90)),
            makeInstance("Bold", weight=("Bold", 700, 151), is_bold=True),
        ]
        font = makeFont(masters, instances, "DesignspaceTest InstanceOrder")
        doc = to_designspace(font, instance_dir="out")
        self.expect_designspace(doc, "DesignspaceTestInstanceOrder.designspace")
        self.expect_designspace_roundtrip(doc)

    def test_twoAxes(self):
        # In NotoSansArabic-MM.glyphs, the regular width only contains
        # parameters for the weight axis. For the width axis, glyphsLib
        # should use 100 as default value (just like Glyphs.app does).
        familyName = "DesignspaceTest TwoAxes"
        masters = [
            makeMaster("Regular", weight=90),
            makeMaster("Black", weight=190),
            makeMaster("Thin", weight=26),
            makeMaster("ExtraCond", weight=90, width=70),
            makeMaster("ExtraCond Black", weight=190, width=70),
            makeMaster("ExtraCond Thin", weight=26, width=70),
        ]
        instances = [
            makeInstance("Thin", weight=("Thin", 100, 26)),
            makeInstance("Regular", weight=("Regular", 400, 90)),
            makeInstance("Semibold", weight=("SemiBold", 600, 128)),
            makeInstance("Black", weight=("Black", 900, 190)),
            makeInstance(
                "ExtraCondensed Thin",
                weight=("Thin", 100, 26),
                width=("Extra Condensed", 2, 70),
            ),
            makeInstance(
                "ExtraCondensed",
                weight=("Regular", 400, 90),
                width=("Extra Condensed", 2, 70),
            ),
            makeInstance(
                "ExtraCondensed Black",
                weight=("Black", 900, 190),
                width=("Extra Condensed", 2, 70),
            ),
        ]
        font = makeFont(masters, instances, familyName)
        doc = to_designspace(font, instance_dir="out")
        self.expect_designspace(doc, "DesignspaceTestTwoAxes.designspace")
        self.expect_designspace_roundtrip(doc)

    def test_variationFontOrigin(self):
        # Glyphs 2.4.1 introduced a custom parameter “Variation Font Origin”
        # to specify which master should be considered the origin.
        # https://glyphsapp.com/blog/glyphs-2-4-1-released
        masters = [
            makeMaster("Thin", weight=26),
            makeMaster("Regular", weight=100),
            makeMaster("Medium", weight=111),
            makeMaster("Black", weight=190),
        ]
        instances = [
            makeInstance("Black", weight=("Black", 900, 190)),
            makeInstance("Medium", weight=("Medium", 444, 111)),
            makeInstance("Regular", weight=("Regular", 400, 100)),
            makeInstance("Thin", weight=("Thin", 100, 26)),
        ]
        font = makeFont(masters, instances, "Family")
        font.customParameters["Variation Font Origin"] = "Medium"
        designspace = to_designspace(font, instance_dir="out")
        path = self.write_to_tmp_path(designspace, "varfontorig.designspace")
        doc = etree.parse(path)
        medium = doc.find('sources/source[@stylename="Medium"]')
        self.assertEqual(medium.find("lib").attrib["copy"], "1")
        weightAxis = doc.find('axes/axis[@tag="wght"]')
        self.assertEqual(weightAxis.attrib["default"], "444")

        self.expect_designspace_roundtrip(designspace)

    def test_designspace_name(self):
        doc = to_designspace(
            makeFont(
                [makeMaster("Regular", weight=100), makeMaster("Bold", weight=190)],
                [],
                "Family Name",
            )
        )
        # no shared base style name, only write the family name
        self.assertEqual(doc.filename, "FamilyName.designspace")

        doc = to_designspace(
            makeFont(
                [
                    makeMaster("Italic", weight=100),
                    makeMaster("Bold Italic", weight=190),
                ],
                [],
                "Family Name",
            )
        )
        # 'Italic' is the base style; append to designspace name
        self.assertEqual(doc.filename, "FamilyName-Italic.designspace")

    def test_instance_filtering_by_family_name(self):
        # See https://github.com/googlefonts/fontmake/issues/257
        path = os.path.join(
            os.path.dirname(__file__), "..", "data", "MontserratStrippedDown.glyphs"
        )
        font = GSFont(path)

        # By default (no special parameter), all instances are exported
        designspace_all = to_designspace(font)
        assert len(designspace_all.instances) == 18

        # If we specify that we want the same familyName as the masters,
        # we only get instances that have that same family name, and the
        # masters are copied as-is. (basically a subset of the previous doc)
        designspace_no_alternates = to_designspace(font, family_name="Montserrat")
        assert len(designspace_no_alternates.instances) == 9

        # If we specify the alternate family name, we only get the instances
        # that have that family name, and the masters are renamed to have the
        # given family name.
        designspace_alternates = to_designspace(
            font, family_name="Montserrat Alternates"
        )
        assert designspace_alternates.sources[0].familyName == "Montserrat Alternates"
        assert (
            designspace_alternates.sources[0].font.info.familyName
            == "Montserrat Alternates"
        )
        assert len(designspace_alternates.instances) == 9


WEIGHT_CLASS_KEY = GLYPHS_PREFIX + "weightClass"
WIDTH_CLASS_KEY = GLYPHS_PREFIX + "widthClass"


class SetWeightWidthClassesTestBase(object):
    ufo_module = None  # subclasses must override this

    def test_no_weight_class(self):
        ufo = self.ufo_module.Font()
        # name here says "Bold", however no explicit weightClass
        # is assigned
        doc, instance = makeInstanceDescriptor("Bold")
        set_weight_class(ufo, doc, instance)
        # the default OS/2 weight class is set
        self.assertEqual(ufo.info.openTypeOS2WeightClass, 400)

    def test_weight_class(self):
        ufo = self.ufo_module.Font()
        doc, data = makeInstanceDescriptor("Bold", weight=("Bold", None, 150))

        set_weight_class(ufo, doc, data)
        self.assertEqual(ufo.info.openTypeOS2WeightClass, 700)

    def test_explicit_default_weight(self):
        ufo = self.ufo_module.Font()
        doc, data = makeInstanceDescriptor("Regular", weight=("Regular", None, 100))

        set_weight_class(ufo, doc, data)
        # the default OS/2 weight class is set
        self.assertEqual(ufo.info.openTypeOS2WeightClass, 400)

    def test_no_width_class(self):
        ufo = self.ufo_module.Font()
        # no explicit widthClass set, instance name doesn't matter
        doc, data = makeInstanceDescriptor("Normal")
        set_width_class(ufo, doc, data)
        # the default OS/2 width class is set
        self.assertEqual(ufo.info.openTypeOS2WidthClass, 5)

    def test_width_class(self):
        ufo = self.ufo_module.Font()
        doc, data = makeInstanceDescriptor("Condensed", width=("Condensed", 3, 80))

        set_width_class(ufo, doc, data)
        self.assertEqual(ufo.info.openTypeOS2WidthClass, 3)

    def test_explicit_default_width(self):
        ufo = self.ufo_module.Font()
        doc, data = makeInstanceDescriptor("Regular", width=("Medium (normal)", 5, 100))

        set_width_class(ufo, doc, data)
        # the default OS/2 width class is set
        self.assertEqual(ufo.info.openTypeOS2WidthClass, 5)

    def test_weight_and_width_class(self):
        ufo = self.ufo_module.Font()
        doc, data = makeInstanceDescriptor(
            "SemiCondensed ExtraBold",
            weight=("ExtraBold", None, 160),
            width=("SemiCondensed", 4, 90),
        )

        set_weight_class(ufo, doc, data)
        set_width_class(ufo, doc, data)

        self.assertEqual(ufo.info.openTypeOS2WeightClass, 800)
        self.assertEqual(ufo.info.openTypeOS2WidthClass, 4)

    def test_unknown_ui_string_but_defined_weight_class(self):
        ufo = self.ufo_module.Font()
        # "DemiLight" is not among the predefined weight classes listed in
        # Glyphs.app/Contents/Frameworks/GlyphsCore.framework/Versions/A/
        # Resources/weights.plist
        # NOTE It is not possible from the user interface to set a custom
        # string as instance 'weightClass' since the choice is constrained
        # by a drop-down menu.
        doc, data = makeInstanceDescriptor(
            "DemiLight Italic", weight=("DemiLight", 350, 70)
        )

        set_weight_class(ufo, doc, data)

        # Here we have set the weightClass to 350 so even though the string
        # is wrong, our value of 350 should be used.
        self.assertTrue(ufo.info.openTypeOS2WeightClass == 350)

    def test_unknown_weight_class(self):
        ufo = self.ufo_module.Font()
        # "DemiLight" is not among the predefined weight classes listed in
        # Glyphs.app/Contents/Frameworks/GlyphsCore.framework/Versions/A/
        # Resources/weights.plist
        # NOTE It is not possible from the user interface to set a custom
        # string as instance 'weightClass' since the choice is constrained
        # by a drop-down menu.
        doc, data = makeInstanceDescriptor(
            "DemiLight Italic", weight=("DemiLight", None, 70)
        )

        set_weight_class(ufo, doc, data)

        # the default OS/2 weight class is set
        self.assertEqual(ufo.info.openTypeOS2WeightClass, 400)


class SetWeightWidthClassesTestUfoLib2(
    SetWeightWidthClassesTestBase, unittest.TestCase
):
    ufo_module = ufoLib2


class SetWeightWidthClassesTestDefcon(SetWeightWidthClassesTestBase, unittest.TestCase):
    ufo_module = defcon


if __name__ == "__main__":
    sys.exit(unittest.main())
