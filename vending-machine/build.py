"""Regenerate the Vending Machine article for GitHub Pages."""
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
def build():
    article = ROOT / 'TUTORIAL-DETAILED.md'
    soup = BeautifulSoup(markdown.markdown(article.read_text(), extensions=['tables', 'fenced_code', 'toc']), 'html.parser')
    soup.h1.decompose()
    for h in soup.find_all(['h2', 'h3']):
        titles = {'Understanding the problem':'Understanding the Problem', 'Core entities and relationships':'Core Entities and Relationships', 'Class design':'Class Design', 'Clarifying questions':'Clarifying Questions', 'Final requirements':'Final Requirements', 'Final class design':'Final Class Design', 'What is expected at each level?':'What is Expected at Each Level?', 'Test your understanding':'Test Your Understanding', 'Complete reference implementations':'Complete Code Implementation'}
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
    scope_items = scope.find_next_sibling('ul')
    assert scope_items is not None
    scope_text = scope.get_text() + '\n' + '\n'.join('- ' + item.get_text() for item in scope_items.find_all('li', recursive=False))
    specification = 'Requirements:\n' + '\n'.join(
        f'{i}. {item.get_text()}'
        for i, item in enumerate(requirement_list.find_all('li', recursive=False), 1)
    ) + '\n\n' + scope_text
    panel = frag('<div class="codebox requirements-panel"><div class="codebar">'
        '<span class="code-title">Final requirements</span>'
        '<button class="copy" aria-label="Copy requirements">▢</button></div>'
        + code_panel(specification, 'text') + '</div>')
    requirement_list.replace_with(panel)
    scope.decompose()
    scope_items.decompose()

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
        assessment = re.match(r'(Bad|Good|Great) Solution: ', text)
        if not assessment: continue
        tone = {'Bad': 'bad', 'Good': 'neutral', 'Great': 'good'}[assessment.group(1)]
        detail = soup.new_tag('details', attrs={'class': 'comparison ' + tone})
        summary = soup.new_tag('summary')
        heading = soup.new_tag('span', attrs={'class': 'comparison-title'}); heading.string = text
        summary.append(heading)
        summary.append(frag('<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true" focusable="false"><path d="M16.59 8.59 12 13.17 7.41 8.59 6 10l6 6 6-6z"></path></svg>'))
        detail.append(summary)
        body = soup.new_tag('div',attrs={'class':'comparison-body'})
        nxt = h.find_next_sibling()
        while nxt and nxt.name not in ['h2','h3','h4','h5']:
            # A standalone bold topic starts the next discussion within this class.
            if nxt.name == 'p' and nxt.find('strong') and nxt.get_text() == nxt.strong.get_text(): break
            following = nxt.find_next_sibling(); body.append(nxt.extract()); nxt=following
        detail.append(body); h.replace_with(detail)

    first = soup.find('h2').find_next_sibling('p')
    first['class'] = 'callout intro'
    if first.contents and isinstance(first.contents[0],str):
        first.contents[0].replace_with(str(first.contents[0]).removeprefix('💸 '))
    first.insert(0,frag('<strong class="callout-title">What is a vending machine?</strong>'))
    for quote in soup.find_all('blockquote'):
        if 'You:' in quote.get_text(): quote['class']='dialogue'

    # Keep the full implementations together at the end of the walkthrough.
    anchor = soup.find(id='complete-reference-implementations')
    ident = 'complete-code'
    widget = '<div class="codebox language-pair full-code" data-code="complete-code"><div class="codebar"><div role="tablist" aria-label="Complete implementation language">'
    for lang, filename in [('python','vending_machine.py'),('java','VendingMachine.java')]:
        widget += f'<button role="tab" id="{ident}-{lang}-tab" aria-controls="{ident}-{lang}" aria-selected="{str(lang == "python").lower()}" tabindex="{0 if lang == "python" else -1}" data-lang="{lang}">{filename}</button>'
    widget += '</div><button class="copy" aria-label="Copy visible code">▢</button></div>'
    for lang, filename in [('python','vending_machine.py'),('java','VendingMachine.java')]:
        widget += code_panel((ROOT/filename).read_text(),lang,ident+'-'+lang)
    widget += '</div>'
    node = frag(widget)
    node.find(id=ident+'-java')['hidden']=''
    for lang in ['python','java']: node.find(id=ident+'-'+lang)['aria-labelledby']=ident+'-'+lang+'-tab'
    anchor.find_next_sibling('p').insert_after(node)

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
    <html lang="en"><head><meta charset="utf-8"><link rel="icon" type="image/svg+xml" href="../favicon.svg"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Vending Machine Low Level Design</title><meta name="description" content="A complete vending machine low-level design walkthrough using the State pattern with runnable Python and Java."><style>{css}</style></head><body>
    <a class="skip" href="#article">Skip to article</a>

    <main class="main" id="top"><header class="topbar"><button class="search-trigger" aria-label="Search article sections"><span class="search-label"><svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="10.75" cy="10.75" r="6.75"/><path d="m16 16 4.25 4.25"/></svg><span>Search sections</span></span><kbd>⌘ K</kbd></button><div class="top-actions"><a class="article-home" href="#top">Low Level Design <span>/</span> Vending Machine</a><button id="theme" aria-label="Switch to dark mode" title="Switch to dark mode"><svg class="theme-moon" viewBox="0 0 24 24" aria-hidden="true"><path d="M20.5 13.1A8.5 8.5 0 0 1 10.9 3.5 8.5 8.5 0 1 0 20.5 13.1Z"/></svg><svg class="theme-sun" viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2m0 16v2M2 12h2m16 0h2M4.93 4.93l1.42 1.42m11.3 11.3 1.42 1.42M4.93 19.07l1.42-1.42m11.3-11.3 1.42-1.42"/></svg></button></div></header>
    <div class="outer"><div class="layout"><article id="article"><div class="article-header"><div class="eyebrow">Low Level Design</div><h1>Vending Machine</h1><p class="metadata">Independent study article <span>·</span> <span class="difficulty">◉ medium</span> <span>·</span> Python &amp; Java </p></div><div class="feature-card green"><span class="feature-icon">⌘</span><div><h2>Complete Code Implementation</h2><p>Read the working solution in your preferred language</p></div><a href="#complete-reference-implementations">View Code &nbsp; →</a></div><div class="feature-card coral"><span class="feature-icon">≋</span><div><h2>Explore the Design Trade-offs</h2><p>Compare approaches and understand the decisions</p></div><a href="#machinestate">Compare &nbsp; →</a></div>
    {str(soup).lstrip()}
    <footer class="article-footer"><p>Written by Yash Pandit.</p><a href="#top">↑ Back to top</a></footer></article><aside class="toc" aria-label="On this page"><div class="reading-tools"><button id="focus" aria-pressed="false">◫ &nbsp; Focus</button><button id="expand" aria-pressed="false">Expand comparisons</button></div><div class="progress-label">Reading Progress</div><div class="progress" role="progressbar" aria-label="Reading progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0"><div></div></div><h2>On This Page</h2><nav>{toc}</nav></aside></div></div></main>
    <button id="exit-focus" hidden>◫ Exit focus</button><dialog id="search-dialog"><form method="dialog"><input id="search-input" aria-label="Search sections" placeholder="Search article sections…" autocomplete="off"><button aria-label="Close search">Esc</button></form><nav id="search-results"></nav></dialog><div id="toast" role="status" aria-live="polite"></div><script>{js}</script></body></html>'''
    (ROOT/'index.html').write_text(page)
    print(f'Built index.html with {len(headings)} section links.')


if __name__ == "__main__":
    build()
