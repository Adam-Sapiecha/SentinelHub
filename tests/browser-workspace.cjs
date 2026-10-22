const {chromium}=require("playwright");
const fs=require("node:fs/promises");
const path=require("node:path");
const assert=require("node:assert/strict");
(async()=>{
  const browser=await chromium.launch({headless:true,...(process.env.BROWSER_CHANNEL ? {channel:process.env.BROWSER_CHANNEL} : {})});
  const folder=path.resolve(__dirname,"../test-results");await fs.mkdir(folder,{recursive:true});
  const base=process.env.DEMO_URL || "http://127.0.0.1:8770";
  try {
    const page=await browser.newPage({viewport:{width:1440,height:1100},acceptDownloads:true});
    const errors=[];page.on("pageerror",e=>errors.push(e.message));
    async function ready(text){await page.waitForFunction(t=>!document.getElementById("create-workspace").disabled && document.getElementById("workspace-status").textContent.includes(t),text);}
    await page.goto(base);
    if(process.env.RESUME_ONLY){
      const access=JSON.parse(await fs.readFile(path.join(folder,"access.json"),"utf8"));
      await page.locator("#access-details").evaluate(el=>el.open=true);
      await page.locator("#workspace-id").fill(access.workspace_id);await page.locator("#workspace-key").fill(access.key);
      await page.locator("#open-workspace").click();await ready("odczytana");
      assert.equal(await page.locator(".history-item").count(),1);
      await page.locator(".history-item button").first().click();await ready("Odczytano zapisany wynik");
      assert.match(await page.locator("#analysis-status").innerText(),/Znaleziono przejazd/);
      console.log("Workspace process-restart PASS: credentials, datasets, saved analysis.");return;
    }
    await page.locator("#workspace-name").fill("Analiza własnych plików · przykład");
    await page.locator("#create-workspace").click();await ready("Przestrzeń gotowa");
    if(!await page.locator("#save-access").isVisible()) await page.locator("#access-details summary").click();
    const downloadEvent=page.waitForEvent("download");await page.locator("#save-access").click();
    const accessDownload=await downloadEvent;await accessDownload.saveAs(path.join(folder,"access.json"));
    const access=JSON.parse(await fs.readFile(path.join(folder,"access.json"),"utf8"));
    await page.locator("#roads-file").setInputFiles(path.resolve(__dirname,"../examples/roads.geojson"));
    await page.locator("#flood-file").setInputFiles(path.resolve(__dirname,"../examples/flood.geojson"));
    await page.locator("#data-source").fill("Syntetyczne pliki użytkownika · examples");
    await page.locator("#observed-at").fill("2026-01-01T10:00");await page.locator("#sample-data").check();
    await page.locator("#save-datasets").click();await ready("Oba zbiory zweryfikowane");
    await page.locator("#route-start").fill("52,21");await page.locator("#route-end").fill("52,21.002");
    await page.locator("#calculate-route").click();await ready("Analiza zakończona");
    assert.match(await page.locator("#own-blocked").innerText(),/1 \/ 4/);
    assert.equal(await page.locator(".history-item").count(),1);
    const resultEvent=page.waitForEvent("download");await page.locator("#download-analysis").click();
    const resultDownload=await resultEvent;
    const result=JSON.parse(await fs.readFile(await resultDownload.path(),"utf8"));
    assert.equal(result.data_mode,"sample");assert.equal(result.status,"found");assert(result.analysis_id);
    const snapshot=path.resolve(__dirname,"../docs/assets");await fs.mkdir(snapshot,{recursive:true});
    // Collapse access details so the screenshot focuses on data; no credential is visible.
    await page.locator("#access-details").evaluate(el=>el.open=false);
    await page.screenshot({path:path.join(snapshot,"application-desktop.png"),fullPage:true});
    for(const width of [390,720,1024,1440]){
      await page.setViewportSize({width,height:844});
      assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth),false,`overflow at ${width}`);
      if(width===390)await page.screenshot({path:path.join(snapshot,"application-mobile.png"),fullPage:true});
    }
    await page.reload();await page.locator("#access-details").evaluate(el=>el.open=true);
    assert.equal(await page.locator("#workspace-key").inputValue(),"");
    await page.locator("#workspace-id").fill(access.workspace_id);await page.locator("#workspace-key").fill(access.key);
    await page.locator("#open-workspace").click();await ready("odczytana");
    assert.equal(await page.locator("#observed-at").inputValue(),"2026-01-01T10:00");
    await page.locator(".history-item button").first().click();await ready("Odczytano zapisany wynik");
    assert.equal(await page.locator("#own-blocked").innerText(),"1 / 4");
    await page.locator("#route-start").fill("90,180");await page.locator("#calculate-route").click();await ready("zbyt daleko");
    await page.locator("#rotate-access").click();await ready("Klucz zmieniony");
    const refused=await page.request.get(base+"/api/workspaces/"+access.workspace_id,{headers:{Authorization:"Bearer "+access.key}});
    assert.equal(refused.status(),401);
    const rotatedEvent=page.waitForEvent("download");await page.locator("#save-access").click();
    await (await rotatedEvent).saveAs(path.join(folder,"access.json"));
    const rotated=JSON.parse(await fs.readFile(path.join(folder,"access.json"),"utf8"));
    await page.locator("#close-workspace").click();
    assert.equal(await page.locator("#workspace-key").inputValue(),"");
    assert.equal(await page.locator(".history-item").count(),0);
    assert.equal(await page.locator("#calculate-route").isDisabled(),true);
    await page.locator("#access-details").evaluate(el=>el.open=true);
    await page.locator("#workspace-id").fill(rotated.workspace_id);await page.locator("#workspace-key").fill(rotated.key);
    await page.locator("#open-workspace").click();await ready("odczytana");
    assert.equal(await page.locator(".history-item").count(),1);
    assert.deepEqual(errors,[]);
    console.log("Workspace browser PASS: creation, private key export, GeoJSON upload, calculation/persistence, history, reload/reconnect, export, invalid input and mobile/desktop.");
  }finally{await browser.close();}
})().catch(error=>{console.error(error);process.exitCode=1;});
