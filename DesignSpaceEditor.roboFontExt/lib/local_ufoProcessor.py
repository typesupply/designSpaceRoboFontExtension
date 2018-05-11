
# coding: utf-8
from __future__ import print_function, division, absolute_import

from ufoLib import fontInfoAttributesVersion1, fontInfoAttributesVersion2, fontInfoAttributesVersion3
from pprint import pprint
import logging

"""
    
    A subclassed DesignSpaceDocument that can
        - process the document and generate finished UFOs with MutatorMath.
        - read and write documents
        - bypass and eventually replace the mutatormath ufo generator.

"""


from fontTools.designspaceLib import DesignSpaceDocument, SourceDescriptor, InstanceDescriptor, AxisDescriptor, RuleDescriptor, processRules
from defcon.objects.font import Font
from defcon.pens.transformPointPen import TransformPointPen
from defcon.objects.component import _defaultTransformation
import defcon
from fontMath.mathGlyph import MathGlyph
from fontMath.mathInfo import MathInfo
from fontMath.mathKerning import MathKerning
from mutatorMath.objects.mutator import buildMutator
from mutatorMath.objects.location import biasFromLocations, Location
import plistlib
import os

"""

    Swap the contents of two glyphs.
        - contours
        - components
        - width
        - group membership
        - kerning

    + Remap components so that glyphs that reference either of the swapped glyphs maintain appearance
    + Keep the unicode value of the original glyph.
    
    Notes
    Parking the glyphs under a swapname is a bit lazy, but at least it guarantees the glyphs have the right parent.

"""


""" These are some UFO specific tools for use with Mutator.


    build() is a convenience function for reading and executing a designspace file.
        documentPath:               filepath to the .designspace document
        outputUFOFormatVersion:     ufo format for output
        verbose:                    True / False for lots or no feedback
        logPath:                    filepath to a log file
        progressFunc:               an optional callback to report progress.
                                    see mutatorMath.ufo.tokenProgressFunc

"""

def build(
        documentPath,
        outputUFOFormatVersion=3,
        roundGeometry=True,
        verbose=True,           # not supported
        logPath=None,           # not supported
        progressFunc=None,      # not supported
        processRules=True,
        logger=None
        ):
    """
        Simple builder for UFO designspaces.
    """
    import os, glob
    if os.path.isdir(documentPath):
        # process all *.designspace documents in this folder
        todo = glob.glob(os.path.join(documentPath, "*.designspace"))
    else:
        # process the 
        todo = [documentPath]
    results = []
    for path in todo:
        reader = DesignSpaceProcessor(ufoVersion=outputUFOFormatVersion)
        reader.roundGeometry = roundGeometry
        reader.read(path)
        try:
            r = reader.generateUFO(processRules=processRules)
            results.append(r)
        except:
            if logger:
                logger.exception("ufoProcessor error")
        #results += reader.generateUFO(processRules=processRules)
        reader = None
    return results

def getUFOVersion(ufoPath):
    # <?xml version="1.0" encoding="UTF-8"?>
    # <!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
    # <plist version="1.0">
    # <dict>
    #   <key>creator</key>
    #   <string>org.robofab.ufoLib</string>
    #   <key>formatVersion</key>
    #   <integer>2</integer>
    # </dict>
    # </plist>
    metaInfoPath = os.path.join(ufoPath, u"metainfo.plist")
    p = plistlib.readPlist(metaInfoPath)
    return p.get('formatVersion')

