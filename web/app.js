const $ = q => document.querySelector(q);
const $$= q => Array.from(document.querySelectorAll(q));
const esc = s => String(s||"").replace(/[&<>"']/g, c =>
  ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));

const SLOT_COLOR = {"ADC":"#ff8a4d","AP":"#b39dff","刺客":"#ff6b8a","战士":"#f0c75e","坦克":"#48d1d1","辅助":"#36e8a8"};
let STATE = null;
let RIOT_CDN = "https://raw.communitydragon.org/latest/plugins/rcp-be-lol-game-data/global/default";
const champIcon = id => id ? `${RIOT_CDN}/v1/champion-icons/${id}.png` : "";
const profileIcon = id => id ? `${RIOT_CDN}/v1/profile-icons/${id}.jpg` : "";

function agoText(unixTs){
  if(!unixTs) return "";
  const s = Math.max(0, Math.floor(Date.now()/1000 - unixTs));
  if(s < 60)        return `${s} 秒前`;
  if(s < 3600)      return `${Math.floor(s/60)} 分钟前`;
  if(s < 86400)     return `${Math.floor(s/3600)} 小时前`;
  return `${Math.floor(s/86400)} 天前`;
}

function renderState(s){
  STATE = s;
  $("#dot").classList.toggle("on", !!s.lcu_online);
  if(!s.lcu_online){
    $("#status").innerHTML = "等待客户端...";
    $("#empty").style.display = "";
    $("#cs-view").style.display = "none";
    return;
  }
  let st = `客户端在线 · phase <b>${esc(s.phase||"None")}</b>`;
  if(s.me && s.me.name) st += ` · ${esc(s.me.name)}`;
  $("#status").innerHTML = st;

  // 决定展示哪个 champ_select: 实时优先, 否则用上一局 (复盘模式)
  let cs = s.champ_select;
  let recap = false;
  if(!cs && s.last_champ_select){
    cs = s.last_champ_select;
    recap = true;
  }

  if(!cs){
    $("#empty").style.display = "";
    $("#empty").innerHTML = `<div class="icon">⏳</div>
      <div>等待第一次选人...</div>
      <div class="hint">phase: ${esc(s.phase||"None")}</div>
      <div class="hint">客户端在线后, 进过一次选人就会持续展示</div>`;
    $("#cs-view").style.display = "none";
    document.body.classList.remove("recap-mode");
    return;
  }
  $("#empty").style.display = "none";
  $("#cs-view").style.display = "";

  // 复盘 banner
  document.body.classList.toggle("recap-mode", recap);
  const banner = $("#recap-banner");
  if(recap){
    banner.classList.add("on");
    const endedAt = cs.ended_at || 0;
    const phase   = cs.ended_phase || s.phase || "Idle";
    $("#recap-text").innerHTML = `上一局选人 · phase 已切到 <b>${esc(phase)}</b>, 等待下次选人`;
    $("#recap-ago").textContent = endedAt ? agoText(endedAt) : "";
  } else {
    banner.classList.remove("on");
  }

  // 用合并后的 cs 渲染 (实时 / 复盘 同一套布局)
  renderChampSelect({...s, champ_select: cs});
}

