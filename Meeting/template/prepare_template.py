import copy
import re
import sys
import uuid
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
NS = {'p': P, 'a': A}
ET.register_namespace('p', P)
ET.register_namespace('a', A)

mode, source = sys.argv[1:3]
source = Path(source)
with zipfile.ZipFile(source) as archive:
    parts = {name: archive.read(name) for name in archive.namelist()}

if mode == 'fix':
    master = ET.fromstring(parts['ppt/slideMasters/slideMaster1.xml'])
    number = next(s for s in master.findall('.//p:sp', NS)
                  if s.find('.//a:fld[@type="slidenum"]', NS) is not None)
    for name, data in list(parts.items()):
        if not (name.startswith(('ppt/slides/slide', 'ppt/slideLayouts/slideLayout')) and name.endswith('.xml')):
            continue
        root = ET.fromstring(data)
        tree = root.find('p:cSld/p:spTree', NS)
        if tree is None:
            continue
        # Clear inherited bullets from the new title/subtitle placeholders.
        for shape in tree.findall('p:sp', NS):
            ph = shape.find('p:nvSpPr/p:nvPr/p:ph', NS)
            if ph is not None and ph.get('type') in ('title', 'subTitle'):
                for paragraph in shape.findall('p:txBody/a:p', NS):
                    props = paragraph.find('a:pPr', NS)
                    if props is None:
                        props = ET.Element(f'{{{A}}}pPr')
                        paragraph.insert(0, props)
                    for child in list(props):
                        if child.tag.split('}')[-1].startswith('bu'):
                            props.remove(child)
                    ET.SubElement(props, f'{{{A}}}buNone')
        if root.tag == f'{{{P}}}sld' or int(re.search(r'slideLayout(\d+)\.xml', name)[1]) > 12:
            if tree.find('.//a:fld[@type="slidenum"]', NS) is None:
                cloned = copy.deepcopy(number)
                ids = [int(e.get('id', '0')) for e in tree.findall('.//p:cNvPr', NS)]
                cloned.find('p:nvSpPr/p:cNvPr', NS).set('id', str(max(ids, default=0) + 1))
                field = cloned.find('.//a:fld', NS)
                field.set('id', '{' + str(uuid.uuid4()).upper() + '}')
                tree.append(cloned)
        parts[name] = ET.tostring(root, encoding='utf-8', xml_declaration=True)
    destination = source
elif mode == 'potx':
    destination = Path(sys.argv[3])
    parts['[Content_Types].xml'] = parts['[Content_Types].xml'].replace(
        b'presentationml.presentation.main+xml', b'presentationml.template.main+xml')
    assert b'presentationml.template.main+xml' in parts['[Content_Types].xml']
else:
    raise ValueError(mode)

with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
    for name, data in parts.items():
        archive.writestr(name, data)
with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
    slides = [n for n in parts if n.startswith('ppt/slides/slide') and n.endswith('.xml')]
    assert len(slides) == 6
    for name in slides:
        root = ET.fromstring(parts[name])
        assert root.find('.//a:fld[@type="slidenum"]', NS) is not None
        ids = {e.get('id') for e in root.findall('.//p:cNvPr', NS)}
        for link in root.findall('.//p:cxnSp', NS):
            assert link.find('.//a:tailEnd', NS).get('type') == 'arrow'
            assert link.find('.//a:stCxn', NS).get('id') in ids
            assert link.find('.//a:endCxn', NS).get('id') in ids
    assert len([n for n in parts if re.fullmatch(r'ppt/slideLayouts/slideLayout\d+\.xml', n)]) == 18
    assert len([n for n in parts if re.search(r'/charts/chart\d+\.xml$', n)]) == 2
    if mode == 'potx':
        assert len([n for n in parts if n.startswith('ppt/embeddings/') and n.endswith('.xlsx')]) == 2
print(f'{mode}: {destination}')