def swapGlyphNames(font, oldName, newName, swapNameExtension = "_______________swap"):
    if not oldName in font or not newName in font:
        return None
    swapName = oldName + swapNameExtension
    # park the old glyph 
    if not swapName in font:
        font.newGlyph(swapName)
    # swap the outlines
    font[swapName].clear()
    p = font[swapName].getPointPen()
    font[oldName].drawPoints(p)
    font[swapName].width = font[oldName].width
    # lib?
    
    font[oldName].clear()
    p = font[oldName].getPointPen()
    font[newName].drawPoints(p)
    font[oldName].width = font[newName].width
    
    font[newName].clear()
    p = font[newName].getPointPen()
    font[swapName].drawPoints(p)
    font[newName].width = font[swapName].width
    
    # remap the components
    for g in font:
        for c in g.components:
           if c.baseGlyph == oldName:
               c.baseGlyph = swapName
           continue
    for g in font:
        for c in g.components:
           if c.baseGlyph == newName:
               c.baseGlyph = oldName
           continue
    for g in font:
        for c in g.components:
           if c.baseGlyph == swapName:
               c.baseGlyph = newName
   
    # change the names in groups
    # the shapes will swap, that will invalidate the kerning
    # so the names need to swap in the kerning as well.
    newKerning = {}
    for first, second in font.kerning.keys():
        value = font.kerning[(first,second)]
        if first == oldName:
            first = newName
        elif first == newName:
            first = oldName
        if second == oldName:
            second = newName
        elif second == newName:
            second = oldName
        newKerning[(first, second)] = value
    font.kerning.clear()
    font.kerning.update(newKerning)
            
    for groupName, members in font.groups.items():
        newMembers = []
        for name in members:
            if name == oldName:
                newMembers.append(newName)
            elif name == newName:
                newMembers.append(oldName)
            else:
                newMembers.append(name)
        font.groups[groupName] = newMembers
    
    remove = []
    for g in font:
        if g.name.find(swapNameExtension)!=-1:
            remove.append(g.name)
    for r in remove:
        del font[r]

class DecomposePointPen(object):
    
    def __init__(self, glyphSet, outPointPen):
        self._glyphSet = glyphSet
        self._outPointPen = outPointPen
        self.beginPath = outPointPen.beginPath
        self.endPath = outPointPen.endPath
        self.addPoint = outPointPen.addPoint
        
    def addComponent(self, baseGlyphName, transformation):
        if baseGlyphName in self._glyphSet:
            baseGlyph = self._glyphSet[baseGlyphName]
            if transformation == _defaultTransformation:
                baseGlyph.drawPoints(self)
            else:
                transformPointPen = TransformPointPen(self, transformation)
                baseGlyph.drawPoints(transformPointPen)