function renderChampSelect(s){
  const me = s.me || {};
  const cs = s.champ_select || {};
  // 我
  $("#me-icon").src = profileIcon(me.profileIconId);
  $("#me-name").textContent = (me.name||"—") + (me.tagLine?` #${me.tagLine}`:"");
  $("#me-tier").textContent = me.tier
    ? `${me.tier} ${me.division||""} · ${me.lp}LP · 总胜率 ${me.wr}% (${me.wins}-${me.losses})`
    : "未定级";
  $("#me-pick").textContent = cs.my_pick_name || "未选定";
  const cid = cs.my_pick_cid;
  const picIc = $("#me-pick-ic");
  if(cid){ $("#me-pick-img").src = champIcon(cid); picIc.classList.add("on"); }
  else { picIc.classList.remove("on"); }
  const h = cid ? (s.my_champ_history||{})[cid] : null;
  if(h && h.games){
    const wr = Math.round(h.wins/h.games*100);
    $("#me-pick-wr").textContent = `近期 ${h.wins}-${h.games-h.wins} · ${wr}%`;
  } else {
    $("#me-pick-wr").textContent = cid ? "近期无该英雄记录" : "—";
  }

  // 队友
  const mates = cs.mates||[];
  const corePuuid = (cs.architecture||{}).core?.puuid || "";
  $("#mates").innerHTML = mates.map(m => {
    const lc = m.locked ? "lock" : "";
    const meCls = m.is_me ? "me" : "";
    const coreCls = (m.puuid && m.puuid === corePuuid) ? "core" : "";
    const slotColor = SLOT_COLOR[m.slot_label] || "#8a82b0";
    const ic = m.champion_id
      ? `<img src="${champIcon(m.champion_id)}" alt="">`
      : `<span>?</span>`;
    const icCls = m.champion_id ? "ic" : "ic empty";
    const profile = m.profile||{};
    const badges = [];
    if(coreCls) badges.push(`<span class="b core">本局核心</span>`);
    if(m.is_premade) badges.push(`<span class="b pre">★ premade</span>`);
    if((profile.tags||[]).length) badges.push(`<span class="b tag">${esc(profile.tags[0])}</span>`);
    const bhtml = badges.length ? `<span class="badges">${badges.join("")}</span>` : "";

    // 右侧统计: 该英雄历史胜率 (优先) · 整体胜率
    let stat = "";
    if(m.champ_history){
      const ch = m.champ_history;
      stat = `<b>${Math.round(ch.wr*100)}%</b> <span class="muted">${ch.games}局</span>`;
    } else if(m.total_games >= 10){
      stat = `<span class="muted">总 ${Math.round(m.total_wr*100)}% (${m.total_games})</span>`;
    } else {
      stat = `<span class="muted">无数据</span>`;
    }

    const tipLines = [];
    if(profile.self_desc)   tipLines.push("摘要: " + profile.self_desc);
    if(profile.peer_review) tipLines.push("评价: " + profile.peer_review);
    if(profile.habits)      tipLines.push("习惯: " + profile.habits);
    if(profile.skill)       tipLines.push("水平: " + profile.skill);
    const persona = profile.persona || {};
    if(persona.self_voice){
      const t = persona.self_voice.length > 120 ? persona.self_voice.slice(0,120)+"…" : persona.self_voice;
      tipLines.push("");
      tipLines.push("【TA 自己说】 " + t);
    }
    if((persona.peer_voices||[]).length){
      tipLines.push("");
      tipLines.push("【别人说】");
      for(const v of persona.peer_voices.slice(-3)){
        tipLines.push("· " + v);
      }
    }
    if(typeof m.carry_score === "number") {
      tipLines.push("");
      tipLines.push("carry_score: " + m.carry_score);
    }
    if(m.total_games) tipLines.push(`总战绩: ${Math.round(m.total_wr*100)}% (${m.total_games}局)`);
    const tip = tipLines.length
      ? ` data-tip="${esc(tipLines.join("\n"))}"` : "";

    return `<div class="mate ${lc} ${meCls} ${coreCls}" data-cell-id="${m.cell_id}"${tip}>
      <span class="${icCls}">${ic}</span>
      <span class="ch">${esc(m.champion_name||"—")}</span>
      <span class="nm">${esc(m.name||"队友")} ${bhtml}</span>
      <span class="slot" style="color:${slotColor}">${esc(m.slot_label||"")}</span>
      <span class="wr">${stat}</span>
    </div>`;
  }).join("") || `<div class="muted">无队友数据</div>`;

  // 架构
  const a = cs.architecture || {};
  $("#arch-stats").innerHTML = `
    <div><b>${a.ad||0}</b><span>AD</span></div>
    <div><b>${a.ap||0}</b><span>AP</span></div>
    <div><b>${a.tank||0}</b><span>坦克</span></div>
    <div><b>${a.sup||0}</b><span>辅助</span></div>`;
  $("#arch-verdict").textContent = a.verdict || "—";

  // 核心 + 建议
  const core = a.core;
  const coreEl = $("#arch-core");
  if(core){
    const meTag = core.is_me ? ` <span class="muted">(你)</span>` : "";
    coreEl.innerHTML = `<div class="head">本局核心: <span class="nm">${esc(core.name||"?")}</span> · ${esc(core.champion_name||"?")}${meTag}
      <span class="muted">score=${core.score}</span></div>
      <div class="adv">${esc(a.advice||"")}</div>`;
    coreEl.classList.add("on");
  } else {
    coreEl.classList.remove("on");
  }
  // 警告
  const warnEl = $("#arch-warn");
  const warns = a.warnings || [];
  warnEl.innerHTML = warns.length ? warns.map(w => `<div>${esc(w)}</div>`).join("") : "";

  // 🎙️ AI 教练点评
  renderCoach(cs.coach || {});

  // 海克斯推荐
  const recs = cs.hex_recs||[];
  if(recs.length){
    $("#hex-list").innerHTML = recs.map(r => {
      const rt = r.rating || "-";
      const cls = ["SSS","SS","S","A","B","C","D"].includes(rt) ? rt : "C";
      const items = r.combo.join(" + ");
      const tag = r.tag ? ` <span class="muted">[${esc(r.tag)}]</span>` : "";
      return `<div class="hex-row">
        <span class="r ${cls}">${esc(rt)}</span>
        <div class="body">
          <div class="combo">${esc(items)}${tag}</div>
          ${r.analysis?`<div class="ana">${esc(r.analysis)}</div>`:""}
        </div></div>`;
    }).join("");
  } else {
    $("#hex-list").innerHTML = `<div class="muted">${cid?"该英雄暂无本地海克斯推荐数据 · 试试更新缓存":"等待选定英雄..."}</div>`;
  }
}

