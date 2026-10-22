const {chromium}=require("playwright");
const assert=require("node:assert/strict");
const path=require("node:path");
const fs=require("node:fs/promises");
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.BROWSER_CHANNEL?{channel:process.env.BROWSER_CHANNEL}:{})});
  const base=process.env.DEMO_URL||"http://127.0.0.1:8770";
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1100}});
    await page.goto(base);
    for(const kind of ["roads","flood"]){
      const data=await page.request.get(`${base}/examples/${kind}.geojson`);
      assert.equal(data.status(),200);
      assert.deepEqual(await data.json(),JSON.parse(await fs.readFile(path.resolve(__dirname,`../examples/${kind}.geojson`),"utf8")));
    }
    await page.locator("#load-example").click();
    await page.waitForFunction(()=>document.getElementById("workspace-status").textContent.includes("Przykład wczytany")&&!document.getElementById("load-example").disabled);
    assert.equal(await page.locator("#roads-file").inputValue(),"");
    assert.equal(await page.locator("#flood-file").inputValue(),"");
    assert.equal(await page.locator("#route-start").inputValue(),"52,21");
    assert.equal(await page.locator("#route-end").inputValue(),"52,21.002");
    await page.locator("#calculate-route").click();
    await page.waitForFunction(()=>document.getElementById("workspace-status").textContent.includes("Analiza zakończona"));
    assert.equal(await page.locator("#own-route").innerText(),"582 m");
    assert.equal(await page.locator("#own-blocked").innerText(),"1 / 4");
    assert.equal(await page.locator("#data-mode").innerText(),"DANE PRZYKŁADOWE");
    assert.equal(await page.locator(".history-item").count(),1);
    // Cancelling replacement leaves both data and saved results intact.
    page.once("dialog",dialog=>dialog.dismiss());await page.locator("#load-example").click();
    assert.equal(await page.locator(".history-item").count(),1);
    await fs.mkdir(path.resolve(__dirname,"../docs/assets"),{recursive:true});
    for(const width of [1440,390]){
      await page.setViewportSize({width,height:1100});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false);
      await page.screenshot({path:path.resolve(__dirname,`../docs/assets/recruiter-${width}.png`),fullPage:true});
    }
    await page.locator("#access-details summary").click();
    page.once("dialog",dialog=>dialog.accept());await page.locator("#delete-workspace").click();
    await page.waitForFunction(()=>document.getElementById("workspace-status").textContent.includes("Przestrzeń usunięta"));
    console.log("Recruiter PASS: two clicks, no files/account/operator key, real calculation and history, downloadable fixtures, sample labels, safe cancellation, desktop/mobile.");
  } finally {await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
