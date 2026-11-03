(() => {
  const $ = s => document.querySelector(s);
  const $$ = s => [...document.querySelectorAll(s)];
  const read = key => { try { return localStorage.getItem(key); } catch { return null; } };
  const save = (key,value) => { try { localStorage.setItem(key,value); } catch {} };
  function selectLanguage(box,lang,focus=false) {
    box.querySelectorAll('[role=tab]').forEach(tab => {
      const selected=tab.dataset.lang===lang;
      tab.setAttribute('aria-selected',selected);
      tab.tabIndex=selected?0:-1;
      document.getElementById(tab.getAttribute('aria-controls')).hidden=!selected;
      if(selected&&focus)tab.focus();
    });
  }
  const pref = read('splitwise-language') || 'python';
  $$('.language-pair').forEach(box => {
    selectLanguage(box,pref);
    box.querySelectorAll('[role=tab]').forEach(tab => {
      tab.addEventListener('click',()=>{
        selectLanguage(box,tab.dataset.lang);
        save('splitwise-language',tab.dataset.lang);
      });
      tab.addEventListener('keydown',e=>{
        if(!['ArrowLeft','ArrowRight','Home','End'].includes(e.key))return;
        e.preventDefault();
        const lang=e.key==='Home'?'python':e.key==='End'?'java':tab.dataset.lang==='python'?'java':'python';
        selectLanguage(box,lang,true);save('splitwise-language',lang);
      });
    });
  });
  let toastTimer;
  function toast(text){$('#toast').textContent=text;$('#toast').classList.add('show');clearTimeout(toastTimer);toastTimer=setTimeout(()=>$('#toast').classList.remove('show'),2000);}
  $$('.copy').forEach(button=>button.addEventListener('click',async()=>{
    const pre=[...button.closest('.codebox').querySelectorAll('pre')].find(e=>!e.hidden);
    try { await navigator.clipboard.writeText(pre.innerText);toast('Code copied'); }
    catch {
      const selection=getSelection(),range=document.createRange();range.selectNodeContents(pre);selection.removeAllRanges();selection.addRange(range);toast('Code selected. Press ⌘C or Ctrl+C to copy.');
    }
  }));
  // Tables scroll inside their own container on smaller screens.
  $$('article table').forEach(table=>{const wrap=document.createElement('div');wrap.className='table-wrap';wrap.tabIndex=0;wrap.setAttribute('role','region');wrap.setAttribute('aria-label','Scrollable comparison table');table.before(wrap);wrap.append(table);});
  const links=$$('.toc a');
  const headings=links.map(a=>document.getElementById(a.hash.slice(1)));
  let pending=false;
  function updateProgress(){
    pending=false;
    const start=$('#article').offsetTop;
    const length=$('#article').offsetHeight-innerHeight+80;
    const value=Math.round(Math.max(0,Math.min(100,(scrollY-start)/Math.max(1,length)*100)));
    $('.progress').setAttribute('aria-valuenow',value);$('.progress>div').style.width=value+'%';
    let active=headings[0];for(const h of headings){if(h.getBoundingClientRect().top<=130)active=h;}
    links.forEach(a=>{const selected=a.hash==='#'+active.id;a.classList.toggle('active',selected);if(selected)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current');});
    const current=$('.toc a.active');
    if(current){const nav=$('.toc nav'),r=current.getBoundingClientRect(),n=nav.getBoundingClientRect();if(r.top<n.top||r.bottom>n.bottom)nav.scrollTop+=r.top-n.top-80;}
  }
  addEventListener('scroll',()=>{if(!pending){pending=true;requestAnimationFrame(updateProgress);}}, {passive:true});
  addEventListener('resize',updateProgress);updateProgress();
  $$('details.comparison').forEach(d=>d.addEventListener('toggle',updateProgress));
  function focusMode(on){document.body.classList.toggle('focus-mode',on);$('#focus').setAttribute('aria-pressed',on);$('#exit-focus').hidden=!on;}
  $('#focus').addEventListener('click',()=>focusMode(true));$('#exit-focus').addEventListener('click',()=>focusMode(false));
  $('#expand').addEventListener('click',()=>{const on=$('#expand').getAttribute('aria-pressed')!=='true';$$('details.comparison').forEach(d=>d.open=on);$('#expand').setAttribute('aria-pressed',on);$('#expand').textContent=on?'Collapse comparisons':'Expand comparisons';});
  if(read('splitwise-theme')==='dark')document.documentElement.classList.add('dark');
  $('#theme').addEventListener('click',()=>{const dark=document.documentElement.classList.toggle('dark');save('splitwise-theme',dark?'dark':'light');});
  const dialog=$('#search-dialog');
  function results(){const query=$('#search-input').value.toLowerCase();$('#search-results').replaceChildren();links.filter(a=>a.textContent.toLowerCase().includes(query)).forEach(a=>{const link=a.cloneNode(true);link.removeAttribute('class');link.addEventListener('click',()=>dialog.close());$('#search-results').append(link);});if(!$('#search-results').children.length)$('#search-results').textContent='No matching sections.';}
  $('.search-trigger').addEventListener('click',()=>{dialog.showModal();results();$('#search-input').focus();});
  $('#search-input').addEventListener('input',results);
  dialog.addEventListener('click',e=>{if(e.target===dialog)dialog.close();});
  addEventListener('keydown',e=>{if((e.metaKey||e.ctrlKey)&&e.key.toLowerCase()==='k'){e.preventDefault();dialog.showModal();results();$('#search-input').focus();}if(e.key==='Escape'){document.body.classList.remove('menu-open');focusMode(false);}});
  addEventListener('beforeprint',()=>$$('details.comparison').forEach(d=>{d.dataset.beforePrint=d.open;d.open=true;}));
  addEventListener('afterprint',()=>$$('details.comparison').forEach(d=>d.open=d.dataset.beforePrint==='true'));
})();