function renderCoach(coach){
  const card = $("#coach-card");
  const v = coach.pre_game || coach.say || "";
  if(!v){
    card.style.display = "none";
    return;
  }
  card.style.display = "";
  $("#coach-name").textContent = coach.name || "AI 教练";
  $("#coach-tag").textContent  = coach.voice ? `(${coach.voice})` : "";
  $("#coach-voice").textContent = v;
  // 心理辅导 (针对状态偏冷队友)
  const ps = $("#coach-psych");
  const psych_lines = coach.psych || [];
  if(psych_lines.length){
    ps.classList.add("on");
    ps.innerHTML = `<b>🧠 心态提醒</b><br>` +
      psych_lines.map(l => esc(l)).join("<br>");
  } else {
    ps.classList.remove("on");
    ps.innerHTML = "";
  }
  // 反馈按钮 (训练数据闭环: 👍 / 👎 / 改写)
  const fb = $("#coach-feedback");
  if(fb){
    fb.dataset.ref = coach.ref || "";
    fb.classList.remove("sent");
    const status = $("#coach-fb-status");
    if(status) status.textContent = "";
  }
}

async function sendCoachFeedback(rating, rewrite=""){
  const fb = $("#coach-feedback");
  const ref = fb ? (fb.dataset.ref || "") : "";
  const status = $("#coach-fb-status");
  const contribute = !!($("#coach-fb-contrib") && $("#coach-fb-contrib").checked);
  try{
    const r = await fetch("/api/coach/feedback", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({ref, rating, rewrite, contribute}),
    });
    const j = await r.json();
    if(j.ok){
      if(fb) fb.classList.add("sent");
      const tail = j.contributed ? " (+ 贡献 ✓)" : "";
      if(status) status.textContent = (rating === "edit" ? "已记录你的改写 ✓" : "已记录 ✓") + tail;
      if(j.contributed) refreshContribStats();
    } else {
      if(status) status.textContent = "失败: " + (j.err || "?");
    }
  } catch(e){
    if(status) status.textContent = "失败: " + e.message;
  }
}

function bindCoachFeedback(){
  const btnUp   = $("#coach-fb-up");
  const btnDown = $("#coach-fb-down");
  const btnEdit = $("#coach-fb-edit");
  if(btnUp)   btnUp.addEventListener("click", () => sendCoachFeedback("good"));
  if(btnDown) btnDown.addEventListener("click", () => sendCoachFeedback("bad"));
  if(btnEdit) btnEdit.addEventListener("click", () => {
    const cur = $("#coach-voice").textContent || "";
    const v = prompt("教练这句话你会怎么说? (留空取消)", cur);
    if(v && v.trim() && v.trim() !== cur) sendCoachFeedback("edit", v.trim());
  });
}

