"""Check the generated article's links, tabs, excerpts, and navigation."""
from pathlib import Path
from bs4 import BeautifulSoup
import ast
ROOT = Path(__file__).resolve().parent
soup = BeautifulSoup((ROOT/'index.html').read_text(), 'html.parser')
ids = [node['id'] for node in soup.select('[id]')]
assert len(ids) == len(set(ids)), 'Duplicate HTML IDs'
for a in soup.select('a[href]'):
    href = a['href']
    if href.startswith('#'): assert href[1:] in ids, href
    elif '://' not in href: assert (ROOT/href).exists(), href
for box in soup.select('.language-pair'):
    tabs = box.select('[role=tab]')
    assert len(tabs) == 2
    assert len(box.select('[role=tabpanel]')) == 2
    assert len(box.select('[role=tabpanel][hidden]')) == 1
    for tab in tabs:
        panel = box.find(id=tab['aria-controls'])
        assert panel and panel['aria-labelledby'] == tab['id']
assert len(soup.select('.language-pair')) == 11
assert len(soup.select('.requirements-panel')) == 1
assert not soup.select('.toc a[href="#withdraw"]')
assert soup.find(id='verification').find_previous('h2')['id'] == 'implementation'
assert 'Splitwise' not in soup.get_text()
# Group displayed excerpts by their owning class, not by panel position.
def excerpts(language):
    sections = {}
    for panel in soup.select(f'.language-pair pre[id$="-{language}"]'):
        if panel['id'].startswith('complete-code'): continue
        heading = panel.find_previous('h3')['id']
        sections.setdefault(heading, []).append(panel.get_text())
    return sections

import textwrap
blocks = excerpts('python')
imports = 'from __future__ import annotations\nfrom threading import Lock\nfrom typing import Protocol\nfrom uuid import uuid4\n'
assembled = imports + '\n\n'.join(blocks['bankgateway-and-hardware'])
for heading, name in [('cashinventory_1', 'CashInventory'), ('atm_1', 'ATM')]:
    assembled += f'\n\nclass {name}:\n'
    assembled += '\n\n'.join(textwrap.indent(code,'    ') for code in blocks[heading])
original_classes = {n.name: ast.dump(n) for n in ast.parse((ROOT/'atm.py').read_text()).body if isinstance(n, ast.ClassDef)}
shown_classes = {n.name: ast.dump(n) for n in ast.parse(assembled).body if isinstance(n, ast.ClassDef)}
assert shown_classes == original_classes, 'Displayed Python class differs from source'
namespace = {'__name__':'article_atm'}
exec(compile(assembled, '<article>', 'exec'),namespace)
import test_atm, unittest
test_atm.ATM, test_atm.CashInventory = namespace['ATM'], namespace['CashInventory']
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromModule(test_atm))
assert result.wasSuccessful()
print('HTML links, IDs, 11 tab pairs, navigation, and assembled Python snippets passed.')
# Compile and run the Java walkthrough assembled from its displayed panels.
import subprocess, tempfile
java_sections = excerpts('java')
java_blocks = java_sections['bankgateway-and-hardware'] + [
    'static final class CashInventory {\n' + '\n'.join(java_sections['cashinventory_1']) + '\n}'
] + java_sections['atm_1']
with tempfile.TemporaryDirectory(prefix='atm-article-') as folder:
    folder = Path(folder)
    (folder/'ATM.java').write_text('import java.util.*;\npublic final class ATM {\n' + '\n'.join(java_blocks) + '\n}\n')
    subprocess.run(['javac','-d',str(folder),str(folder/'ATM.java'),str(ROOT/'ATMTest.java')],check=True)
    subprocess.run(['java','-cp',str(folder),'ATMTest'],check=True)
print('Assembled Java article snippets passed the Java behavior tests.')