class DesignSpaceProcessor(DesignSpaceDocument):
    """
        builder of glyphs from designspaces
        validate the data
        if it works, make a generating thing
    """

    fontClass = defcon.Font
    glyphClass = defcon.Glyph
    libClass = defcon.Lib
    glyphContourClass = defcon.Contour
    glyphPointClass = defcon.Point
    glyphComponentClass = defcon.Component
    glyphAnchorClass = defcon.Anchor
    kerningClass = defcon.Kerning
    groupsClass = defcon.Groups
    infoClass = defcon.Info
    featuresClass = defcon.Features

    mathInfoClass = MathInfo
    mathGlyphClass = MathGlyph
    mathKerningClass = MathKerning

    braceLayerNamePattern = u"#brace "
    braceLocationLibKey = "designspace.location"
    braceGlyphSourceKey = "designspace.glyph.source"


    def __init__(self, readerClass=None, writerClass=None, fontClass=None, ufoVersion=3):
        super(DesignSpaceProcessor, self).__init__(readerClass=readerClass, writerClass=writerClass)
        self.ufoVersion = ufoVersion         # target UFO version
        self.roundGeometry = False
        self._glyphMutators = {}
        self._infoMutator = None
        self._kerningMutator = None
        self._preppedAxes = None
        self.fonts = {}
        self._fontsLoaded = False
        self.glyphNames = []     # list of all glyphnames
        self.processRules = True
        self.problems = []  # receptacle for problem notifications. Not big enough to break, but also not small enough to ignore.

    def generateUFO(self, processRules=True):
        # makes the instances
        # option to execute the rules
        # make sure we're not trying to overwrite a newer UFO format
        self.loadFonts()
        self.checkDefault()
        v = 0
        for instanceDescriptor in self.instances:
            if instanceDescriptor.path is None:
                continue
            font = self.makeInstance(instanceDescriptor, processRules)
            folder = os.path.dirname(instanceDescriptor.path)
            path = instanceDescriptor.path
            if not os.path.exists(folder):
                os.makedirs(folder)
            if os.path.exists(path):
                existingUFOFormatVersion = getUFOVersion(path)
                if existingUFOFormatVersion > self.ufoVersion:
                    self.problems.append(u"Can’t overwrite existing UFO%d with UFO%d."%(existingUFOFormatVersion, self.ufoVersion))
                    continue
            else:
                font.save(path, self.ufoVersion)
                self.problems.append("Generated %s as UFO%d"%(os.path.basename(path), self.ufoVersion))

    def getInfoMutator(self):
        """ Returns a info mutator """
        if self._infoMutator:
            return self._infoMutator
        infoItems = []
        for sourceDescriptor in self.sources:
            loc = Location(sourceDescriptor.location)
            sourceFont = self.fonts[sourceDescriptor.name]
            infoItems.append((loc, self.mathInfoClass(sourceFont.info)))
        bias, self._infoMutator = buildMutator(infoItems, axes=self._preppedAxes, bias=self.defaultLoc)
        return self._infoMutator

    def getKerningMutator(self):
        """ Return a kerning mutator, collect the sources, build mathGlyphs. """
        if self._kerningMutator:
            return self._kerningMutator
        kerningItems = []
        for sourceDescriptor in self.sources:
            loc = Location(sourceDescriptor.location)
            sourceFont = self.fonts[sourceDescriptor.name]
            # this makes assumptions about the groups of all sources being the same. 
            kerningItems.append((loc, self.mathKerningClass(sourceFont.kerning, sourceFont.groups)))
        bias, self._kerningMutator = buildMutator(kerningItems, axes=self._preppedAxes, bias=self.defaultLoc)
        return self._kerningMutator

    def _collectBraceGlyphs(self, glyphName):
        """ 
            - Collect the brace glyphs and their locations.
            - The layer API is rather different between fontparts and defcon. 
            - Just suck it up and make it work here. 
        """
        braces = []
        defaultFont = self.getNeutralFont()
        glyph = defaultFont[glyphName]
        if hasattr(glyph, "layers"):
            #print("_collectBraceGlyphs: fontparts")
            # fontParts
            for layerGlyph in glyph.layers:
                #print("from fontparts", layerGlyph, layerGlyph.layer.name, layerGlyph.lib.get(self.braceLocationLibKey))
                locFromLib = layerGlyph.lib.get(self.braceLocationLibKey)
                if locFromLib is not None:
                    sourceInfo = dict(source=defaultFont.path, glyphName=glyphName, layerName=layerGlyph.layer.name, location=locFromLib, sourceName=self.default.name)
                    braces.append((locFromLib, layerGlyph, sourceInfo))
        elif hasattr(defaultFont, "layers"):
            #print("_collectBraceGlyphs: defcon")
            # defcon
            if hasattr(defaultFont.layers, "layerOrder"):
                for layerName in defaultFont.layers.layerOrder:
                    layer = defaultFont.layers[layerName]
                    if glyphName in layer:
                        layerGlyph = layer[glyphName]
                    locFromLib = layerGlyph.lib.get(self.braceLocationLibKey)
                    if locFromLib is not None:
                        # collect the source info here so an editor can find the right source to open
                        if self.default is not None:
                            name = self.default.name
                        else:
                            name = "xxxxxx"
                        sourceInfo = dict(source=defaultFont.path, glyphName=glyphName, layerName=layerName, location=locFromLib, sourceName=name)
                        braces.append((locFromLib, layerGlyph, sourceInfo))
        return braces

    def getGlyphMutator(self, glyphName, decomposeComponents=False, includeBraces=True, fromCache=True):
        cacheKey = (glyphName, decomposeComponents, includeBraces)
        if cacheKey in self._glyphMutators and fromCache:
            return self._glyphMutators[cacheKey]
        items = self.collectMastersForGlyph(glyphName, decomposeComponents=decomposeComponents, includeBraces=includeBraces)
        items = [(a,self.mathGlyphClass(b)) for a, b, c in items]
        bias, self._glyphMutators[cacheKey] = buildMutator(items, axes=self._preppedAxes, bias=self.defaultLoc)
        return self._glyphMutators[cacheKey]

    def collectMastersForGlyph(self, glyphName, decomposeComponents=False, includeBraces=True):
        """ Return a glyph mutator.defaultLoc
            decomposeComponents = True causes the source glyphs to be decomposed first
            before building the mutator. That gives you instances that do not depend
            on a complete font. If you're calculating previews for instance.
        """
        items = []
        for sourceDescriptor in self.sources:
            loc = Location(sourceDescriptor.location)
            f = self.fonts[sourceDescriptor.name]
            if glyphName in sourceDescriptor.mutedGlyphNames:
                continue
            if not glyphName in f:
                # log this>
                continue
            sourceGlyphObject = f[glyphName]
            if decomposeComponents:
                temp = self.glyphClass()
                p = temp.getPointPen()
                dpp = DecomposePointPen(f, p)
                sourceGlyphObject.drawPoints(dpp)
                temp.width = sourceGlyphObject.width
                temp.name = sourceGlyphObject.name
                #temp.lib = sourceGlyphObject.lib
                processThis = temp
            else:
                processThis = sourceGlyphObject
            sourceInfo = dict(source=f.path, glyphName=glyphName, layerName="foreground", location=sourceDescriptor.location, sourceName=sourceDescriptor.name)
            items.append((loc, self.mathGlyphClass(processThis), sourceInfo))
            #items.append((loc, processThis, sourceInfo))
        # XXXX find open locations and generate supports here. 
        if includeBraces:
            braces = self._collectBraceGlyphs(glyphName)
            if braces and not glyphName in sourceDescriptor.mutedGlyphNames:
                #print("xxxx braces", braces)
                for locDict, braceGlyph, sourceInfo in braces:
                    loc = Location(locDict)
                    # do we need decomposition here?
                    #print("adding brace", loc, braceGlyph)
                    items.append((loc, self.mathGlyphClass(braceGlyph), sourceInfo))
                    #items.append((loc, braceGlyph, sourceInfo))
        return items

    def getNeutralFont(self):
        # Return a font object for the neutral font
        # self.fonts[self.default.name] ?
        neutralLoc = self.newDefaultLocation()
        for sd in self.sources:
            if sd.location == neutralLoc:
                if sd.name in self.fonts:
                    return self.fonts[sd.name]
        return None

    def loadFonts(self, reload=False):
        # Load the fonts and find the default candidate based on the info flag
        if self._fontsLoaded and not reload:
            return
        names = set()
        for sourceDescriptor in self.sources:
            if not sourceDescriptor.name in self.fonts:
                if os.path.exists(sourceDescriptor.path):
                    self.fonts[sourceDescriptor.name] = self._instantiateFont(sourceDescriptor.path)
                    self.problems.append("loaded master from %s, format %d"%(sourceDescriptor.path, getUFOVersion(sourceDescriptor.path)))
                    names = names | set(self.fonts[sourceDescriptor.name].keys())
                else:
                    self.fonts[sourceDescriptor.name] = None
                    self.problems.append("can't load master from %s"%(sourceDescriptor.path))
        self.glyphNames = list(names)
        self._fontsLoaded = True

    def makeInstance(self, instanceDescriptor, doRules=False, glyphNames=None):
        """ Generate a font object for this instance """
        font = self._instantiateFont(None)
        self._preppedAxes = self._prepAxesForBender()
        # make fonty things here
        loc = Location(instanceDescriptor.location)
        # groups, 
        if hasattr(self.fonts[self.default.name], "kerningGroupConversionRenameMaps"):
            renameMap = self.fonts[self.default.name].kerningGroupConversionRenameMaps
            self.problems.append("renameMap %s"%renameMap)
        else:
            renameMap = {}
        font.kerningGroupConversionRenameMaps = renameMap
        # make the kerning
        if instanceDescriptor.kerning:
            try:
                self.getKerningMutator().makeInstance(loc).extractKerning(font)
            except:
                self.problems.append("Could not make kerning for %s"%loc)
        # make the info
        if instanceDescriptor.info:
            try:
                self.getInfoMutator().makeInstance(loc).extractInfo(font.info)
                info = self._infoMutator.makeInstance(loc)
                info.extractInfo(font.info)
                font.info.familyName = instanceDescriptor.familyName
                font.info.styleName = instanceDescriptor.styleName
                font.info.postScriptFontName = instanceDescriptor.postScriptFontName
                font.info.styleMapFamilyName = instanceDescriptor.styleMapFamilyName
                font.info.styleMapStyleName = instanceDescriptor.styleMapStyleName
                # localised names need to go to the right openTypeNameRecords
                # records = []
                # nameID = 1
                # platformID = 
                # for languageCode, name in instanceDescriptor.localisedStyleMapFamilyName.items():
                #    # Name ID 1 (font family name) is found at the generic styleMapFamily attribute.
                #    records.append((nameID, ))

            except:
                self.problems.append("Could not make fontinfo for %s"%loc)
        # copied info
        for sourceDescriptor in self.sources:
            if sourceDescriptor.copyInfo:
                # this is the source
                self._copyFontInfo(self.fonts[sourceDescriptor.name].info, font.info)
            if sourceDescriptor.copyLib:
                # excplicitly copy the font.lib items
                for key, value in self.fonts[sourceDescriptor.name].lib.items():
                    font.lib[key] = value
            if sourceDescriptor.copyFeatures:
                featuresText = self.fonts[sourceDescriptor.name].features.text
                if isinstance(featuresText, str):
                    font.features.text = u""+featuresText
                elif isinstance(featuresText, unicode):
                    font.features.text = featuresText
        # glyphs
        if glyphNames:
            selectedGlyphNames = glyphNames
        else:
            selectedGlyphNames = self.glyphNames
        # add the glyphnames to the font.lib['public.glyphOrder']
        if not 'public.glyphOrder' in font.lib.keys():
            font.lib['public.glyphOrder'] = selectedGlyphNames
        for glyphName in selectedGlyphNames:
            try:
                glyphMutator = self.getGlyphMutator(glyphName)
            except:
                self.problems.append("Could not make mutator for glyph %s"%glyphName)
                continue
            if glyphName in instanceDescriptor.glyphs.keys():
                # reminder: this is what the glyphData can look like
                # {'instanceLocation': {'custom': 0.0, 'weight': 824.0},
                #  'masters': [{'font': 'master.Adobe VF Prototype.Master_0.0',
                #               'glyphName': 'dollar.nostroke',
                #               'location': {'custom': 0.0, 'weight': 0.0}},
                #              {'font': 'master.Adobe VF Prototype.Master_1.1',
                #               'glyphName': 'dollar.nostroke',
                #               'location': {'custom': 0.0, 'weight': 368.0}},
                #              {'font': 'master.Adobe VF Prototype.Master_2.2',
                #               'glyphName': 'dollar.nostroke',
                #               'location': {'custom': 0.0, 'weight': 1000.0}},
                #              {'font': 'master.Adobe VF Prototype.Master_3.3',
                #               'glyphName': 'dollar.nostroke',
                #               'location': {'custom': 100.0, 'weight': 1000.0}},
                #              {'font': 'master.Adobe VF Prototype.Master_0.4',
                #               'glyphName': 'dollar.nostroke',
                #               'location': {'custom': 100.0, 'weight': 0.0}},
                #              {'font': 'master.Adobe VF Prototype.Master_4.5',
                #               'glyphName': 'dollar.nostroke',
                #               'location': {'custom': 100.0, 'weight': 368.0}}],
                #  'unicodes': [36]}
                glyphData = instanceDescriptor.glyphs[glyphName]
            else:
                glyphData = {}
            font.newGlyph(glyphName)
            font[glyphName].clear()
            if glyphData.get('mute', False):
                # mute this glyph, skip
                continue
            glyphInstanceLocation = Location(glyphData.get("instanceLocation", instanceDescriptor.location))
            try:
                uniValues = glyphMutator[()][0].unicodes
            except IndexError:
                uniValues = []
            glyphInstanceUnicodes = glyphData.get("unicodes", uniValues)
            note = glyphData.get("note")
            if note:
                font[glyphName] = note
            masters = glyphData.get("masters", None)
            if masters:
                items = []
                for glyphMaster in masters:
                    sourceGlyphFont = glyphMaster.get("font")
                    sourceGlyphName = glyphMaster.get("glyphName", glyphName)
                    m = self.fonts.get(sourceGlyphFont)
                    if not sourceGlyphName in m:
                        continue
                    sourceGlyph = MathGlyph(m[sourceGlyphName])
                    sourceGlyphLocation = Location(glyphMaster.get("location"))
                    items.append((sourceGlyphLocation, sourceGlyph))
                bias, glyphMutator = buildMutator(items, axes=self._preppedAxes, bias=self.defaultLoc)
            try:
                glyphInstanceObject = glyphMutator.makeInstance(glyphInstanceLocation)
            except IndexError:
                # alignment problem with the data?
                print("Error making instance %s"%glyphName)
                continue
            font.newGlyph(glyphName)
            font[glyphName].clear()
            if self.roundGeometry:
                try:
                    glyphInstanceObject = glyphInstanceObject.round()
                except AttributeError:
                    pass
            try:
                glyphInstanceObject.extractGlyph(font[glyphName], onlyGeometry=True)
            except TypeError:
                # this causes ruled glyphs to end up in the wrong glyphname
                # but defcon2 objects don't support it
                pPen = font[glyphName].getPointPen()
                font[glyphName].clear()
                glyphInstanceObject.drawPoints(pPen)
            font[glyphName].width = glyphInstanceObject.width
            font[glyphName].unicodes = glyphInstanceUnicodes
        if doRules:
            resultNames = processRules(self.rules, loc, self.glyphNames)
            for oldName, newName in zip(self.glyphNames, resultNames):
                if oldName != newName:
                    swapGlyphNames(font, oldName, newName)
        # copy the glyph lib?
        #for sourceDescriptor in self.sources:
        #    if sourceDescriptor.copyLib:
        #        pass
        #    pass
        # store designspace location in the font.lib
        font.lib['designspace'] = list(instanceDescriptor.location.items())
        return font

    def _instantiateFont(self, path):
        """ Return a instance of a font object with all the given subclasses"""
        try:
            return self.fontClass(path,
                libClass=self.libClass,
                kerningClass=self.kerningClass,
                groupsClass=self.groupsClass,
                infoClass=self.infoClass,
                featuresClass=self.featuresClass,
                glyphClass=self.glyphClass,
                glyphContourClass=self.glyphContourClass,
                glyphPointClass=self.glyphPointClass,
                glyphComponentClass=self.glyphComponentClass,
                glyphAnchorClass=self.glyphAnchorClass)
        except TypeError:
            # if our fontClass doesnt support all the additional classes
            return self.fontClass(path)

    def _copyFontInfo(self, sourceInfo, targetInfo):
        """ Copy the non-calculating fields from the source info."""
        infoAttributes = [
            "versionMajor",
            "versionMinor",
            "copyright",
            "trademark",
            "note",
            "openTypeGaspRangeRecords",
            "openTypeHeadCreated",
            "openTypeHeadFlags",
            "openTypeNameDesigner",
            "openTypeNameDesignerURL",
            "openTypeNameManufacturer",
            "openTypeNameManufacturerURL",
            "openTypeNameLicense",
            "openTypeNameLicenseURL",
            "openTypeNameVersion",
            "openTypeNameUniqueID",
            "openTypeNameDescription",
            "#openTypeNamePreferredFamilyName",
            "#openTypeNamePreferredSubfamilyName",
            "#openTypeNameCompatibleFullName",
            "openTypeNameSampleText",
            "openTypeNameWWSFamilyName",
            "openTypeNameWWSSubfamilyName",
            "openTypeNameRecords",
            "openTypeOS2Selection",
            "openTypeOS2VendorID",
            "openTypeOS2Panose",
            "openTypeOS2FamilyClass",
            "openTypeOS2UnicodeRanges",
            "openTypeOS2CodePageRanges",
            "openTypeOS2Type",
            "postscriptIsFixedPitch",
            "postscriptForceBold",
            "postscriptDefaultCharacter",
            "postscriptWindowsCharacterSet"
        ]
        for infoAttribute in infoAttributes:
            copy = False
            if self.ufoVersion == 1 and infoAttribute in fontInfoAttributesVersion1:
                copy = True
            elif self.ufoVersion == 2 and infoAttribute in fontInfoAttributesVersion2:
                copy = True
            elif self.ufoVersion == 3 and infoAttribute in fontInfoAttributesVersion3:
                copy = True
            if copy:
                value = getattr(sourceInfo, infoAttribute)
                setattr(targetInfo, infoAttribute, value)