/* ============ 训练贡献 (opt-in) ============ */
async function refreshContribStats(){
  try{
    const j = await fetch("/api/contribute/stats").then(r=>r.json());
    const n = j.pending || 0;
    const nEl = $("#contrib-tab-n"); if(nEl) nEl.textContent = n;
    const cnt = $("#contrib-count"); if(cnt) cnt.textContent = n;
    const an  = $("#contrib-anon");  if(an)  an.textContent = j.anon_id || "—";
    const cs  = $("#contrib-consent");
    if(cs){
      const act = (j.consent && j.consent.action) || "";
      cs.textContent = act === "grant" ? "已同意 ✓"
                     : act === "revoke" ? "已撤回 ✗"
                     : "未声明";
    }
    const tgt = $("#contrib-target");
    if(tgt && j.upload){
      tgt.innerHTML = `<div class="mono">${esc(j.upload.url || "")}</div>` +
                      `<div class="muted">${esc(j.upload.hint || "")}</div>`;
    }
  }catch(_){ /* server may be reloading */ }
}

async function postContribConsent(action){
  try{
    const r = await fetch("/api/contribute/consent", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({action}),
    });
    const j = await r.json();
    if(!j.ok) alert("失败: " + (j.err || "?"));
    refreshContribStats();
  }catch(e){ alert("失败: " + e.message); }
}

async function clearContrib(){
  if(!confirm("清空所有待贡献样本? 不可恢复 (除非你已导出过).")) return;
  try{
    const j = await fetch("/api/contribute/clear", {method:"POST"}).then(r=>r.json());
    if(j.ok) pushLog(`[contrib] 清空 ${j.cleared} 条`);
    refreshContribStats();
  }catch(e){ alert("失败: " + e.message); }
}

function exportContrib(){
  // 直接当下载用 — 浏览器会根据 Content-Disposition 保存
  window.location.href = "/api/contribute/export";
}

async function openUploadTarget(){
  try{
    const j = await fetch("/api/contribute/stats").then(r=>r.json());
    const url = (j.upload && j.upload.url) || "";
    if(!url){ alert("尚未配置上传地址. 编辑 data/contributed/upload_target.json 即可."); return; }
    window.open(url, "_blank");
  }catch(e){ alert("失败: " + e.message); }
}

function bindContribPanel(){
  const tab = $("#contrib-tab");
  const pnl = $("#contrib-panel");
  const cls = $("#contrib-close");
  if(tab) tab.addEventListener("click", () => {
    pnl.classList.toggle("on");
    if(pnl.classList.contains("on")) refreshContribStats();
  });
  if(cls) cls.addEventListener("click", () => pnl.classList.remove("on"));
  const ex = $("#contrib-export"); if(ex) ex.addEventListener("click", exportContrib);
  const up = $("#contrib-upload"); if(up) up.addEventListener("click", openUploadTarget);
  const rv = $("#contrib-revoke"); if(rv) rv.addEventListener("click", () => {
    if(confirm("撤回同意后, 即使勾选'贡献到训练集'也不会再写副本. 现有样本不会被删除 (用'清空' 按钮删).")) postContribConsent("revoke");
  });
  const cl = $("#contrib-clear"); if(cl) cl.addEventListener("click", clearContrib);
  refreshContribStats();
}

/* SSE */
function connectStream(){
  const es = new EventSource("/stream");
  es.addEventListener("state", e => {
    try{ renderState(JSON.parse(e.data)); }catch(_){}
  });
  es.addEventListener("log", e => {
    try{
      const o = JSON.parse(e.data);
      pushLog(o.l);
    }catch(_){}
  });
  es.addEventListener("refreshed", e => {
    $("#btn-refresh").classList.remove("spin");
    $("#btn-refresh-txt").textContent = "更新数据";
    fetch("/api/state").then(r=>r.json()).then(renderState);
    try{ const o=JSON.parse(e.data); pushLog(`[refresh] ok=${o.ok}`); }catch(_){}
  });
  es.onerror = () => { setTimeout(connectStream, 3000); es.close(); };
}

