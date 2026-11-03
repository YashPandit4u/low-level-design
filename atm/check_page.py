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
assert len(soup.select('.language-pair')) == 9
assert len(soup.select('.requirements-panel')) == 1
assert not soup.select('.toc a[href="#withdraw"]')
assert soup.find(id='verification').find_previous('h2')['id'] == 'implementation'
assert 'Splitwise' not in soup.get_text()
# Reassemble the taught Python methods into a class and execute the same tests.
blocks = [p.get_text() for p in soup.select('.language-pair pre[id$="-python"]')][:-1]
imports = 'from __future__ import annotations\nfrom threading import Lock\nfrom typing import Protocol\nfrom uuid import uuid4\n'
assembled = imports + '\n\n'.join(blocks[:2]) + '\n\nclass ATM:\n'
import textwrap
assembled += '\n\n'.join(textwrap.indent(code,'    ') for code in blocks[2:])
assert ast.dump(ast.parse(assembled)).count('FunctionDef') == ast.dump(ast.parse((ROOT/'atm.py').read_text())).count('FunctionDef')
namespace = {'__name__':'article_atm'}
exec(compile(assembled, '<article>', 'exec'),namespace)
import test_atm, unittest
test_atm.ATM, test_atm.CashInventory = namespace['ATM'], namespace['CashInventory']
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromModule(test_atm))
assert result.wasSuccessful()
print('HTML links, IDs, 9 tab pairs, navigation, and assembled Python snippets passed.')
# Compile and run the Java walkthrough assembled from its displayed panels.
import subprocess, tempfile
java_blocks = [p.get_text() for p in soup.select('.language-pair pre[id$="-java"]')][:-1]
with tempfile.TemporaryDirectory(prefix='atm-article-') as folder:
    folder = Path(folder)
    (folder/'ATM.java').write_text('import java.util.*;\npublic final class ATM {\n' + '\n'.join(java_blocks) + '\n}\n')
    subprocess.run(['javac','-d',str(folder),str(folder/'ATM.java'),str(ROOT/'ATMTest.java')],check=True)
    subprocess.run(['java','-cp',str(folder),'ATMTest'],check=True)
print('Assembled Java article snippets passed the Java behavior tests.')
