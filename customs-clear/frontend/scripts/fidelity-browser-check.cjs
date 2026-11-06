// Real-browser source fidelity. Successful responses are never substituted.
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),crypto=require('node:crypto');
const {chromium}=require('playwright');
const compact=s=>String(s).replace(/[\s\u200b\u00ad]/g,'');
async function run(){
 const [base,expectedFile,out]=process.argv.slice(2),expected=JSON.parse(fs.readFileSync(expectedFile));
 fs.mkdirSync(out,{recursive:true});
 const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{})});
 const report={snapshot_sha256:expected.snapshot_sha256,source_corpus_sha256:expected.source_corpus_sha256,positive:[],negative:null};
 try{
  for(const [width,zoom] of [[1440,1],[1280,1],[1280,1.25]]){
   // Desktop zoom equivalence: CSS viewport shrinks while physical output
   // remains width x 1000. CSS document zoom alone mis-scales vh/fixed dialogs.
   const context=await browser.newContext({viewport:{width:Math.round(width/zoom),height:Math.round(1000/zoom)},deviceScaleFactor:zoom,permissions:['clipboard-read','clipboard-write']});
   const page=await context.newPage(),responses=[],errors=[];
   page.on('pageerror',e=>errors.push(String(e)));
   page.on('response',r=>{if(/\/api\/(?:tnved\/|v1\/tnved\/)/.test(r.url()))responses.push({url:r.url(),status:r.status()});});
   await page.goto(base+'/tnved',{waitUntil:'networkidle'});
   const health=await(await context.request.get(base+'/api/health/ready')).json();
   assert.equal(health.recovered_catalog.snapshot_sha256,expected.snapshot_sha256);
   assert.equal(health.recovered_catalog.navigation_enabled,true);
   const tree=page.getByTestId('tnved-tree'),node=id=>tree.locator(`button[data-node-id="${id}"]`);
   async function open(id){const b=node(id);await b.waitFor();if(await b.getAttribute('aria-expanded')==='false')await b.click();}
   async function reveal(id){for(const parent of expected.paths[id])await open(parent);await node(id).waitFor();await node(id).scrollIntoViewIfNeeded();await page.waitForFunction(key=>{let e=document.querySelector(`[data-testid="tnved-tree"] button[data-node-id="${key}"]`);for(;e;e=e.parentElement){if(Number(getComputedStyle(e).opacity)<0.99)return false;}return true;},id);}
   await open('XVI');await node('85').waitFor();
   for(const ch of ['84','85'])assert(compact(await node(ch).textContent()).includes(compact(expected.titles[ch])));
   const prefix=path.join(out,`${width}-zoom${zoom}`);
   await page.screenshot({path:prefix+'-collapsed.png'});
   await open('84');await node(expected.root84[0]).waitFor();
   await page.screenshot({path:prefix+'-84-expanded.png'});await node('84').click();
   await open('85');await node('8549').waitFor({state:'attached'});
   const order=await tree.locator('button.tree-node-branch').evaluateAll(nodes=>nodes.filter(n=>n.closest('[data-testid="tnved-tree"]')).map(n=>n.getAttribute('data-node-id')));
   const positions=['8502','850300','8504','8517','853400','854800','8549'].map(id=>order.indexOf(id));
   assert(positions.every(n=>n>=0)&&positions.every((n,i)=>!i||n>positions[i-1]),JSON.stringify(positions));
   await reveal('850300');assert.equal(compact(await node('850300').locator('.tree-code').textContent()),'850300');
   await page.screenshot({path:prefix+'-85-start.png'});
   for(const id of ['8502','850300','8504','8517','853400','854800','8549']){
    await reveal(id);await open(id);
    const geometry=await node(id).locator('.tree-code').evaluate(e=>{const r=document.createRange();r.selectNodeContents(e);return{width:e.getBoundingClientRect().width,content:r.getBoundingClientRect().width,right:e.getBoundingClientRect().right,viewport:innerWidth,text:e.textContent};});
    assert(geometry.content<=geometry.width+1&&geometry.right<=geometry.viewport+1,JSON.stringify(geometry));
   }
   await node('8549').scrollIntoViewIfNeeded();await page.screenshot({path:prefix+'-85-end.png'});
   const checked=[];
   for(const code of expected.test_leaves){
    await reveal(code);await node(code).click();
    const card=page.getByRole('article',{name:'Позиция восстановленного справочника'});
    await card.getByTestId('recovered-name').waitFor();
    assert.equal(await page.getByTestId('selected-code').textContent(),code);
    assert.equal(await card.getByTestId('recovered-name').textContent(),expected.details[code].name);
    assert.deepEqual(await card.getByRole('list',{name:'Полный путь из источника'}).locator('li').allTextContents(),expected.details[code].path);
    await card.getByText('Подтверждённые ставки отсутствуют',{exact:true}).waitFor();
    await card.getByRole('button',{name:'Копировать код',exact:true}).click();
    await card.getByRole('button',{name:'Код скопирован',exact:true}).waitFor();
    assert.equal(await page.evaluate(()=>navigator.clipboard.readText()),code);
    checked.push(code);if(code.startsWith('01'))await page.screenshot({path:prefix+'-01-codeless-card.png'});
    await page.getByRole('button',{name:'Закрыть',exact:true}).click();
   }
   const search=page.getByPlaceholder('Поиск по коду или наименованию…');await search.fill('85');
   await page.getByTestId('search-total').filter({hasText:`Найдено: ${expected.search85_total}.`}).waitFor();
   await page.getByRole('button',{name:'Последняя страница',exact:true}).click();
   await tree.locator(`[data-search-id="${expected.last85}"]`).waitFor();
   assert.equal(await tree.locator('[data-search-id]').last().getAttribute('data-search-id'),expected.last85);
   assert(await page.getByRole('button',{name:'Далее',exact:true}).isDisabled());
   await page.screenshot({path:prefix+'-search-last.png'});await page.getByRole('button',{name:'Очистить',exact:true}).click();
   for(const section of expected.sections)await open(section);
   const names={};for(const ch of Object.keys(expected.titles)){
    const label=await node(ch).locator('span').last().textContent();names[ch]=label;assert.equal(compact(label),compact(expected.titles[ch]));
   }
   fs.writeFileSync(prefix+'-DOM.html',await page.content());fs.writeFileSync(prefix+'-network.json',JSON.stringify(responses,null,2));
   assert.equal(Object.keys(names).length,96);assert.deepEqual(errors,[]);assert(responses.every(r=>r.status===200),JSON.stringify(responses.filter(r=>r.status!==200)));
   report.positive.push({physical_width:width,render_scale:zoom,css_viewport_width:Math.round(width/zoom),checked_chapter_names:96,checked_leaf_cards:checked,order85:positions,search85_total:expected.search85_total,last85:expected.last85,page_errors:errors,catalog_requests:responses.length,frontend_index_sha256:crypto.createHash('sha256').update(await(await context.request.get(base+'/tnved')).body()).digest('hex')});
   await context.close();
  }
  // Separate negative test: one request fails, retry uses the real server.
  const context=await browser.newContext({viewport:{width:1280,height:1000}}),page=await context.newPage(),errors=[];
  page.on('pageerror',e=>errors.push(String(e)));let failed=false;
  await page.route('**/api/tnved/children/85?*',async route=>{if(!failed){failed=true;await new Promise(r=>setTimeout(r,600));await route.abort('failed');}else await route.continue();});
  await page.goto(base+'/tnved',{waitUntil:'networkidle'});const tree=page.getByTestId('tnved-tree');
  await tree.locator('button[data-node-id="XVI"]').click();const group=tree.locator('button[data-node-id="85"]');await group.waitFor();await group.click();
  await tree.getByText('Загрузка…',{exact:true}).waitFor();await tree.getByRole('alert').waitFor();
  assert.equal(await tree.getByText('Нет элементов',{exact:true}).count(),0);
  await page.screenshot({path:path.join(out,'failure-visible.png')});await tree.getByRole('button',{name:'Повторить загрузку',exact:true}).click();
  await tree.locator('button[data-node-id="850300"]').waitFor();assert.equal(await tree.getByRole('alert').count(),0);assert.deepEqual(errors,[]);
  report.negative={loading_visible:true,failed_visible:true,false_empty:false,retry_real_HTTP:true,page_errors:errors};
  await page.screenshot({path:path.join(out,'retry-restored.png')});await context.close();
  report.status='PASS';fs.writeFileSync(path.join(out,'browser-fidelity.json'),JSON.stringify(report,null,2)+'\n');console.log(JSON.stringify(report));
 }finally{await browser.close();}
}
run().catch(e=>{console.error(e);process.exitCode=1;});
