import re
import posixpath
import sys
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

NS = {
    'p': 'http://schemas.openxmlformats.org/presentationml/2006/main',
    'a': 'http://schemas.openxmlformats.org/drawingml/2006/main',
    'r': 'http://schemas.openxmlformats.org/officeDocument/2006/relationships',
    'c': 'http://schemas.openxmlformats.org/drawingml/2006/chart',
    'rel': 'http://schemas.openxmlformats.org/package/2006/relationships',
}
mode, source = sys.argv[1:3]
with zipfile.ZipFile(source) as archive:
    parts = {name: archive.read(name) for name in archive.namelist()}
if mode == 'restore-workbooks':
    destination = Path(sys.argv[3])
    source_pages = [int(n) for n in sys.argv[4].split(',')]
    with zipfile.ZipFile(destination) as archive:
        target = {name: archive.read(name) for name in archive.namelist()}

    def relation_part(name):
        return posixpath.join(posixpath.dirname(name), '_rels', posixpath.basename(name) + '.rels')

    def owner_charts(package, page):
        slide = f'ppt/slides/slide{page}.xml'
        relationships = ET.fromstring(package[relation_part(slide)])
        refs = {r.get('Id'): posixpath.normpath(posixpath.join(posixpath.dirname(slide), r.get('Target'))).lstrip('/')
                for r in relationships}
        return [refs[c.get(f'{{{NS["r"]}}}id')] for c in ET.fromstring(package[slide]).findall('.//c:chart', NS)]

    restored = 0
    for page, source_page in enumerate(source_pages, 1):
        original = owner_charts(parts, source_page)
        exported = owner_charts(target, page)
        assert len(original) == len(exported)
        for old_chart, new_chart in zip(original, exported):
            relationships = ET.fromstring(parts[relation_part(old_chart)])
            assert len(relationships) == 1
            relationship = relationships[0]
            assert relationship.get('Type').endswith('/package')
            old_book = posixpath.normpath(posixpath.join(posixpath.dirname(old_chart), relationship.get('Target'))).lstrip('/')
            new_book = f'ppt/embeddings/eagle-template-chart-{restored + 1}.xlsx'
            target[new_book] = parts[old_book]
            relationship.set('Target', posixpath.relpath(new_book, posixpath.dirname(new_chart)))
            target[new_chart] = parts[old_chart]
            ET.register_namespace('', NS['rel'])
            target[relation_part(new_chart)] = ET.tostring(relationships, encoding='utf-8', xml_declaration=True)
            restored += 1
    content_types = ET.fromstring(target['[Content_Types].xml'])
    if not any(t.get('Extension') == 'xlsx' for t in content_types):
        ET.SubElement(content_types, '{http://schemas.openxmlformats.org/package/2006/content-types}Default',
                      Extension='xlsx', ContentType='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    ET.register_namespace('', 'http://schemas.openxmlformats.org/package/2006/content-types')
    target['[Content_Types].xml'] = ET.tostring(content_types, encoding='utf-8', xml_declaration=True)
    assert restored == 3
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in target.items():
            archive.writestr(name, data)
    print(f'Preserved {restored} original native charts and source workbooks')
    sys.exit(0)
if mode == 'potx':
    destination = Path(sys.argv[3])
    parts['[Content_Types].xml'] = parts['[Content_Types].xml'].replace(
        b'presentationml.presentation.main+xml', b'presentationml.template.main+xml')
    with zipfile.ZipFile(destination, 'w', zipfile.ZIP_DEFLATED) as archive:
        for name, data in parts.items():
            archive.writestr(name, data)
elif mode == 'verify':
    destination = Path(source)
else:
    raise ValueError(mode)

with zipfile.ZipFile(destination) as archive:
    assert archive.testzip() is None
    assert b'presentationml.template.main+xml' in archive.read('[Content_Types].xml')
    slides = [n for n in parts if re.fullmatch(r'ppt/slides/slide\d+\.xml', n)]
    layouts = [n for n in parts if re.fullmatch(r'ppt/slideLayouts/slideLayout\d+\.xml', n)]
    charts = [n for n in parts if re.search(r'/charts/chart\d+\.xml$', n)]
    assert len(slides) == 8
    assert len(layouts) == 18
    assert len(charts) == 3
    assert len([n for n in parts if n.startswith('ppt/embeddings/') and n.endswith('.xlsx')]) == 3
    for name in slides + layouts + ['ppt/slideMasters/slideMaster1.xml']:
        root = ET.fromstring(parts[name])
        assert root.find('p:cSld/p:bg/p:bgPr/a:blipFill/a:blip', NS) is not None, name
        if name in slides:
            assert root.find('.//p:cxnSp/p:nvCxnSpPr/p:nvPr/p:ph', NS) is None, name
            fields = root.findall('.//a:fld[@type="slidenum"]', NS)
            assert len(fields) == 0, name
        if name in layouts[-6:]:
            assert root.find('.//a:buChar', NS) is None, name
    master = ET.fromstring(parts['ppt/slideMasters/slideMaster1.xml'])
    fields = master.findall('.//a:fld[@type="slidenum"]', NS)
    assert len(fields) == 1
    assert re.fullmatch(r'\{[0-9A-F-]{36}\}', fields[0].get('id'))
    assert master.find('.//p:ph[@type="sldNum"]', NS) is None
    assert master.find('p:txStyles/p:bodyStyle//a:buChar', NS) is None
print(f'{mode}: {destination}; 8 slides, 18 layouts, 3 native charts, native backgrounds and page numbers')
