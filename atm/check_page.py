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
assert len(soup.select('.language-pair')) == 1
assert soup.select_one('.language-pair')['data-code'] == 'complete-code'
assert len(soup.select('.requirements-panel')) == 1
assert not soup.select('.toc a[href="#withdraw"]')
assert soup.find(id='verification').find_previous('h2')['id'] == 'implementation'
assert 'Splitwise' not in soup.get_text()
implementation_headings = []
for heading in soup.find(id='implementation').find_all_next(['h2', 'h3']):
    if heading.name == 'h2':
        break
    implementation_headings.append(heading['id'])
assert implementation_headings[:5] == ['atm_1', 'cashinventory_1', 'bankgateway_1', 'hardware_1', 'atmstate'], 'Implementation must proceed from ATM to its dependencies'

# The walkthrough teaches design with pseudocode. Runnable languages appear only
# in the complete implementation section, whose content must match source files.
implementation = soup.find(id='implementation')
complete = soup.find(id='complete-reference-implementations')
walkthrough = []
for node in implementation.find_all_next():
    if node is complete:
        break
    if node.name == 'pre':
        walkthrough.append(node.get_text())
assert len(walkthrough) >= 11
assert all('self.' not in code and 'public synchronized' not in code for code in walkthrough)
assert all(not line.strip().startswith(('require ', 'under lock', 'on operation error', 'on bank error', 'on ejection error')) for code in soup.select('pre') for line in code.get_text().splitlines())
assert 'withdraw(amount)' in '\n'.join(walkthrough)
assert 'findBundle(index, remaining)' in '\n'.join(walkthrough)

import subprocess, tempfile, unittest
python = soup.find(id='complete-code-python').get_text()
java = soup.find(id='complete-code-java').get_text()
assert python.rstrip() == (ROOT/'atm.py').read_text().rstrip()
assert java.rstrip() == (ROOT/'ATM.java').read_text().rstrip()
namespace = {'__name__': 'article_atm'}
exec(compile(python, '<article>', 'exec'), namespace)
import test_atm
test_atm.ATM = namespace['ATM']
test_atm.CashInventory = namespace['CashInventory']
test_atm.ATMState = namespace['ATMState']
result = unittest.TextTestRunner().run(unittest.defaultTestLoader.loadTestsFromModule(test_atm))
assert result.wasSuccessful()
with tempfile.TemporaryDirectory(prefix='atm-article-') as folder:
    folder = Path(folder)
    (folder/'ATM.java').write_text(java)
    subprocess.run(['javac', '-d', str(folder), str(folder/'ATM.java'), str(ROOT/'ATMTest.java')], check=True)
    subprocess.run(['java', '-cp', str(folder), 'ATMTest'], check=True)
print('Pseudocode walkthrough, class order, links, IDs, final code tabs, and complete implementations passed.')
