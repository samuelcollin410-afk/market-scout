"use strict";
const $ = (id) => document.getElementById(id);
const state = {data: null};
const esc = (v) => String(v ?? "").replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const pct = v => Number.isFinite(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(2)}%` : "—";
const pp = v => Number.isFinite(v) ? `${v >= 0 ? "+" : ""}${v.toFixed(2)} pp` : "—";
const money = v => Number.isFinite(v) ? v.toLocaleString("en-US", {style:"currency",currency:"USD",maximumFractionDigits:2}) : "—";
const tone = v => Number.isFinite(v) ? (v >= 0 ? "positive" : "negative") : "muted";
const time = v => v && Number.isFinite(Date.parse(v)) ? new Date(v).toLocaleString() : "Not available";
function safeURL(v) {try {const u = new URL(v); return u.protocol === "https:" ? u.href : "";} catch {return "";}}
function toast(message) {$("toast").textContent=message; $("toast").hidden=false; clearTimeout(toast.timer); toast.timer=setTimeout(()=>$("toast").hidden=true,5000);}
function navigate() {const requested=location.hash.slice(1); const view=["overview","sources","journal","setup"].includes(requested)?requested:"overview"; document.querySelectorAll(".view").forEach(e=>e.hidden=e.id!==view);document.querySelectorAll("nav a").forEach(e=>{e.classList.toggle("active",e.dataset.view===view);if(e.dataset.view===view)e.setAttribute("aria-current","page");else e.removeAttribute("aria-current");});}
async function load() {
 $("refresh").disabled=true;
 try {const response=await fetch("./data/latest.json",{cache:"no-store"});if(!response.ok)throw new Error("fetch");const data=await response.json();if(data.schema_version!==1 || !Array.isArray(data.stocks))throw new Error("schema");state.data=data; render();}
 catch {$("notice").classList.remove("good");$("notice").textContent="Could not refresh the scan. Any results still visible are from the previous load. Try again; for local previews, follow the README’s local server instructions.";}
 finally {$("refresh").disabled=false;}
}
function render() {
 const d=state.data; const age=d.generated_at?Date.now()-Date.parse(d.generated_at):Infinity;
 const stale=age>4*86400000; const good=d.status==="ok"&&!stale;
 $("notice").classList.toggle("good",good);
 $("notice").textContent=stale&&d.generated_at?"This scan is over four days old. Check the GitHub workflow before relying on these results.":d.message;
 $("scan-time").textContent=d.generated_at?`Last scan: ${time(d.generated_at)} · Completed daily bars only` : "Waiting for the first connected scan.";
 $("watch-count").textContent=d.stocks.length;
 $("candidate-count").textContent=d.market_status==="ok"?d.stocks.filter(s=>s.status==="Research").length:"—";
 $("benchmark-return").textContent=pct(d.benchmark?.return_63d);
 $("benchmark-return").className=tone(d.benchmark?.return_63d);
 $("mention-count").textContent=d.sources?.length?d.mentions.length:"—";
 renderStocks(); renderSources();
}
function renderStocks() {
 if(!state.data)return;const q=$("search").value.toLowerCase(),filter=$("filter").value;
 const rows=state.data.stocks.filter(s=>(s.symbol+" "+s.name).toLowerCase().includes(q)&&(filter==="all"||s.status===filter));
 $("stocks").innerHTML=rows.map(s=>`<tr><td><div class="company"><span class="ticker-icon">${esc(s.symbol[0])}</span><span><b>${esc(s.symbol)}</b><small>${esc(s.name)}</small></span></div></td><td>${money(s.close)}</td><td class="${tone(s.return_20d)}">${pct(s.return_20d)}</td><td class="${tone(s.excess_63d)}">${pp(s.excess_63d)}</td><td><span class="badge ${s.status==="Research"?"research":""}">${esc(s.status)}</span></td><td><button class="button subtle" data-symbol="${esc(s.symbol)}" aria-label="View ${esc(s.symbol)} evidence">↗</button></td></tr>`).join("")||'<tr><td colspan="6" class="empty">No stocks match this filter.</td></tr>';
}
function detail(symbol) {
 const s=state.data.stocks.find(s=>s.symbol===symbol);if(!s)return;
 $("detail-title").textContent=`${s.symbol} · ${s.name}`;
 $("detail-body").innerHTML=`<span class="badge ${s.status==="Research"?"research":""}">${esc(s.status)}</span><p>${esc(s.reason)}</p><div class="detail-grid"><div><span class="label">ADJUSTED CLOSE</span><strong>${money(s.close)}</strong></div><div><span class="label">BAR DATE</span><strong>${esc(s.as_of||"Awaiting data")}</strong></div><div><span class="label">20-SESSION RETURN</span><strong class="${tone(s.return_20d)}">${pct(s.return_20d)}</strong></div><div><span class="label">63-SESSION LEAD VS SPY</span><strong class="${tone(s.excess_63d)}">${pp(s.excess_63d)}</strong></div></div><p class="muted">${esc(s.window_start?`Comparison window: ${s.window_start} to ${s.as_of}. `:"")}Source: Alpaca IEX daily bars, adjusted for corporate actions. Adjusted close is a research value, not an executable quote.</p><h3>Before any paper decision</h3><ul><li>Check current news, earnings timing, and company filings.</li><li>Record why this might fail and when you will reassess.</li><li>Use a separately observed price in your journal.</li></ul><p class="muted">This screen has no proven predictive edge and does not issue buy or sell orders.</p><a class="text-link" href="https://www.sec.gov/edgar/search/#/q=${encodeURIComponent(s.symbol)}" target="_blank" rel="noopener noreferrer">Search SEC filings ↗</a>`;
 $("detail").showModal();
}
function renderSources() {
 const d=state.data;
 $("source-status").innerHTML=d.sources.length?`<h2>Your connected feeds</h2>${d.sources.map(s=>`<p><b>${esc(s.name)}</b> <span class="badge">${esc(s.status)}</span></p><p class="muted">${esc(s.message||"")}</p>`).join("")}`:'<h2>No trader sources selected yet</h2><p class="muted">Add authorized RSS or Atom feeds to config/sources.json. The scanner looks for explicit cashtags such as $NVDA and keeps the original source link. Website scraping and AI interpretation are not connected.</p><a href="#setup" class="text-link">View setup ↗</a>';
 $("mentions").innerHTML=d.mentions.map(m=>`<article class="panel"><span class="label">${esc(m.source)} · MENTION ONLY</span><h3>${esc(m.title)}</h3><p>${m.symbols.map(s=>`<span class="badge">${esc(s)}</span>`).join(" ")}</p><p class="muted">Published: ${time(m.published_at)}<br>First collected: ${time(m.first_seen_at)}</p>${safeURL(m.url)?`<a class="text-link" href="${esc(safeURL(m.url))}" target="_blank" rel="noopener noreferrer">Read original ↗</a>`:""}</article>`).join("")||'<div class="empty">No recent matching cashtags collected.<br>Empty results are not a signal to buy or sell.</div>';
}
const journalKey="market-scout-journal-v1";
function readJournal() {const raw=localStorage.getItem(journalKey);if(!raw)return [];const data=JSON.parse(raw);if(!Array.isArray(data)||!data.every(validEntry))throw new Error("Invalid journal");return data;}
function validEntry(e) {return e&&typeof e.id==="string"&&e.id.length<100&&/^[A-Z][A-Z0-9.\-]{0,9}$/.test(e.symbol)&&["Research","Skip","Paper buy","Paper sell","Hold"].includes(e.action)&&Number.isFinite(e.price)&&e.price>0&&typeof e.reason==="string"&&e.reason.length<=3000&&typeof e.horizon==="string"&&e.horizon.length<=100&&Number.isFinite(Date.parse(e.recorded_at));}
function renderJournal() {try {const entries=readJournal();$("journal-list").innerHTML=entries.slice().reverse().map(e=>`<article class="journal-entry"><h3>${esc(e.symbol)} <span class="badge">${esc(e.action)}</span> · ${money(e.price)}</h3><small>${time(e.recorded_at)} · Holding period: ${esc(e.horizon)}</small><p>${esc(e.reason)}</p></article>`).join("")||'<div class="empty">Your first decision belongs here.<br>Write down the reasoning before you see the outcome.</div>';}catch{$("journal-list").textContent="Your browser journal could not be read. Existing data has not been overwritten. Check browser storage access.";}}
$("journal-form").addEventListener("submit",e=>{e.preventDefault();const f=new FormData(e.target);const entry={id:crypto.randomUUID(),symbol:f.get("symbol").trim().toUpperCase(),action:f.get("action"),price:Number(f.get("price")),horizon:f.get("horizon").trim(),reason:f.get("reason").trim(),recorded_at:new Date().toISOString()};if(!validEntry(entry)||!entry.reason||!entry.horizon)return toast("Please complete every field with a valid value.");try{const entries=readJournal();entries.push(entry);localStorage.setItem(journalKey,JSON.stringify(entries));e.target.reset();renderJournal();toast("Paper decision saved on this browser.");}catch{toast("Could not save. Browser storage may be unavailable or full.");}});
$("export").addEventListener("click",()=>{try{const data={schema_version:1,exported_at:new Date().toISOString(),entries:readJournal()};const url=URL.createObjectURL(new Blob([JSON.stringify(data,null,2)],{type:"application/json"}));const a=document.createElement("a");a.href=url;a.download="market-scout-journal.json";a.click();setTimeout(()=>URL.revokeObjectURL(url),1000);}catch{toast("Could not export the journal. Existing data has not been changed.");}});
$("import").addEventListener("change",async e=>{const file=e.target.files[0];if(!file)return;try{if(file.size>5_000_000)throw new Error();const incoming=JSON.parse(await file.text());if(incoming.schema_version!==1||!Array.isArray(incoming.entries)||!incoming.entries.every(validEntry))throw new Error();const entries=readJournal(),ids=new Set(entries.map(x=>x.id));for(const entry of incoming.entries){if(!ids.has(entry.id)){entries.push(entry);ids.add(entry.id);}}localStorage.setItem(journalKey,JSON.stringify(entries));renderJournal();toast("Backup merged. Existing decisions were preserved.");}catch{toast("Could not import this backup. Use a valid Market Scout journal export.");}e.target.value="";});
$("stocks").addEventListener("click",e=>{const b=e.target.closest("[data-symbol]");if(b)detail(b.dataset.symbol);});
$("close-detail").addEventListener("click",()=>$("detail").close());
$("search").addEventListener("input",renderStocks);$("filter").addEventListener("change",renderStocks);$("refresh").addEventListener("click",load);window.addEventListener("hashchange",navigate);navigate();renderJournal();load();
