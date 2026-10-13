/* ============================================================
   易普方舟 · 交互式原型行为脚本
   视图切换 / 面包屑 / Tab / 评分 / AI 演示 / 登录 / Toast
   ============================================================ */

/* 视图 -> 面包屑（中文名, 英文标） */
const names = {
  dash:      ['工作台驾驶舱', 'DASHBOARD'],
  bigscreen: ['经费监督大屏', 'SUPERVISION SCREEN'],
  guide:     ['申报指南',     'GUIDELINES'],
  editor:    ['申报书撰写',   'APPLICATION EDITOR'],
  review:    ['评审工作台',   'PEER REVIEW'],
  projects:  ['我的项目',     'MY PROJECTS'],
  project:   ['项目详情',     'PROJECT DETAIL'],
  expense:   ['报销填单',     'EXPENSE FORM'],
  claim:     ['成果认领',     'OUTPUT CLAIM'],
  transfer:  ['转化看板',     'TECH TRANSFER'],
  procurement:['采购与合同',   'PROCUREMENT & CONTRACT'],
  asset:     ['资产与耗材台账', 'ASSET & CONSUMABLE'],
  portrait:  ['PI 画像',      'RESEARCHER PORTRAIT']
};

/* 视图切换 */
function go(v) {
  document.querySelectorAll('.view').forEach(x => x.classList.remove('on'));
  const el = document.getElementById('v-' + v);
  if (el) el.classList.add('on');
  document.querySelectorAll('.nav-item').forEach(x =>
    x.classList.toggle('active', x.dataset.v === v));
  if (names[v]) {
    const zh = document.getElementById('crumbZh');
    const en = document.getElementById('crumbEn');
    if (zh) zh.textContent = names[v][0];
    if (en) en.textContent = names[v][1];
  }
  const c = document.querySelector('.content');
  if (c) c.scrollTop = 0;
}

/* 侧边导航点击（排除含百分号的装饰性 data-v） */
document.querySelectorAll('.nav-item[data-v]').forEach(n => {
  if (/^[a-z]+$/.test(n.dataset.v)) {
    n.addEventListener('click', () => go(n.dataset.v));
  }
});

/* 通用页面内跳转：data-go="视图名" */
document.querySelectorAll('[data-go]').forEach(el =>
  el.addEventListener('click', () => go(el.dataset.go)));

/* ---------- Toast ---------- */
let tt;
function toast(m) {
  const t = document.getElementById('toast');
  if (!t) return;
  t.textContent = m;
  t.classList.add('on');
  clearTimeout(tt);
  tt = setTimeout(() => t.classList.remove('on'), 2600);
}

/* ---------- 项目详情 Tab（甘特/任务/经费…）---------- */
document.querySelectorAll('.tabs .tab').forEach(t => {
  t.addEventListener('click', () => {
    document.querySelectorAll('.tabs .tab').forEach(x => x.classList.remove('on'));
    t.classList.add('on');
    const p = t.dataset.t;
    document.querySelectorAll('.pane').forEach(x => x.style.display = 'none');
    const el = document.querySelector('.pane.' + p);
    if (el) { el.style.display = 'block'; el.style.animation = 'fadeUp .3s both'; }
  });
});
function tabTo(p) {
  const tab = document.querySelector('.tab[data-t="' + p + '"]');
  if (tab) tab.click();
}

/* ---------- 评审评分：4 个维度，每维 1-5 分 ---------- */
['d1', 'd2', 'd3', 'd4'].forEach(id => {
  const box = document.getElementById(id);
  if (!box || box.querySelector('.sdot')) return;      // 避免重复生成
  for (let i = 1; i <= 5; i++) {
    const d = document.createElement('div');
    d.className = 'sdot';
    d.textContent = i;
    d.addEventListener('click', () => {
      box.querySelectorAll('.sdot').forEach(x => x.classList.remove('on'));
      d.classList.add('on');
      const sum = [...document.querySelectorAll('.score-dots')].map(b => {
        const on = b.querySelector('.on');
        return on ? +on.textContent : 0;
      });
      const total = sum.reduce((a, b) => a + b, 0);
      const tEl = document.getElementById('totalScore');
      if (tEl) tEl.textContent = total ? total + '/20' : '—';
    });
    box.appendChild(d);
  }
});

/* ---------- AI 起草评审意见（演示：依据评分要点生成）---------- */
function genComment() {
  const b = document.getElementById('commentBox');
  if (b) {
    b.value =
'本项目针对多轴机床颤振主动抑制问题，提出"生成先验 + 在线微调"双阶段框架，选题紧扣制造领域前沿，立项依据充分。\n\n' +
'创新性：将扩散模型引入稳定性叶片概率建模，思路新颖；\n' +
'研究方案：技术路线可行，但半物理仿真工况覆盖不足，建议补充变参数验证矩阵；\n' +
'研究基础：申请人前期成果扎实，团队结构合理。\n\n' +
'综合意见：优先资助。（本稿由 AI 依据评分要点起草，请评审人核校后提交）';
    b.style.animation = 'none'; void b.offsetWidth; b.style.animation = 'fadeUp .3s both';
  }
  toast('AI 已根据评分与评阅要点起草意见，请人工核校');
}

/* ---------- AI 申报撰写助手（演示）---------- */
function aiDraft() {
  const r = document.getElementById('draftResp');
  if (r) {
    r.style.display = 'block';
    r.style.animation = 'none'; void r.offsetWidth; r.style.animation = 'fadeUp .35s both';
  }
  toast('§3 三条主线建议已生成（来源已标注）');
}

/* ---------- 目录 / 章节高亮（申报书编辑器）---------- */
document.querySelectorAll('.toc-item').forEach(t =>
  t.addEventListener('click', () => {
    document.querySelectorAll('.toc-item').forEach(x => x.classList.remove('on'));
    t.classList.add('on');
  }));

/* ---------- 可多选标签 chip 切换 ---------- */
document.querySelectorAll('.chip').forEach(c =>
  c.addEventListener('click', () => c.classList.toggle('on')));

/* ---------- 登录浮层 ---------- */
function hideLogin() {
  const l = document.getElementById('loginScreen');
  if (l) l.classList.remove('on');
}

/* 进入页面：默认显示登录浮层，停在驾驶舱 */
(function init() {
  const l = document.getElementById('loginScreen');
  if (l) l.classList.add('on');
  go('dash');
})();