/* 调试抽屉 */
function pushLog(line){
  const dbg = $("#debug");
  const cls = /\[!\]|err|fail|失败|异常/i.test(line) ? "err"
            : /warn|⚠|警/i.test(line) ? "warn"
            : /\[\+\]|✓|ok|成功/i.test(line) ? "ok" : "";
  const div = document.createElement("div");
  div.className = "l " + cls;
  div.textContent = line;
  dbg.appendChild(div);
  while(dbg.childNodes.length > 400) dbg.removeChild(dbg.firstChild);
  if(dbg.classList.contains("on")) dbg.scrollTop = dbg.scrollHeight;
}
$("#debug-tab").onclick = () => {
  const d = $("#debug");
  d.classList.toggle("on");
  $("#debug-tab").textContent = d.classList.contains("on") ? "调试 ▼" : "调试 ▲";
  if(d.classList.contains("on")) d.scrollTop = d.scrollHeight;
};

/* 刷新 */
$("#btn-refresh").onclick = async () => {
  if($("#btn-refresh").classList.contains("spin")) return;
  $("#btn-refresh").classList.add("spin");
  $("#btn-refresh-txt").textContent = "更新中...";
  try{
    await fetch("/api/refresh", {method:"POST"});
    pushLog("[refresh] 已触发, 后台进行中...");
  }catch(e){
    pushLog("[refresh] 触发失败: " + e);
    $("#btn-refresh").classList.remove("spin");
    $("#btn-refresh-txt").textContent = "更新数据";
  }
};

/* 搜索 */
let searchTimer = 0;
$("#q").addEventListener("input", e => {
  clearTimeout(searchTimer);
  const q = e.target.value.trim();
  if(!q){ $("#sr").classList.remove("on"); $("#sr").innerHTML=""; return; }
  searchTimer = setTimeout(() => doSearch(q), 200);
});
document.addEventListener("click", e => {
  if(e.target.id === "q" || e.target.closest("#sr")) return;
  $("#sr").classList.remove("on");
});

async function doSearch(q){
  try{
    const r = await fetch("/api/search?q=" + encodeURIComponent(q));
    const data = await r.json();
    const sr = $("#sr");
    sr.innerHTML = "";
    if(!data.champions.length && !data.hex.length){
      sr.innerHTML = `<div class="muted" style="padding:10px">无结果</div>`;
    } else {
      for(const c of data.champions){
        const div = document.createElement("div");
        div.className = "search-item";
        div.innerHTML = `<div class="si-ic"><img src="${champIcon(c.cid)}" alt=""></div>
          <div class="si-body">
            <div class="t">${esc(c.name)} <span class="muted">${esc(c.alias)} · ${esc(c.role)}</span></div>
            <div class="s">点击查看海克斯推荐 (${c.rec_count} 条)</div>
          </div>`;
        div.onclick = () => showChampRecs(c.cid, c.name);
        sr.appendChild(div);
      }
      for(const h of data.hex){
        const div = document.createElement("div");
        div.className = "search-item";
        div.innerHTML = `<div class="si-ic"></div>
          <div class="si-body">
            <div class="t">【${esc(h.tier||"")}】${esc(h.name)}</div>
            <div class="s">${esc(h.desc)}</div>
          </div>`;
        sr.appendChild(div);
      }
    }
    sr.classList.add("on");
  }catch(e){ pushLog("[search] " + e); }
}

async function showChampRecs(cid, name){
  const r = await fetch("/api/hex/champion?cid=" + cid);
  const data = await r.json();
  const sr = $("#sr");
  sr.innerHTML = `<div style="padding:8px 10px"><b style="color:var(--phi)">${esc(name)} 海克斯推荐</b>
    <span class="muted">(点击其它处关闭)</span></div>`;
  for(const rec of data.recs){
    const cls = ["SSS","SS","S","A","B","C","D"].includes(rec.rating) ? rec.rating : "C";
    const div = document.createElement("div");
    div.className = "search-item";
    div.innerHTML = `<div class="t"><span class="r ${cls}" style="margin-right:6px;font-size:11px;padding:1px 6px;border-radius:3px;border:1px solid currentColor">${esc(rec.rating||"-")}</span>${esc(rec.combo.join(" + "))} ${rec.tag?`<span class="muted">[${esc(rec.tag)}]</span>`:""}</div>
      <div class="s">${esc(rec.analysis||"")}</div>`;
    sr.appendChild(div);
  }
  if(!data.recs.length){
    sr.innerHTML += `<div class="muted" style="padding:10px">本地无该英雄推荐数据 · 试试更新缓存</div>`;
  }
}

