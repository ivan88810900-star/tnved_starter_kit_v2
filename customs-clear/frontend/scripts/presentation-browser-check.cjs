// Actual Chrome observations. No successful HTTP response is substituted.
const fs=require('node:fs'),path=require('node:path'),assert=require('node:assert/strict'),crypto=require('node:crypto');
const {execFileSync}=require('node:child_process');
const {chromium}=require('playwright');

async function run(){
 const [base,expectedFile,out]=process.argv.slice(2),expected=JSON.parse(fs.readFileSync(expectedFile));
 fs.mkdirSync(out,{recursive:true});
 if(!process.argv.includes('--skip-active-regression')){
  const regression=execFileSync(process.execPath,[path.join(__dirname,'fidelity-browser-check.cjs'),base,expectedFile,path.join(out,'active-regression')],{encoding:'utf8',env:process.env});
  fs.writeFileSync(path.join(out,'active-regression.log'),regression);
 }
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{})});
 const report={observer:'A0 real Chrome; not independent Claude',snapshot_sha256:expected.snapshot_sha256,expectations_sha256:crypto.createHash('sha256').update(fs.readFileSync(expectedFile)).digest('hex'),configurations:[],negative:null};
 try{
  for(const [width,scale] of [[1440,1],[1280,1],[1280,1.25]]){
   const context=await browser.newContext({viewport:{width:Math.round(width/scale),height:Math.round(1100/scale)},deviceScaleFactor:scale,permissions:['clipboard-read','clipboard-write']});
   const page=await context.newPage(),errors=[],responses=[];
   page.on('pageerror',e=>errors.push(String(e)));
   page.on('response',r=>{if(/\/api\/(?:tnved\/|v1\/tnved\/)/.test(r.url()))responses.push({url:r.url(),status:r.status()});});
   await page.goto(base+'/tnved',{waitUntil:'networkidle'});
   const tree=page.getByTestId('tnved-tree'),node=id=>tree.locator(`button[data-node-id="${id}"]`);
   async function open(id){const b=node(id);await b.waitFor();if(await b.getAttribute('aria-expanded')==='false')await b.click();}
   const markerChecked=[];
   for(const chapter of [...new Set(expected.markers.map(r=>r.chapter))]){
    await open(expected.chapter_sections[chapter]);await open(chapter);
    const rows=expected.markers.filter(r=>r.chapter===chapter);
    for(const row of rows){
     const mark=tree.locator(`[data-marker-id="${row.id}"]`);await mark.waitFor();
     assert.equal(await mark.getAttribute('data-printed-code'),row.printed_code);
     assert.equal(await mark.locator('button').count(),0);
     await mark.getByText('Неактивная отметка источника',{exact:false}).waitFor();
     const link=mark.getByRole('link',{name:`Фрагмент оригинала · стр. ${row.page}`});await link.waitFor();
     assert.equal(await link.getAttribute('href'),row.fragment_url);
     if(row.source_url)assert.equal(await mark.getByRole('link',{name:'Ссылка на PDF',exact:true}).getAttribute('href'),row.source_url+'#page='+row.page);
     const order=await tree.locator('[data-node-id], [data-marker-id]').evaluateAll(ns=>ns.map(n=>n.getAttribute('data-node-id')||n.getAttribute('data-marker-id')));
     if(row.previous_root)assert(order.indexOf(row.previous_root)<order.indexOf(row.id));
     if(row.next_root)assert(order.indexOf(row.id)<order.indexOf(row.next_root));
     await mark.click();assert.equal(await page.getByTestId('selected-code').count(),0);
     markerChecked.push(row.printed_code);
    }
    const ids=rows.map(r=>r.id),actual=await tree.locator('[data-marker-id]').evaluateAll(ns=>ns.map(n=>n.getAttribute('data-marker-id')));
    assert.deepEqual(actual.filter(id=>ids.includes(id)),ids);
   }
   assert.equal(markerChecked.length,37);
   const prefix=path.join(out,`${width}-scale${scale}`);
   const first=expected.markers.find(r=>r.printed_code==='[0503]');
   const firstMarker=tree.locator(`[data-marker-id="${first.id}"]`);await firstMarker.scrollIntoViewIfNeeded();
   await page.screenshot({path:prefix+'-reserved-marker.png'});
   if(width===1440){
    const [popup]=await Promise.all([page.waitForEvent('popup'),firstMarker.getByRole('link',{name:`Фрагмент оригинала · стр. ${first.page}`,exact:true}).click()]);
    await popup.waitForLoadState('load');await popup.locator('img').waitFor();
    await popup.waitForFunction(()=>{const i=document.querySelector('img');return i&&i.complete&&i.naturalWidth>100;});
    await popup.screenshot({path:prefix+'-reserved-original.png'});await popup.close();
   }
   const cards=[];
   async function show(code){
    const target=expected.presentation_cases[code],leaf=target.navigation_leaf||code;
    await page.getByPlaceholder('Поиск по коду или наименованию…').fill(leaf);
    await tree.locator(`[data-search-id="${leaf}"]`).click();
    const card=page.getByRole('article',{name:'Позиция восстановленного справочника'});await card.getByTestId('recovered-name').waitFor();
    if(leaf!==code){await card.getByRole('navigation',{name:'Путь к позиции'}).getByRole('button').filter({hasText:target.name}).last().click();}
    await page.waitForFunction(name=>document.querySelector('[data-testid="recovered-name"]')?.textContent===name,target.name);
    assert.equal(await card.getByTestId('recovered-name').textContent(),target.name);
    await card.getByTestId('presentation-limitation').waitFor();
    const imgs=card.getByTestId('source-original-fragment');assert.equal(await imgs.count(),target.fragments.length);
    for(let i=0;i<target.fragments.length;i++){
     await imgs.nth(i).scrollIntoViewIfNeeded();await imgs.nth(i).evaluate(img=>img.decode());
     const box=await imgs.nth(i).evaluate(img=>({width:img.getBoundingClientRect().width,right:img.getBoundingClientRect().right,viewport:innerWidth,natural:img.naturalWidth}));
     assert(box.natural>100&&box.width>100&&box.right<=box.viewport+1,JSON.stringify(box));
     const response=await context.request.get(base+target.fragments[i].url);
     assert.equal(response.status(),200);assert.equal(crypto.createHash('sha256').update(await response.body()).digest('hex'),target.fragments[i].sha256);
    }
    if(target.spacing){const d=card.getByTestId('spacing-difference');await d.waitFor();assert((await d.textContent()).includes(target.spacing.source_text));assert((await d.textContent()).includes(target.spacing.display_text));assert((await d.textContent()).includes('не согласовано автоматически'));}
    await card.getByRole('button',{name:'Копировать код',exact:true}).click();await card.getByRole('button',{name:'Код скопирован',exact:true}).waitFor();assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),code);
    await imgs.first().scrollIntoViewIfNeeded();await page.screenshot({path:prefix+'-'+code+'-original.png'});
    cards.push(code);return card;
   }
   for(const code of Object.keys(expected.presentation_cases)){
    await show(code);await page.getByRole('button',{name:'Закрыть',exact:true}).click();
   }
   // Complete parent-child navigation with source formatting present.
   const card=await show('7002320000'),target=expected.presentation_cases['7002320000'];
   await card.getByRole('navigation',{name:'Путь к позиции'}).getByRole('button').filter({hasText:target.parent_name}).last().click();
   await page.waitForFunction(name=>document.querySelector('[data-testid="recovered-name"]')?.textContent===name,target.parent_name);
   await card.getByRole('heading',{name:'Дочерние узлы',exact:true}).waitFor();
   await card.getByRole('button').filter({hasText:target.printed_code}).last().click();
   await page.waitForFunction(name=>document.querySelector('[data-testid="recovered-name"]')?.textContent===name,target.name);
   await page.getByRole('button',{name:'Закрыть',exact:true}).click();
   assert.deepEqual(errors,[]);assert(responses.every(r=>r.status===200),JSON.stringify(responses.filter(r=>r.status!==200)));
   fs.writeFileSync(prefix+'-DOM.html',await page.content());fs.writeFileSync(prefix+'-network.json',JSON.stringify(responses,null,2));
   report.configurations.push({physical_width:width,render_scale:scale,checked_markers:markerChecked,source_cards:cards,parent_child_round_trip:true,source_images_decoded:true,clipboard_preserved:true,page_errors:errors,catalog_requests:responses.length});await context.close();
  }
  const context=await browser.newContext({viewport:{width:1280,height:1100}}),page=await context.newPage();
  await page.route('**/api/v1/tnved/7002320000/source-fragments/*.png',r=>r.abort('failed'));
  await page.goto(base+'/tnved',{waitUntil:'networkidle'});await page.getByPlaceholder('Поиск по коду или наименованию…').fill('7002320000');await page.locator('[data-search-id="7002320000"]').click();
  await page.getByRole('alert').filter({hasText:'Точное оформление не подтверждено'}).waitFor();
  await page.screenshot({path:path.join(out,'missing-original-visible.png')});report.negative={original_load_failure_is_explicit:true};await context.close();
  report.status='PASS';fs.writeFileSync(path.join(out,'presentation-browser.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
 }finally{await browser.close();}
}
run().catch(e=>{console.error(e);process.exitCode=1;});
