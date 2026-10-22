"""Preserve the cloud package while replacing slide 4 and inserting slide 5."""
import copy
import sys
import zipfile
from lxml import etree as E

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'
CT = 'http://schemas.openxmlformats.org/package/2006/content-types'
NS = {'p': P, 'a': A}
for prefix, uri in [('p', P), ('a', A), ('r', R)]:
    E.register_namespace(prefix, uri)


def xml(root):
    return E.tostring(root, encoding='utf-8', xml_declaration=True)


def foreground(target, authored):
    cs = target.find('p:cSld', NS)
    old_tree = cs.find('p:spTree', NS)
    tree_index = list(cs).index(old_tree)
    footer = next(copy.deepcopy(sp) for sp in old_tree if sp.find('.//a:fld[@type="slidenum"]', NS) is not None)
    cs.remove(cs.find('p:spTree', NS))
    cs.insert(tree_index, copy.deepcopy(authored.find('p:cSld/p:spTree', NS)))
    cs.find('p:spTree', NS).append(footer)
    for index, element in enumerate(cs.findall('p:spTree/*', NS), 1):
        nonvisual = element.find('.//p:cNvPr', NS)
        if nonvisual is not None:
            nonvisual.set('id', str(index + 100))


def notes_body(root):
    return next(sp for sp in root.findall('.//p:sp', NS)
                if sp.find('p:nvSpPr/p:nvPr/p:ph', NS) is not None
                and sp.find('p:nvSpPr/p:nvPr/p:ph', NS).get('type') == 'body')


with zipfile.ZipFile(sys.argv[1]) as source, zipfile.ZipFile(sys.argv[2]) as authored:
    parts = {name: source.read(name) for name in source.namelist()}
    presentation = E.fromstring(parts['ppt/presentation.xml'])
    ids = presentation.find('p:sldIdLst', NS)
    source_count = len(ids)
    assert source_count >= 4
    relationships = E.fromstring(parts['ppt/_rels/presentation.xml.rels'])
    lookup = {r.get('Id'): r.get('Target') for r in relationships}
    original_order = ['ppt/' + lookup[i.get('{' + R + '}id')] for i in ids]
    assert original_order[3] == 'ppt/slides/slide4.xml'
    assert 'llm_coach' in ''.join(E.fromstring(parts[original_order[3]]).itertext())
    new_slide = 'ppt/slides/slide46.xml'
    new_notes = 'ppt/notesSlides/notesSlide46.xml'
    assert new_slide not in parts and new_notes not in parts
    for logical, slide_part, notes_part in [(4, original_order[3], 'ppt/notesSlides/notesSlide4.xml'), (5, new_slide, new_notes)]:
        slide = E.fromstring(source.read(original_order[3]))
        foreground(slide, E.fromstring(authored.read(f'ppt/slides/slide{logical - 3}.xml')))
        parts[slide_part] = xml(slide)
        notes = E.fromstring(source.read('ppt/notesSlides/notesSlide4.xml'))
        body = notes_body(notes)
        old_text = body.find('p:txBody', NS)
        text_index = list(body).index(old_text)
        body.remove(old_text)
        body.insert(text_index, copy.deepcopy(notes_body(E.fromstring(authored.read(f'ppt/notesSlides/notesSlide{logical - 3}.xml'))).find('p:txBody', NS)))
        parts[notes_part] = xml(notes)
    rels = E.fromstring(source.read('ppt/slides/_rels/slide4.xml.rels'))
    for r in rels:
        if r.get('Type').endswith('/notesSlide'):
            r.set('Target', '../notesSlides/notesSlide46.xml')
    parts['ppt/slides/_rels/slide46.xml.rels'] = xml(rels)
    rels = E.fromstring(source.read('ppt/notesSlides/_rels/notesSlide4.xml.rels'))
    for r in rels:
        if r.get('Type').endswith('/slide'):
            r.set('Target', '../slides/slide46.xml')
    parts['ppt/notesSlides/_rels/notesSlide46.xml.rels'] = xml(rels)
    new_rid = 'rIdManualCoach'
    assert new_rid not in lookup
    E.SubElement(relationships, '{' + REL + '}Relationship', Id=new_rid, Type=R + '/slide', Target='slides/slide46.xml')
    ids.insert(4, E.Element('{' + P + '}sldId', {'id': str(max(int(i.get('id')) for i in ids) + 1), '{' + R + '}id': new_rid}))
    parts['ppt/presentation.xml'] = xml(presentation)
    parts['ppt/_rels/presentation.xml.rels'] = xml(relationships)
    types = E.fromstring(parts['[Content_Types].xml'])
    for part, kind in [(new_slide, 'slide'), (new_notes, 'notesSlide')]:
        E.SubElement(types, '{' + CT + '}Override', PartName='/' + part, ContentType='application/vnd.openxmlformats-officedocument.presentationml.' + kind + '+xml')
    parts['[Content_Types].xml'] = xml(types)
    for index, part in enumerate(original_order[:4] + [new_slide] + original_order[4:], 1):
        root = E.fromstring(parts[part])
        for field in root.findall('.//a:fld', NS):
            if field.get('type') == 'slidenum':
                field.find('a:t', NS).text = str(index)
        for t in root.findall('.//a:t', NS):
            if t.text and t.text.strip().startswith('/ ') and t.text.strip()[2:].isdigit():
                t.text = f' / {source_count + 1}'
        parts[part] = xml(root)
    app = E.fromstring(parts['docProps/app.xml'])
    count = app.find('{http://schemas.openxmlformats.org/officeDocument/2006/extended-properties}Slides')
    if count is not None:
        count.text = str(source_count + 1)
        parts['docProps/app.xml'] = xml(app)
    # Assert unchanged foregrounds after excluding the sole slide-number shape.
    for part in original_order:
        if part == original_order[3]:
            continue
        old, new = E.fromstring(source.read(part)), E.fromstring(parts[part])
        for root in [old, new]:
            tree = root.find('p:cSld/p:spTree', NS)
            for sp in list(tree):
                if sp.find('.//a:fld[@type="slidenum"]', NS) is not None:
                    tree.remove(sp)
        assert E.tostring(old) == E.tostring(new), part
    for name in source.namelist():
        if name.startswith(('ppt/charts/', 'ppt/embeddings/')):
            assert parts[name] == source.read(name), name
    with zipfile.ZipFile(sys.argv[3], 'w', zipfile.ZIP_DEFLATED) as output:
        for name, payload in parts.items():
            output.writestr(name, payload)
print('Preserved all original slide foregrounds except slide 4 and page numbering; all charts/workbooks unchanged.')
