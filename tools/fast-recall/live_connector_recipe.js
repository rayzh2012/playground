/** FAST RECALL v3: run this inside ChatGPT functions.exec Code Mode.
 * Set QUERY / TERMS. Connected Notion tools are supplied by the host.
 * Nothing is written to Notion; full fetch stays inside tool orchestration.
 */
const QUERY = "replace with current entity / topic";
const TERMS = QUERY.split(/\s+/).filter(Boolean);
const BUDGET_CHARS = 2200;
const start = Date.now();
const read = r => r?.structuredContent || r;
const search = await tools.mcp__Notion__search({query:QUERY,page_size:5,max_highlight_length:100});
const results = read(search).results || [];
const rank = row => {
  const title = String(row.title || "").toLowerCase();
  let score = TERMS.reduce((n,t)=>n+(title.includes(t.toLowerCase())?3:0),0);
  if (/当前|主单|传承册|current|index/i.test(title)) score += 4;
  if (/每日成果|日志|总账|log/i.test(title)) score -= 6;
  return score;
};
const target = [...results].sort((a,b)=>rank(b)-rank(a))[0];
if (!target) {
  text(JSON.stringify({mode:"LIVE_NOTION",query:QUERY,status:"NO_MATCH",next:"alias / narrower scoped search"}));
} else {
  const fetched = await tools.mcp__Notion__fetch({id:target.id});
  const full = String(read(fetched).text || "");
  const lines = full.split("\n");
  const scored = [];
  for (let i=0;i<lines.length;i++) {
    const s=lines[i].trim();
    if (s.length < 20) continue;
    let score=TERMS.reduce((n,t)=>n+(s.toLowerCase().includes(t.toLowerCase())?2:0),0);
    if (/LOCK|FACT|CANON|INFERENCE|REJECTED|OPEN|CONTRADICTION|CURRENT/i.test(s)) score+=2;
    if (score) scored.push({line:i,score,text:s.slice(0,350)});
  }
  scored.sort((a,b)=>b.score-a.score || a.line-b.line);
  let size=0;
  const excerpts=[];
  for (const item of scored) {
    if (excerpts.length >= 7 || size + item.text.length > BUDGET_CHARS) break;
    excerpts.push(item); size += item.text.length;
  }
  excerpts.sort((a,b)=>a.line-b.line);
  text(JSON.stringify({mode:"LIVE_NOTION",query:QUERY,source:{title:target.title,
    page_id:target.id,url:target.url},raw_fetch_chars:full.length,
    emitted_excerpt_chars:size,elapsed_ms:Date.now()-start,excerpts,
    warning:"Model-facing context is compressed, but backend still fetched this entire page; verify exact sources before promoting a claim."}));
}