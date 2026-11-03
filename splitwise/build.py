"""Regenerate both article editions. pip install -r requirements.txt"""
from pathlib import Path
import base64
import re
from html import escape
import markdown
from bs4 import BeautifulSoup
from pygments import highlight
from pygments.lexers import get_lexer_by_name, TextLexer
from pygments.formatters import HtmlFormatter

ROOT = Path(__file__).resolve().parent
def build(detailed=False):
    ARTICLE = ROOT / ('TUTORIAL-DETAILED.md' if detailed else 'TUTORIAL.md')
    output = 'index.html' if detailed else 'simplified.html'
    edition = 'Detailed' if detailed else 'Simplified'
    code_title = 'Complete Code Implementation' if detailed else 'Extended Code Reference'
    code_description = 'Read the working solution in your preferred language' if detailed else 'Optional implementations of the follow-up design'
    version_links = '<nav class="editions" aria-label="Article version">' + ''.join(
        f'<a href="{href}"' + (' aria-current="page"' if selected else '') + f'>{label}</a>'
        for href, label, selected in [('index.html', 'Detailed', detailed), ('simplified.html', 'Simplified', not detailed)]
    ) + '</nav>'
    soup = BeautifulSoup(markdown.markdown(ARTICLE.read_text(), extensions=['tables', 'fenced_code', 'toc']), 'html.parser')
    soup.h1.decompose()
    for h in soup.find_all(['h2', 'h3']):
        titles = {'Understanding the problem':'Understanding the Problem', 'Core entities and relationships':'Core Entities and Relationships', 'Class design':'Class Design', 'Clarifying questions':'Clarifying Questions', 'Final requirements':'Final Requirements', 'Final class design':'Final Class Design', 'What is expected at each level?':'What is Expected at Each Level?', 'Test your understanding':'Test Your Understanding', 'Complete reference implementations':('Complete Code Implementation' if detailed else 'Extended Reference Implementations')}
        if h.get_text() in titles: h.string = titles[h.get_text()]


    def frag(text):
        return BeautifulSoup(text, 'html.parser')

    def code_panel(code, lang, panel_id=None):
        try: lexer = get_lexer_by_name(lang)
        except Exception: lexer = TextLexer()
        body = highlight(code.rstrip(), lexer, HtmlFormatter(nowrap=True))
        attrs = f' id="{panel_id}" role="tabpanel" tabindex="0"' if panel_id else ''
        return f'<pre{attrs}><code>{body}</code></pre>'

    # Render the agreed requirements and scope as one copyable specification.
    requirement_heading = soup.find(id='final-requirements')
    requirement_list = requirement_heading.find_next_sibling('ol')
    scope = requirement_list.find_next_sibling('p')
    assert scope.get_text().startswith('Out of scope')
    specification = 'Requirements:\n' + '\n'.join(
        f'{i}. {item.get_text()}'
        for i, item in enumerate(requirement_list.find_all('li', recursive=False), 1)
    ) + '\n\n' + scope.get_text()
    panel = frag('<div class="codebox requirements-panel"><div class="codebar">'
        '<span class="code-title">Final requirements</span>'
        '<button class="copy" aria-label="Copy requirements">▢</button></div>'
        + code_panel(specification, 'text') + '</div>')
    requirement_list.replace_with(panel)
    scope.decompose()

    # Combine adjacent language versions without removing any explanatory prose.
    count = 0
    for label in list(soup.find_all('p')):
        if label.get_text(strip=True) != 'Python:': continue
        py = label.find_next_sibling()
        jl = py.find_next_sibling() if py else None
        java = jl.find_next_sibling() if jl else None
        if not(py and py.name == 'pre' and jl and jl.get_text(strip=True) == 'Java:' and java and java.name == 'pre'): continue
        count += 1
        ident = f'code-{count}'
        heading = label.find_previous(['h2','h3','h4']).get_text()
        widget = f'<div class="codebox language-pair" data-code="{ident}"><div class="codebar"><div role="tablist" aria-label="{escape(heading)} language">'
        for lang, title in [('python','Python'),('java','Java')]:
            widget += f'<button role="tab" id="{ident}-{lang}-tab" aria-controls="{ident}-{lang}" aria-selected="{str(lang == "python").lower()}" tabindex="{0 if lang == "python" else -1}" data-lang="{lang}">{title}</button>'
        widget += '</div><button class="copy" aria-label="Copy visible code">▢</button></div>'
        widget += code_panel(py.get_text(), 'python', ident+'-python')
        widget += code_panel(java.get_text(), 'java', ident+'-java')+'</div>'
        node = frag(widget)
        node.find(id=ident+'-java')['hidden'] = ''
        for lang in ['python','java']:
            node.find(id=ident+'-'+lang)['aria-labelledby'] = ident+'-'+lang+'-tab'
        label.replace_with(node)
        py.decompose(); jl.decompose(); java.decompose()

    for pre in list(soup.find_all('pre')):
        if pre.find_parent(class_='codebox'): continue
        classes = pre.code.get('class',[]) if pre.code else []
        lang = classes[0].replace('language-','') if classes else 'text'
        previous = pre.find_previous(['h2','h3','h4'])
        title = previous.get_text() if previous else 'Design sketch'
        box = frag(f'<div class="codebox"><div class="codebar"><span class="code-title">{escape(title)}</span><button class="copy" aria-label="Copy code">▢</button></div>{code_panel(pre.get_text(),lang)}</div>')
        pre.replace_with(box)

    # Keep comparisons available, but collapse secondary approaches on first load.
    for h in list(soup.find_all(['h4','h5'])):
        text = h.get_text()
        if not text.startswith(('Option ', 'Incorrect:', 'Correct but broad:', 'Selected approach:')): continue
        good = text.startswith(('Option 3','Selected approach:'))
        bad = text.startswith(('Option 1','Incorrect:'))
        detail = soup.new_tag('details', attrs={'class': 'comparison '+('good' if good else 'bad' if bad else 'neutral')})
        if good: detail['open']=''
        summary = soup.new_tag('summary'); summary.string = text
        detail.append(summary)
        body = soup.new_tag('div',attrs={'class':'comparison-body'})
        nxt = h.find_next_sibling()
        while nxt and nxt.name not in ['h2','h3','h4','h5']:
            following = nxt.find_next_sibling(); body.append(nxt.extract()); nxt=following
        detail.append(body); h.replace_with(detail)

    first = soup.find('h2').find_next_sibling('p')
    first['class'] = 'callout intro'
    if first.contents and isinstance(first.contents[0],str):
        first.contents[0].replace_with(str(first.contents[0]).removeprefix('💸 '))
    first.insert(0,frag('<strong class="callout-title">💸 What is an expense-sharing system?</strong>'))
    for quote in soup.find_all('blockquote'):
        if 'You:' in quote.get_text(): quote['class']='dialogue'

    # Embed both actual implementations, with the same language switch as snippets.
    anchor = soup.find(id='complete-reference-implementations')
    count += 1
    ident = 'complete-code'
    widget = '<div class="codebox language-pair full-code" data-code="complete-code"><div class="codebar"><div role="tablist" aria-label="Complete implementation language">'
    for lang, filename in [('python','splitwise.py'),('java','Splitwise.java')]:
        widget += f'<button role="tab" id="{ident}-{lang}-tab" aria-controls="{ident}-{lang}" aria-selected="{str(lang == "python").lower()}" tabindex="{0 if lang == "python" else -1}" data-lang="{lang}">{filename}</button>'
    widget += '</div><button class="copy" aria-label="Copy visible code">▢</button></div>'
    for lang, filename in [('python','splitwise.py'),('java','Splitwise.java')]:
        widget += code_panel((ROOT/filename).read_text(),lang,ident+'-'+lang)
    widget += '</div>'
    node = frag(widget)
    node.find(id=ident+'-java')['hidden']=''
    for lang in ['python','java']: node.find(id=ident+'-'+lang)['aria-labelledby']=ident+'-'+lang+'-tab'
    if detailed:
        anchor.insert_after(node)
    else:
        reference = soup.new_tag('details', attrs={'class': 'reference-code'})
        summary = soup.new_tag('summary')
        summary.string = 'Open the extended Python / Java implementation'
        reference.append(summary)
        reference.append(node)
        anchor.find_next_sibling('p').insert_after(reference)
    # Source links continue to work when served from the repository.
    for a in soup.find_all('a',href=True):
        if '://' not in a['href'] and not a['href'].startswith('#'): a['href']=a['href']

    headings = [(h['id'],h.get_text(),h.name) for h in soup.find_all(['h2','h3'])]
    toc=''.join(f'<a href="#{i}" class="toc-{level}" title="{escape(title)}">{escape(title)}</a>' for i,title,level in headings)
    for h in soup.find_all(['h2','h3']):
        h.append(frag(f'<a class="heading-anchor" href="#{h["id"]}" aria-label="Link to {escape(h.get_text())}">#</a>'))

    font = base64.b64encode((ROOT/'assets/open-sans.woff2').read_bytes()).decode()
    copy_icon='<svg viewBox="0 0 24 24" width="15" height="15" fill="none" stroke="currentColor" stroke-width="1.5" aria-hidden="true"><rect x="7" y="5" width="12" height="16" rx="2"/><path d="M15 5V3H4v14h3"/></svg>'
    for button in soup.select('.copy'):
        button.clear(); button.append(frag(copy_icon))
    css=(ROOT/'styles.css').read_text().replace('FONT_DATA',font)
    js=(ROOT/'app.js').read_text()
    page=f'''<!doctype html>
    <html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Splitwise Low Level Design | {edition} Edition</title><meta name="description" content="A complete Splitwise low-level design walkthrough with Python and Java, trade-offs, verification, and follow-ups."><style>{css}</style></head><body>
    <a class="skip" href="#article">Skip to article</a>

    <main class="main" id="top"><header class="topbar"><button class="search-trigger" aria-label="Search article sections"><span>⌕ &nbsp; Search</span><kbd>⌘K</kbd></button><div class="top-actions"><a class="article-home" href="#top">Low Level Design <span>/</span> Splitwise</a><button id="theme" aria-label="Toggle dark mode">☼</button></div></header>
    <div class="outer"><div class="layout"><article id="article"><div class="article-header"><div class="eyebrow">Common Problems</div><h1>Splitwise</h1><p class="metadata">Independent study article <span>·</span> <span class="difficulty">◉ medium</span> <span>·</span> Python &amp; Java <span>·</span> {edition} edition</p>{version_links}</div><div class="feature-card green"><span class="feature-icon">⌘</span><div><h2>{code_title}</h2><p>{code_description}</p></div><a href="#complete-reference-implementations">View Code &nbsp; →</a></div><div class="feature-card coral"><span class="feature-icon">≋</span><div><h2>Explore the Design Trade-offs</h2><p>Compare approaches and understand the decisions</p></div><a href="#group-and-balance-representation">Compare &nbsp; →</a></div>
    {str(soup)}
    <footer class="article-footer"><p>Written by Yash Pandit. Split the bills, but share the knowledge.</p><a href="#top">↑ Back to top</a><a href="{ARTICLE.name}">Read Markdown</a></footer></article><aside class="toc" aria-label="On this page"><div class="reading-tools"><button id="focus" aria-pressed="false">◫ &nbsp; Focus</button><button id="expand" aria-pressed="false">Expand comparisons</button></div><div class="progress-label">Reading Progress</div><div class="progress" role="progressbar" aria-label="Reading progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div></div></div><h2>On This Page</h2><nav>{toc}</nav></aside></div></div></main>
    <button id="exit-focus" hidden>◫ Exit focus</button><dialog id="search-dialog"><form method="dialog"><input id="search-input" aria-label="Search sections" placeholder="Search article sections…" autocomplete="off"><button aria-label="Close search">Esc</button></form><nav id="search-results"></nav></dialog><div id="toast" role="status" aria-live="polite"></div><script>{js}</script></body></html>'''
    (ROOT/output).write_text(page)
    if detailed:
        (ROOT/'detailed.html').write_text(page)  # Keep previously shared links working.
    print(f'Built {output}: {count} paired code panels; {len(headings)} section links; {len(page):,} bytes.')


if __name__ == "__main__":
    build(False)
    build(True)
