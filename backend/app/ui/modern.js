(() => {
const $ = (s, p=document)=>p.querySelector(s);
const $$ = (s, p=document)=>Array.from(p.querySelectorAll(s));

const input = $('#q');
const btnGo = $('#btnGo');
const sug = $('#suggest');
const state = $('#state');
const treeBox = $('#tree');
const detailBox = $('#detail');
const textBox = $('#textResults');
const toast = $('#toast');

const L4 = $('#L4'), L6=$('#L6'), L8=$('#L8'), L10=$('#L10');
const moreBtns = $$('.more');
const treePrefix = $('#treePrefix');
const treeCounts = $('#treeCounts');
const detailBody = $('#detailBody');

const xls = $('#xls'); const btnXls = $('#btnXls'); const batchMsg = $('#batchMsg');

const cache = new Map();
const pending = new Map(); // key -> AbortController

const debounce = (fn, ms=150) => {
  let t; return (...a)=>{clearTimeout(t); t=setTimeout(()=>fn(...a), ms)};
};

const isDigits = v => /^\d+(?:\.\d+)?$/.test((v||'').trim());
const norm = v => (v||'').replace(/\./g,'').trim();

function toastMsg(msg, ms=2200){
  toast.textContent = msg; toast.hidden = false;
  setTimeout(()=>toast.hidden = true, ms);
}

async function fetchJSON(url){
  if (cache.has(url)) return cache.get(url);
  if (pending.has(url)) pending.get(url).abort();
  const ctl = new AbortController();
  pending.set(url, ctl);
  try{
    const r = await fetch(url, {signal: ctl.signal});
    if(!r.ok) throw new Error(r.status+' '+r.statusText);
    const j = await r.json();
    cache.set(url, j);
    return j;
  } finally {
    pending.delete(url);
  }
}

function renderSuggest(list){
  if (!list || list.length===0){ sug.hidden = true; sug.innerHTML=''; return; }
  sug.innerHTML = list.map((s,i)=> (
    `<div role="option" data-code="${s.code}" aria-selected="${i===0?'true':'false'}"><b>${s.code}</b> — ${s.title_ru||''}</div>`
  )).join('');
  sug.hidden = false;
}

function pick(code){
  input.value = code; sug.hidden = true; go();
}

sug.addEventListener('click', e=>{
  const div = e.target.closest('div[role="option"]');
  if(!div) return;
  pick(div.dataset.code);
});

document.addEventListener('keydown', e=>{
  if (sug.hidden) return;
  const items = $$('#suggest div[role="option"]');
  if (!items.length) return;
  let i = items.findIndex(n => n.getAttribute('aria-selected')==='true');
  if (e.key==='ArrowDown'){ i = Math.min(items.length-1, i+1); items.forEach(n=>n.setAttribute('aria-selected','false')); items[i].setAttribute('aria-selected','true'); e.preventDefault(); }
  if (e.key==='ArrowUp'){ i = Math.max(0, i-1); items.forEach(n=>n.setAttribute('aria-selected','false')); items[i].setAttribute('aria-selected','true'); e.preventDefault(); }
  if (e.key==='Enter'){ const code = items[i].dataset.code; pick(code); e.preventDefault(); }
  if (e.key==='Escape'){ sug.hidden = true; }
});

async function typeahead(){
  const q = input.value.trim();
  if (!q || q.length<2){ sug.hidden=true; return; }
  try{
    if (isDigits(q)){
      const j = await fetchJSON('/codes/suggest?q='+encodeURIComponent(q));
      renderSuggest(j.suggest || []);
    } else {
      const url = '/codes/search_fts?q='+encodeURIComponent(q);
      const r = await fetch(url, {method:'GET'});
      const list = r.ok ? await r.json() : await fetchJSON('/codes/search?q='+encodeURIComponent(q));
      renderSuggest(Array.isArray(list)?list:(list.suggest||[]));
    }
  }catch(err){ /* ignore */ }
}

async function go(){
  const q = input.value; const c = norm(q);
  state.textContent = 'Загрузка...'; state.classList.add('muted');
  treeBox.hidden = true; detailBox.hidden = true; textBox.hidden = true;

  try{
    if(!c){ state.textContent = 'Введите код или текст.'; return; }

    if(!/^\d+$/.test(c)){
      const url = '/codes/search_fts?q='+encodeURIComponent(q);
      const r = await fetch(url);
      let arr = [];
      if (r.ok) arr = await r.json(); else arr = await fetchJSON('/codes/search?q='+encodeURIComponent(q));
      $('#textList').innerHTML = arr.map(x => `<div class="item" onclick="window.__pick('${x.code}')"><b>${x.code}</b> — ${x.title_ru||''}</div>`).join('') || '<div class="muted">Пусто</div>';
      textBox.hidden = false; state.textContent = `Найдено: ${arr.length}`; return;
    }

    if([2,4,6,8].includes(c.length)){
      const j = await fetchJSON('/codes/list?prefix='+encodeURIComponent(c)+'&limit=5000');
      treePrefix.textContent = j.prefix || '—';
      treeCounts.textContent = `4: ${j.counts["4"]} • 6: ${j.counts["6"]} • 8: ${j.counts["8"]} • 10: ${j.counts["10"]}`;

      const showChunk = 60;
      function renderLen(L){
        const arr = j.items[String(L)] || [];
        const box = (L===4?L4:L===6?L6:L===8?L8:L10);
        box.innerHTML = arr.slice(0, showChunk).map(x => `<div class="item" onclick="window.__pick('${x.code}')"><b>${x.code}</b> — ${x.title_ru||''}</div>`).join('') || '<div class="muted">нет</div>';
        const btn = document.querySelector(`button.more[data-len="${L}"]`);
        if (!btn) return;
        if (arr.length > showChunk){
          btn.hidden = false; let shown = showChunk;
          btn.onclick = () => {
            const add = arr.slice(shown, shown+showChunk).map(x => `<div class="item" onclick="window.__pick('${x.code}')"><b>${x.code}</b> — ${x.title_ru||''}</div>`).join('');
            box.insertAdjacentHTML('beforeend', add); shown += showChunk;
            if (shown >= arr.length) btn.hidden = true;
          };
        } else { btn.hidden = true; }
      }
      [4,6,8,10].forEach(L => renderLen(L));
      treeBox.hidden = false; state.textContent = `Префикс ${c}`; return;
    }

    if(c.length===10){
      const j = await fetchJSON('/classify/'+c);
      detailBody.innerHTML = `
      <div><span class="badge">Код</span> <b>${j.hs_code}</b></div>
      <div><span class="badge">Наименование</span> ${j.title||'—'}</div>
      <div><span class="badge">Пошлина</span> ${j.duty?.duty || 'N/A'} <span class="muted">${j.duty?.version||''}</span></div>
      <div><span class="badge">НДС</span> ${j.vat?.rate ?? '—'}% <span class="muted">(${j.vat?.source||''})</span></div>
      `;
      detailBox.hidden = false; state.textContent = 'Готово'; return;
    }

    state.textContent = 'Введите 2/4/6/8/10 знаков или текст.';
  } catch (e){
    state.textContent = 'Ошибка загрузки.'; toastMsg('Ошибка: '+(e?.message||e));
  }
}

window.__pick = pick;

input.addEventListener('input', debounce(typeahead, 140));
input.addEventListener('keydown', e=>{ if(e.key==='Enter'){ e.preventDefault(); go(); }});
btnGo.addEventListener('click', go);

btnXls.addEventListener('click', async ()=>{
  const f = xls.files?.[0]; if (!f){ toastMsg('Выберите файл XLSX'); return; }
  btnXls.disabled = true; batchMsg.textContent = 'Отправка...';
  try{
    const fd = new FormData(); fd.append('file', f);
    const r = await fetch('/batch/classify_xlsx', { method:'POST', body: fd });
    if (!r.ok) throw new Error('HTTP '+r.status);
    const blob = await r.blob(); const a = document.createElement('a');
    a.href = URL.createObjectURL(blob); a.download = 'classified.xlsx'; a.click(); URL.revokeObjectURL(a.href);
    batchMsg.textContent = 'Файл сформирован';
  }catch(e){ batchMsg.textContent = 'Ошибка. Проверьте формат.'; toastMsg('Не удалось классифицировать файл.'); }
  finally{ btnXls.disabled = false; }
});

})();