/* ===== 编辑画像模态框 ===== */
let _modal_puuid = "";
let _modal_mate  = null;

function openMateModal(mate){
  if(!mate || !mate.puuid){ return; }
  _modal_puuid = mate.puuid;
  _modal_mate  = mate;
  $("#modal-title").textContent = `${mate.name || '?'}  ·  ${mate.champion_name || '?'}`;
  $("#modal-sub").textContent   = `puuid: ${mate.puuid.slice(0,12)}…  ·  写入 data/profiles.json[persona]`;

  // 渲染当前 persona
  const p = (mate.profile||{}).persona || {};
  const cur = $("#modal-current");
  let html = "";
  if(p.self_voice){
    html += `<div class="voice"><b style="color:var(--gold)">TA 自己说:</b><br>${esc(p.self_voice)}</div>`;
  }
  if((p.peer_voices||[]).length){
    html += `<div><b style="color:var(--teal)">别人说:</b></div>`;
    for(const v of p.peer_voices){
      html += `<div class="peer">${esc(v)}</div>`;
    }
  }
  cur.innerHTML = html || `<div class="empty">暂无 persona, 添加第一条吧</div>`;

  // 清空输入
  $("#modal-text").value = "";
  $$('input[name="kind"]').forEach(r => r.checked = (r.value === "peer"));

  $("#modal-bg").classList.add("on");
  setTimeout(() => $("#modal-text").focus(), 50);
}

function closeMateModal(){
  $("#modal-bg").classList.remove("on");
  _modal_puuid = "";
  _modal_mate  = null;
}

async function saveMatePersona(){
  if(!_modal_puuid) return;
  const text = $("#modal-text").value.trim();
  if(!text){ closeMateModal(); return; }
  const kind = $$('input[name="kind"]').find(r => r.checked)?.value || "peer";
  const btn = $("#modal-save");
  btn.disabled = true; btn.textContent = "保存中...";
  try{
    const resp = await fetch("/api/profile/persona", {
      method: "POST",
      headers: {"Content-Type":"application/json"},
      body: JSON.stringify({puuid: _modal_puuid, kind, text}),
    });
    if(!resp.ok){
      const e = await resp.json().catch(()=>({err:"未知"}));
      alert("保存失败: " + (e.err || resp.status));
    } else {
      closeMateModal();
    }
  }catch(e){
    alert("网络错误: " + e);
  }finally{
    btn.disabled = false; btn.textContent = "保存";
  }
}

$("#modal-cancel").onclick = closeMateModal;
$("#modal-save").onclick   = saveMatePersona;
$("#modal-bg").addEventListener("click", e => {
  if(e.target.id === "modal-bg") closeMateModal();
});
document.addEventListener("keydown", e => {
  if(!$("#modal-bg").classList.contains("on")) return;
  if(e.key === "Escape") closeMateModal();
  if((e.metaKey || e.ctrlKey) && e.key === "Enter") saveMatePersona();
});

// 点击 mate 卡片打开模态框 (事件委托, 适配 SSE 重渲染)
$("#mates").addEventListener("click", e => {
  const card = e.target.closest(".mate");
  if(!card) return;
  const cs = (STATE || {}).champ_select || {};
  const mates = cs.mates || [];
  const cellId = card.dataset.cellId;
  const mate = mates.find(m => String(m.cell_id) === String(cellId));
  if(mate) openMateModal(mate);
});

/* 初始化 */
bindCoachFeedback();
bindContribPanel();
// 首次勾选"贡献"时自动写一条 grant consent (PIPL 取证用)
document.addEventListener("change", e => {
  if(e.target && e.target.id === "coach-fb-contrib" && e.target.checked){
    fetch("/api/contribute/stats").then(r=>r.json()).then(j => {
      const act = j.consent && j.consent.action;
      if(act !== "grant") postContribConsent("grant");
    }).catch(()=>{});
  }
});
fetch("/api/state").then(r=>r.json()).then(renderState).catch(()=>{});
connectStream();
