// Run with Playwright on NODE_PATH; uses a fresh browser profile, never a user session.
const {chromium}=require('playwright');
const fs=require('node:fs');
const path=require('node:path');
const assert=require('node:assert/strict');
(async()=>{
  const url=process.argv[2], output=path.resolve(process.argv[3]);
  assert(url && output,'Supply page URL and evidence directory');
  fs.mkdirSync(output,{recursive:true});
  let browser;
  try { browser=await chromium.launch({headless:true}); }
  catch { browser=await chromium.launch({headless:true,channel:'msedge'}); }
  const results=[];
  try {
    for(const width of [1440,390]){
      const context=await browser.newContext({viewport:{width,height:1000},deviceScaleFactor:1});
      const page=await context.newPage(), errors=[];
      page.on('pageerror',e=>errors.push(e.message));
      assert.equal((await page.goto(url)).status(),200);
      await page.locator('#live-title').filter({hasText:/match in progress|Changing battlefield|Server status unavailable/}).waitFor();
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth),true,'Horizontal page overflow');
      await page.screenshot({path:path.join(output,`page-${width}.png`),fullPage:true});
      if(width===1440) await page.screenshot({path:path.join(output,'hero.png')});
      await page.getByText("The game won't connect.",{exact:true}).click();
      assert(await page.getByText(/No port forwarding is needed/).isVisible());
      assert.deepEqual(errors,[]);
      results.push({width,http:200,overflow:false,pageErrors:errors});
      await context.close();
    }
    // Exercise stale-data handling in an isolated test response.
    const context=await browser.newContext();
    const page=await context.newPage();
    await page.route('**/status.json',route=>route.fulfill({json:{updated_utc:'2000-01-01T00:00:00Z',teams:[]}}));
    await page.goto(url);
    await page.getByRole('heading',{name:'Server status unavailable'}).waitFor();
    await context.close();
    for(const fixture of [{ready:false},{ready:true,url:'https://example.invalid/client.zip',sha256:'a'.repeat(64),version:'bad',bytes:1}]){
      const unavailable=await browser.newContext();
      const page=await unavailable.newPage();
      await page.route('**/release.json',route=>route.fulfill({json:fixture}));
      await page.goto(url);
      await page.getByText('Download temporarily unavailable',{exact:true}).waitFor();
      assert.equal(await page.locator('#download').getAttribute('href'),'#get-started');
      assert.equal(await page.locator('#checksum').isVisible(),false);
      await unavailable.close();
    }
    fs.writeFileSync(path.join(output,'checks.json'),JSON.stringify({results,staleStatusRejected:true,invalidReleaseRejected:true},null,2));
    console.log(JSON.stringify({results,staleStatusRejected:true,invalidReleaseRejected:true}));
  } finally { await browser.close(); }
})().catch(error=>{console.error(error);process.exitCode=1;});