if __name__ == "__main__":
    # standalone test
    import shutil
    import os
    from defcon.objects.font import Font
    import logging

    def addGlyphs(font, s):
        # we need to add the glyphs
        step = 0
        for n in ['glyphOne', 'glyphTwo', 'glyphThree', 'glyphFour']:
            font.newGlyph(n)
            g = font[n]
            p = g.getPen()
            p.moveTo((0,0))
            p.lineTo((s,0))
            p.lineTo((s,s))
            p.lineTo((0,s))
            p.closePath()
            g.move((0,s+step))
            g.width = s
            step += 50
        for n, w in [('wide', 800), ('narrow', 100)]:
            font.newGlyph(n)
            g = font[n]
            p = g.getPen()
            p.moveTo((0,0))
            p.lineTo((w,0))
            p.lineTo((w,font.info.ascender))
            p.lineTo((0,font.info.ascender))
            p.closePath()
            g.width = w
        font.newGlyph("wide.component")
        g = font["wide.component"]
        comp = g.instantiateComponent()
        comp.baseGlyph = "wide"
        comp.offset = (0,0)
        g.appendComponent(comp)
        g.width = font['wide'].width
        font.newGlyph("narrow.component")
        g = font["narrow.component"]
        comp = g.instantiateComponent()
        comp.baseGlyph = "narrow"
        comp.offset = (0,0)
        g.appendComponent(comp)
        g.width = font['narrow'].width
        uniValue = 200
        for g in font:
            g.unicode = uniValue
            uniValue += 1

    def fillInfo(font):
        font.info.unitsPerEm = 1000
        font.info.ascender = 800
        font.info.descender = -200

    def makeTestFonts(rootPath):
        """ Make some test fonts that have the kerning problem."""
        path1 = os.path.join(rootPath, "geometryMaster1.ufo")
        path2 = os.path.join(rootPath, "geometryMaster2.ufo")
        path3 = os.path.join(rootPath, "my_test_instance_dir_one", "geometryInstance%3.3f.ufo")
        path4 = os.path.join(rootPath, "my_test_instance_dir_two", "geometryInstanceAnisotropic1.ufo")
        path5 = os.path.join(rootPath, "my_test_instance_dir_two", "geometryInstanceAnisotropic2.ufo")
        f1 = Font()
        fillInfo(f1)
        addGlyphs(f1, 100)
        f1.features.text = u"# features text from master 1"
        f2 = Font()
        fillInfo(f2)
        addGlyphs(f2, 500)
        f2.features.text = u"# features text from master 2"
        f1.info.ascender = 400
        f1.info.descender = -200
        f2.info.ascender = 600
        f2.info.descender = -100
        f1.info.copyright = u"This is the copyright notice from master 1"
        f2.info.copyright = u"This is the copyright notice from master 2"
        f1.lib['ufoProcessor.test.lib.entry'] = "Lib entry for master 1"
        f2.lib['ufoProcessor.test.lib.entry'] = "Lib entry for master 2"
        f1.save(path1, 2)
        f2.save(path2, 2)
        return path1, path2, path3, path4, path5

    def makeSwapFonts(rootPath):
        """ Make some test fonts that have the kerning problem."""
        path1 = os.path.join(rootPath, "Swap.ufo")
        path2 = os.path.join(rootPath, "Swapped.ufo")
        f1 = Font()
        fillInfo(f1)
        addGlyphs(f1, 100)
        f1.features.text = u"# features text from master 1"
        f1.info.ascender = 800
        f1.info.descender = -200
        f1.kerning[('glyphOne', 'glyphOne')] = -10
        f1.kerning[('glyphTwo', 'glyphTwo')] = 10
        f1.save(path1, 2)
        return path1, path2

    def testDocument(docPath):
        # make the test fonts and a test document
        testFontPath = os.path.join(os.getcwd(), "automatic_testfonts")
        m1, m2, i1, i2, i3 = makeTestFonts(testFontPath)
        d = DesignSpaceProcessor()
        a = AxisDescriptor()
        a.name = "pop"
        a.minimum = 50
        a.maximum = 1000
        a.default = 0
        a.tag = "pop*"
        d.addAxis(a)
        s1 = SourceDescriptor()
        s1.path = m1
        s1.location = dict(pop=a.minimum)
        s1.name = "test.master.1"
        s1.copyInfo = True
        s1.copyFeatures = True
        s1.copyLib = True
        d.addSource(s1)
        s2 = SourceDescriptor()
        s2.path = m2
        s2.location = dict(pop=1000)
        s2.name = "test.master.2"
        #s2.copyInfo = True
        d.addSource(s2)
        for counter in range(3):
            factor = counter / 2        
            i = InstanceDescriptor()
            v = a.minimum+factor*(a.maximum-a.minimum)
            i.path = i1%v
            i.familyName = "TestFamily"
            i.styleName = "TestStyle_pop%3.3f"%(v)
            i.name = "%s-%s"%(i.familyName, i.styleName)
            i.location = dict(pop=v)
            i.info = True
            i.kerning = True
            if counter == 2:
                i.glyphs['glyphTwo'] = dict(name="glyphTwo", mute=True)
                i.copyLib = True
            if counter == 2:
               i.glyphs['narrow'] = dict(instanceLocation=dict(pop=400), unicodes=[0x123, 0x124, 0x125])
            d.addInstance(i)
        d.write(docPath)

    def testGenerateInstances(docPath):
        # execute the test document
        d = DesignSpaceProcessor()
        d.read(docPath)
        d.generateUFO()
        if d.problems:
            print(d.problems)

    def testSwap(docPath):
        srcPath, dstPath = makeSwapFonts(os.path.dirname(docPath))
        
        f = Font(srcPath)
        swapGlyphNames(f, "narrow", "wide")
        f.info.styleName = "Swapped"
        f.save(dstPath)
        
        # test the results in newly opened fonts
        old = Font(srcPath)
        new = Font(dstPath)
        assert new.kerning.get(("narrow", "narrow")) == old.kerning.get(("wide","wide"))
        assert new.kerning.get(("wide", "wide")) == old.kerning.get(("narrow","narrow"))
        # after the swap these widths should be the same
        assert old['narrow'].width == new['wide'].width
        assert old['wide'].width == new['narrow'].width
        # The following test may be a bit counterintuitive:
        # the rule swaps the glyphs, but we do not want glyphs that are not
        # specifically affected by the rule to *appear* any different.
        # So, components have to be remapped. 
        assert new['wide.component'].components[0].baseGlyph == "narrow"
        assert new['narrow.component'].components[0].baseGlyph == "wide"

    def testUnicodes(docPath):
        # after executing testSwap there should be some test fonts
        # let's check if the unicode values for glyph "narrow" arrive at the right place.
        d = DesignSpaceProcessor()
        d.read(docPath)
        for instance in d.instances:
            if os.path.exists(instance.path):
                f = Font(instance.path)
                print("instance.path", instance.path)
                print("instance.name", instance.name, "f['narrow'].unicodes", f['narrow'].unicodes)
                if instance.name == "TestFamily-TestStyle_pop1000.000":
                    assert f['narrow'].unicodes == [291, 292, 293]
                else:
                    assert f['narrow'].unicodes == [207]
            else:
                print("Missing test font at %s"%instance.path)

    selfTest = True
    if selfTest:
        testRoot = os.path.join(os.getcwd(), "automatic_testfonts")
        if os.path.exists(testRoot):
            shutil.rmtree(testRoot)
        docPath = os.path.join(testRoot, "automatic_test.designspace")
        testDocument(docPath)
        testGenerateInstances(docPath)
        testSwap(docPath)
        #testUnicodes(docPath)