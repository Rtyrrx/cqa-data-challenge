'use strict';
const $ = id => document.getElementById(id);
const state = {conversation: null, view: null, checklists: [], appeals: [], appeal: null, selection: 0};
let pollTimer = null;

function el(tag, text, props = {}) {
  const node = document.createElement(tag);
  if (text !== null && text !== undefined) node.textContent = ui(text);
  Object.assign(node, props);
  return node;
}
function message(text, error = false) {
  $('notice').textContent = ui(text);
  $('notice').className = error ? 'error' : '';
  clearTimeout(state.noticeTimer);
  if (!error) state.noticeTimer=setTimeout(()=>{$('notice').textContent='';},8000);
}
async function api(path, body) {
  const response = await fetch(path, body === undefined ? {} : {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const data = await response.json();
  if (!response.ok) {
    let detail = data.detail || 'Request failed';
    if (Array.isArray(detail)) detail = detail.map(e => `${e.loc.join('.')}: ${e.msg}`).join('\n');
    throw new Error(typeof detail === 'string' ? detail : JSON.stringify(detail));
  }
  return data;
}
function run(fn) { return async event => { if (event) event.preventDefault(); try { await fn(event); } catch (error) { message(error.message, true); } finally { if(typeof refreshInterface==='function') refreshInterface(); } }; }
function option(select, label, value) { select.append(el('option', label, {value})); }
function valueLabel(value) { return value === null ? 'N/A' : value === true ? ui('Да') : value === false ? ui('Нет') : String(value); }

async function health() {
  const data = await api('/api/health');
  $('health').textContent = `Backend: ${data.status}. Model: ${data.model} (${data.provider}). Imported: ${data.datasets.map(d => `${d.id.toUpperCase()} ${d.conversation_ids.length}`).join(', ') || 'none'}.`;
  const count=data.datasets.reduce((n,d)=>n+d.conversation_ids.length,0);
  $('home-dataset-count').textContent=`${count} диалогов`;
  return data;
}
async function loadChecklists(selected = $('checklist-select').value || 'official-v1') {
  state.checklists = await api('/api/checklists');
  $('checklist-select').replaceChildren();
  for (const c of state.checklists) option($('checklist-select'), `${c.name} (${c.id})`, c.id);
  $('checklist-select').value = selected;
  renderEditor();
  if(typeof refreshEditorVersions==='function')refreshEditorVersions();
}
function clearEvaluation() {
  state.view = null;
  $('criteria-count').textContent = '';
  updateScore(null);
  $('evaluation-list').replaceChildren(el('option', 'Нет сохранённой оценки', {value: ''}));
  $('results').replaceChildren();
  $('appeal-criterion').replaceChildren();
  $('evaluation-summary').textContent = '';
  $('review-warning').textContent = '';
  $('contact-check-info').textContent = '';
  $('decision-history').textContent = 'Решений по апелляциям пока нет.';
  $('submit-appeal').disabled = true;
}
async function loadConversations() {
  const selected = state.conversation?.conversation_id || new URLSearchParams(location.search).get('conversation');
  state.selection++;
  state.conversation = null;
  clearEvaluation();
  $('transcript').replaceChildren(); $('audio').replaceChildren();
  $('conversation-info').textContent = ''; $('evaluate').disabled = true;
  $('conversation-list').replaceChildren();
  state.conversations=[];renderConversationCards();
  $('conversation-title').textContent='Выберите диалог';$('conversation-meta').textContent='—';
  const query = new URLSearchParams({dataset: $('dataset').value});
  query.set('checklist_id',$('checklist-select').value||'official-v1');
  if ($('language').value) query.set('language', $('language').value);
  if ($('channel').value) query.set('channel', $('channel').value);
  let rows;
  $('conversation-count').textContent=ui('Загрузка диалогов…');
  try { rows = await api('/api/conversations?' + query); }
  catch (error) {
    if (error.message.includes('dataset not found')) { $('conversation-count').textContent = 'Набор пока не загружен.'; return; }
    throw error;
  }
  state.conversations = rows; state.libraryPage=0; renderConversationCards();
  for (const c of rows) option($('conversation-list'), `${c.conversation_id} | ${c.language} | ${c.channel} | ${c.turn_count} turns`, c.conversation_id);
  $('conversation-count').textContent = `${rows.length} диалогов`;
  if (rows.length) {
    $('conversation-list').value = rows.some(c => c.conversation_id === selected) ? selected : rows[0].conversation_id;
    await openConversation($('conversation-list').value);
  }
}
async function openConversation(id) {
  const token = ++state.selection;
  clearEvaluation();
  const conversation = await api('/api/conversations/' + encodeURIComponent(id));
  if (token !== state.selection) return;
  state.conversation = conversation;
  try {localStorage.setItem('cqa-conversation',id);} catch (_) {}
  $('conversation-list').value = id;
  $('conversation-info').textContent = `${id} · ${conversation.language} · ${conversation.channel}`;
  $('evaluate').disabled = false;
  $('conversation-title').textContent = id;
  $('conversation-meta').textContent = `${conversation.language} · ${conversation.channel === 'agent chat' ? 'Чат' : 'Звонок'}`;
  renderConversationCards();
  $('transcript').replaceChildren();
  conversation.transcript.forEach((turn, i) => {
    const li = el('li', null, {id: 'turn-' + (i + 1)});
    li.className = 'message message-' + turn.speaker;
    const roles = {client:'Клиент',operator:'Оператор',bot:'AI-ассистент',system:'Система'};
    const meta=el('div',null,{className:'message-meta'});
    meta.append(el('span',roles[turn.speaker] || turn.speaker,{className:'message-role'}),el('span',`${turn.timestamp} / ${i+1}`,{className:'message-time'}));
    const text=el('p');text.textContent=turn.text;text.dataset.source='true';li.append(meta,text);
    $('transcript').append(li);
  });
  $('audio').replaceChildren();
  if (conversation.audio_url) {
    let url;
    try { url = new URL(conversation.audio_url); } catch (_) { url = null; }
    if (url && ['https:', 'http:'].includes(url.protocol)) {
      const audio = el('audio', null, {controls: true, preload: 'none', src: url.href});
      const link = el('a', 'Open recording', {href: url.href, target: '_blank', rel: 'noopener noreferrer'});
      $('audio').append(audio, document.createTextNode(' '), link);
    } else $('audio').textContent = 'Recording link is unavailable.';
  }
  revealSelectedConversation();
  await loadEvaluations(null, token);
}
async function loadEvaluations(preferred = null, token = state.selection) {
  if (!state.conversation) return;
  const id = state.conversation.conversation_id;
  const rows = await api('/api/evaluations?conversation_id=' + encodeURIComponent(id));
  if (token !== state.selection) return;
  const matching = rows.filter(r => r.checklist_version_id === $('checklist-select').value);
  $('evaluation-list').replaceChildren();
  if (!matching.length) { clearEvaluation(); $('evaluation-summary').textContent = 'Для выбранного чек-листа пока нет оценки.'; return; }
  for (const row of matching.toReversed ? matching.toReversed() : [...matching].reverse()) {
    option($('evaluation-list'), `${row.created_at} · ${row.status} · ${row.model_metadata.name} · ${row.model_metadata.rubric_guidance_version || 'old rules'}`, row.id);
  }
  $('evaluation-list').value = preferred && matching.some(r => r.id === preferred) ? preferred : matching[matching.length - 1].id;
  await showEvaluation($('evaluation-list').value, token);
}
async function showEvaluation(id, token = state.selection) {
  const view = await api('/api/evaluations/' + encodeURIComponent(id));
  if (token !== state.selection || view.original.conversation_id !== state.conversation?.conversation_id) return;
  state.view = view;
  renderEvaluation();
}
function jumpTo(turn) {
  if(location.hash!=='#conversations')location.hash='conversations';
  if(typeof showWorkspace==='function'){showWorkspace();setReviewMode(innerWidth>900?'compare':'transcript');}
  document.querySelectorAll('.selected-turn').forEach(n => n.classList.remove('selected-turn'));
  const li = $('turn-' + turn);
  if (li) { li.classList.add('selected-turn'); li.scrollIntoView({behavior: 'smooth', block: 'center'}); }
}
function renderEvaluation() {
  const view = state.view;
  $('results').replaceChildren(); $('appeal-criterion').replaceChildren();
  $('decision-history').textContent = 'Решений по апелляциям пока нет.';
  const result = view.final, original = view.original;
  const contactCheck = original.contact_check;
  $('contact-check-info').textContent = sourceCheckSummary(original);
  const toneHints = original.tone_observations?.possible_informal_address || [];
  if (toneHints.length) $('contact-check-info').textContent += ` ${ui('Возможное неформальное обращение: реплики')} ${toneHints.map(h=>h.turn).join(', ')}.`;
  $('submit-appeal').disabled = result.status !== 'ok';
  $('review-warning').textContent = result.needs_review ? 'Ожидает проверки экспертом' : '';
  if (result.status !== 'ok') {
    updateScore(null);
    $('score-label').textContent = 'Ошибка оценки';
    $('score-description').textContent = result.error;
    $('evaluation-summary').textContent = `Evaluation failed: ${result.error}. No score calculated.`;
    return;
  }
  $('evaluation-summary').textContent = `Original score: ${original.score.final_score ?? 'N/A'} / 100. Current score: ${result.score.final_score ?? 'N/A'} / 100. Critical violation: ${result.score.critical_flag ? 'YES' : 'No'}. Checklist: ${result.checklist_version_id}. Model: ${result.model_metadata.name}. Rubric: ${result.model_metadata.rubric_guidance_version || 'old rules'}. Duration: ${result.elapsed_seconds}s. Review revision: ${view.revision}.`;
  updateScore(result);
  const checklist = state.checklists.find(c => c.id === result.checklist_version_id);
  $('criteria-count').textContent = `${result.criteria.length} критериев`;
  const titles = {contact:'Первый контакт',discovery:'Выявление потребности',identification:'Идентификация',consultation:'Качество консультации',empathy:'Эмпатия и деловой тон',dialogue:'Управление диалогом',closure:'Завершение диалога',critical:'Критические нарушения'};
  result.criteria.forEach((j,index) => {
    const definition = checklist?.criteria.find(c => c.id === j.criterion_id);
    const title = ui(titles[j.criterion_id] || definition?.title || j.criterion_id);
    const points = result.contributions?.find(c => c.criterion_id === j.criterion_id)?.earned_before_normalization;
    const isFlag = definition?.response_type === 'flag';
    const max = definition?.weight || 0;
    const ratio = max ? Number(points)/max : (j.value ? 0 : 1);
    const status = j.value === null ? 'neutral' : (isFlag ? (j.value ? 'bad' : 'good') : ratio >= .8 ? 'good' : ratio >= .5 ? 'medium' : 'bad');
    const card = el('details',null,{className:'criterion '+status});
    card.style.setProperty('--criterion-progress',`${Math.max(0,Math.min(100,ratio*100))}%`);
    const summary = el('summary');
    const heading = el('div',null,{className:'criterion-name'});
    heading.append(el('strong',title));
    const values=el('div',null,{className:'criterion-values'});
    values.append(el('span',valueLabel(j.value),{className:'badge '+status}),el('span',isFlag ? 'Флаг' : points === null ? 'N/A' : `${points ?? '—'} / ${max}`,{className:'points'}),el('span','+',{className:'chevron'}));
    summary.append(heading,values);card.append(summary);card.addEventListener('toggle',()=>{card.querySelector('.chevron').textContent=card.open?'−':'+';});
    const body=el('div',null,{className:'criterion-body'});
    const rationale=el('p');rationale.textContent=j.rationale;rationale.dataset.source='true';body.append(rationale);
    body.append(el('p',isFlag ? 'Критический флаг учитывается отдельно от итогового балла.' : `Вес критерия: ${max}. Баллы до нормализации: ${points === null ? 'N/A — исключён из расчёта' : points}.`,{className:'muted'}));
    const audit=original.evidence_audit?.[j.criterion_id];
    if(audit) {
      body.append(el('blockquote',`${view.decisions.some(d=>d.criterion_id===j.criterion_id)?'Источник исходной AI-оценки, реплика':'Реплика'} #${audit.quote_turn}: «${audit.evidence_quote}»`));
      const extra=el('details',null,{className:'audit-details'});extra.append(el('summary','Инструкция и проверенные факты'));
      extra.append(el('p',definition?.description || ''),el('p',audit.applicability_reason));
      for(const [key,value] of Object.entries(audit.decision_facts || {})) extra.append(el('p',`${ui(key)}: ${valueLabel(value)}`));
      body.append(extra);
    }
    const actions=el('div',null,{className:'criterion-actions'});
    const sources=el('div',null,{className:'sources'});sources.append(el('span','Источник: '));
    for(const turn of j.evidence_turns){const b=el('button',`#${turn}`,{type:'button',title:'Перейти к реплике'});b.onclick=()=>jumpTo(turn);sources.append(b);}
    const appeal=el('button','Оспорить оценку ↗',{type:'button',className:'appeal-button',title:'Оспорить оценку: '+title});
    appeal.onclick=()=>{$('appeal-criterion').value=j.criterion_id;$('appeal-feedback').textContent='';$('appeal-dialog').showModal();$('appeal-comment').focus();};
    actions.append(sources,appeal);body.append(actions);card.append(body);$('results').append(card);
    option($('appeal-criterion'),title,j.criterion_id);
  });
  $('decision-history').replaceChildren();
  if (!view.decisions.length) $('decision-history').textContent = 'Решений по апелляциям пока нет.';
  for (const d of view.decisions) $('decision-history').append(el('p', `${d.created_at} · ${d.criterion_id}: ${valueLabel(d.old_value)} → ${valueLabel(d.new_value)}. ${d.reason}`));
}
async function evaluate() {
  if (!state.conversation) return;
  const id = state.conversation.conversation_id;
  const token = state.selection;
  $('evaluate').disabled = true;
  $('evaluate').textContent = 'Анализируем…';
  message('Оцениваем диалог… Локальной модели может потребоваться несколько минут.');
  try {
    const result = await api('/api/evaluations', {conversation_id: id, checklist_id: $('checklist-select').value, force: $('force').checked});
    if (token === state.selection) await loadEvaluations(result.original.id, token);
    await refreshConversationStatuses();
    message(result.original.status === 'ok' ? (result.cached ? 'Загружена сохранённая оценка.' : 'Оценка сохранена. Требуется проверка экспертом.') : result.original.error, result.original.status !== 'ok');
  } finally { $('evaluate').disabled = !state.conversation; $('evaluate').textContent = 'Оценить диалог ↗'; }
}
async function batch() {
  $('batch').disabled = true;
  try {
    const job = await api('/api/evaluations/batch', {dataset: $('dataset').value, checklist_id: $('checklist-select').value, force:false, only_unevaluated:true});
    clearTimeout(pollTimer);
    const poll = async () => {
      try {
        const progress = await api('/api/jobs/' + job.id);
        const errors = progress.items.filter(i => i.status === 'error').length;
        await refreshConversationStatuses();
        $('job-status').textContent = `${progress.dataset.toUpperCase()}: ${progress.status}. Completed ${progress.items.length}/${progress.conversation_ids.length}; errors ${errors}.`;
        if (['queued', 'running'].includes(progress.status)) pollTimer = setTimeout(poll, 3000);
        else { $('batch').disabled = false; await loadEvaluations(); await health(); if (progress.error) message(progress.error, true); }
      } catch (error) { $('batch').disabled = false; message(error.message + ' Use Refresh to inspect saved evaluations.', true); }
    };
    await poll();
  } catch (error) { $('batch').disabled = false; throw error; }
}

function editorField(tag, value, label, props = {}) {
  const node = el(tag, null, {...props});
  node.setAttribute('aria-label', label);
  if (tag !== 'select') node.value = value ?? '';
  return node;
}
function appendCriterion(c) {
  const tr = el('tr');
  tr.dataset.section = c.section || '';
  const id = editorField('input', c.id, 'Criterion ID', {required: true}); id.dataset.field = 'id';
  const title = editorField('input', c.title, 'Criterion title', {required: true}); title.dataset.field = 'title';
  const description = editorField('textarea', c.description, 'Criterion instruction', {required: true, rows: 5}); description.dataset.field = 'description';
  const weight = editorField('input', c.weight, 'Criterion weight', {type: 'number', min: '0', step: 'any', required: true}); weight.dataset.field = 'weight';
  const type = editorField('select', '', 'Response type'); type.dataset.field = 'response_type';
  for (const k of ['boolean', 'scale', 'flag']) option(type, k, k); type.value = c.response_type;
  const allowed = editorField('input', JSON.stringify(c.allowed_values), 'Allowed values as JSON', {required: true}); allowed.dataset.field = 'allowed_values';
  const allow = editorField('input', '', 'Allow N/A', {type: 'checkbox', checked: c.allow_na}); allow.dataset.field = 'allow_na';
  const condition = editorField('textarea', c.na_condition, 'N/A condition', {rows: 3}); condition.dataset.field = 'na_condition';
  for (const nodes of [[id, title], [description], [weight, type], [allowed], [el('label', 'Allow N/A'), condition]]) {
    const td = el('td'); td.append(...nodes); tr.append(td);
  }
  if (c.decision_guidance) {
    const details = el('details');
    details.append(el('summary', 'Применяемые правила оценки'), el('p', c.decision_guidance));
    tr.children[1].append(details);
  }
  tr.children[4].firstChild.prepend(allow);
  const action = el('td'); const remove = el('button', 'Remove', {type: 'button'}); remove.onclick = () => tr.remove(); action.append(remove); tr.append(action);
  $('criteria-editor').append(tr);
}
function renderEditor() {
  const c = state.checklists.find(c => c.id === $('checklist-select').value);
  $('criteria-editor').replaceChildren();
  if (!c) return;
  $('checklist-name').value = c.name;
  $('checklist-version').textContent = 'Исходная версия: ' + c.id;
  c.criteria.forEach(criterion => appendCriterion({...criterion, decision_guidance: c.evaluation_guidance?.[criterion.id]}));
}
async function saveChecklist() {
  const criteria = [...$('criteria-editor').children].map(row => {
    const get = name => row.querySelector(`[data-field="${name}"]`);
    let allowed;
    try { allowed = JSON.parse(get('allowed_values').value); } catch (_) { throw new Error(`Allowed values for ${get('id').value} must be a JSON array, for example [true,false,null].`); }
    return {id: get('id').value.trim(), title: get('title').value, description: get('description').value, weight: Number(get('weight').value), response_type: get('response_type').value, allowed_values: allowed, allow_na: get('allow_na').checked, na_condition: get('na_condition').value, section: row.dataset.section};
  });
  const c = await api('/api/checklists/' + encodeURIComponent($('checklist-select').value) + '/versions', {name: $('checklist-name').value, criteria});
  await loadChecklists(c.id); clearEvaluation(); await loadEvaluations();
  message('Saved new checklist version. Select Evaluate selected to apply it to the conversation.');
}

async function loadAppeals(selected = '') {
  state.appeals = await api('/api/appeals');
  $('appeal-select').replaceChildren(el('option', 'Выберите апелляцию', {value: ''}));
  for (const a of [...state.appeals].reverse()) option($('appeal-select'), `${ui(a.status)} / ${ui(criterionNames[a.criterion_id]||a.criterion_id)} / ${a.comment.slice(0,70)}`, a.id);
  $('appeal-select').value = selected;
  if (selected) await openAppeal();
}
async function submitAppeal() {
  if (!state.view) return;
  const appeal = await api('/api/appeals', {evaluation_id: state.view.original.id, criterion_id: $('appeal-criterion').value, comment: $('appeal-comment').value});
  $('appeal-comment').value = '';
  await loadAppeals(appeal.id);
  message('Апелляция отправлена на рассмотрение.');
  $('appeal-dialog').close();
  location.hash = 'appeals';
}
async function openAppeal() {
  state.appeal = state.appeals.find(a => a.id === $('appeal-select').value) || null;
  $('save-decision').disabled = true; $('decision-value').replaceChildren();
  if (!state.appeal) { $('appeal-details').textContent = ''; return; }
  const a = state.appeal;
  const view = await api('/api/evaluations/' + encodeURIComponent(a.evaluation_id));
  const checklist = state.checklists.find(c => c.id === view.original.checklist_version_id);
  const criterion = checklist.criteria.find(c => c.id === a.criterion_id);
  const judgment = view.final.criteria.find(c => c.criterion_id === a.criterion_id);
  state.appeal = {...a, revision: view.revision};
  state.appealDetailView=view;
  $('appeal-details').textContent=appealDescription(a,view);
  for (const v of criterion.allowed_values) option($('decision-value'), valueLabel(v), JSON.stringify(v));
  $('decision-value').value = JSON.stringify(judgment.value);
  $('decision-evidence').value = judgment.evidence_turns.join(', ');
  $('decision-reason').value = '';
  $('save-decision').disabled = a.status !== 'open';
  if (state.conversation?.conversation_id !== view.original.conversation_id) await openConversation(view.original.conversation_id);
  state.view = view;
  if ($('checklist-select').value !== view.original.checklist_version_id) {
    $('checklist-select').value = view.original.checklist_version_id; renderEditor();
  }
  await loadEvaluations(view.original.id);
}
async function saveDecision() {
  const a = state.appeal;
  if (!a || a.status !== 'open') return;
  const pieces = $('decision-evidence').value.trim().split(',').map(s => s.trim());
  if (pieces.some(s => !/^\d+$/.test(s))) throw new Error('Enter source turn numbers separated by commas, for example 10, 12.');
  const result = await api('/api/appeals/' + encodeURIComponent(a.id) + '/decision', {action: $('decision-action').value, value: JSON.parse($('decision-value').value), reason: $('decision-reason').value, evidence_turns: pieces.map(Number), expected_revision: a.revision});
  await loadEvaluations(result.original.id); await loadAppeals(a.id);
  message('Решение сохранено. Текущая оценка обновлена, исходная доступна в истории.');
}
async function importData(options={}) {
  const body = {dataset: $('dataset').value, expected: Number($('expected').value)};
  const file = $('import-file').files[0];
  if (file && !options.fromApi) body.payload = JSON.parse(await file.text());
  else if ($('group-id').value.trim()) body.group_id = $('group-id').value.trim();
  $('import-api').disabled=true;
  try {
    message('Загрузка диалогов…');
    const result = await api('/api/conversations/import', body);
    await health(); await loadConversations(); message(`Imported ${result.total} conversations into ${result.dataset.toUpperCase()}.`);
  } finally { $('import-api').disabled=false; }
}
async function exportData() {
  const dataset = $('dataset').value;
  const payload = await api('/api/export/' + dataset, {expected: dataset === 'dev' ? 65 : 10, reviewed: $('reviewed-export').checked});
  const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2) + '\n'], {type: 'application/json;charset=utf-8'}));
  const anchor = el('a', null, {href: url, download: 'results.json'}); document.body.append(anchor); anchor.click(); anchor.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  const errors = payload.results.filter(r => r.status === 'error').length;
  $('export-status').textContent = `Downloaded ${payload.results.length} records (${errors} errors). Save as results/${dataset}/results.json in your repository.`;
}

$('refresh').onclick = run(async () => { await health(); await loadConversations(); message('Refreshed.'); });
$('dataset').onchange = run(async () => { $('expected').value = $('dataset').value === 'dev' ? 65 : 10; $('group-id').value=$('dataset').value==='dev'?'DEV':'FBroker'; await loadConversations(); });
$('language').onchange = run(loadConversations); $('channel').onchange = run(loadConversations);
$('conversation-list').onchange = run(() => openConversation($('conversation-list').value));
$('checklist-select').onchange = run(async () => { state.selection++; renderEditor(); clearEvaluation(); await loadEvaluations(); await refreshConversationStatuses(); });
$('evaluation-list').onchange = run(() => showEvaluation($('evaluation-list').value));
$('evaluate').onclick = run(evaluate); $('batch').onclick = run(batch);
$('appeal-form').onsubmit = async event => {event.preventDefault(); $('submit-appeal').disabled=true;try {await submitAppeal();} catch(e){$('appeal-feedback').textContent=e.message;} finally {$('submit-appeal').disabled=false;}};
$('checklist-form').onsubmit = run(saveChecklist);
$('add-criterion').onclick = () => appendCriterion({id: 'new_criterion', title: 'New criterion', description: '', weight: 10, response_type: 'boolean', allowed_values: [true, false], allow_na: false, na_condition: ''});
$('refresh-appeals').onclick = run(() => loadAppeals());
$('appeal-select').onchange = run(openAppeal);
$('decision-action').onchange = () => { $('decision-value').disabled = $('decision-action').value !== 'override'; };
$('decision-form').onsubmit = run(saveDecision);
$('import-form').onsubmit = run(importData); $('export').onclick = run(exportData);
$('import-api').onclick = run(()=>importData({fromApi:true}));
$('import-fbroker').onclick = run(async()=>{
  $('import-fbroker').disabled=true;
  try {
    const result=await api('/api/conversations/import',{dataset:'prod',group_id:'FBroker',expected:10});
    $('dataset').value='prod'; $('expected').value='10'; $('group-id').value='FBroker';
    await health(); await loadConversations();
    message(`FBroker: ${result.total} диалогов загружено в PROD. Оценка запускается отдельно.`);
  } finally {$('import-fbroker').disabled=false;}
});
$('save-swap').onclick = run(async()=>{
  $('save-swap').disabled=true;
  try {
    const result=await api('/api/supplementary-datasets/swap',{});
    $('swap-status').textContent=`SWAP: сохранено ${result.total} диалога. Оценка не запускалась; в PROD не включены.`;
    message($('swap-status').textContent);
  } finally {$('save-swap').disabled=false;}
});
run(async () => { await health(); await loadChecklists(); await loadConversations(); await loadAppeals(); await health();
  const swap=await api('/api/supplementary-datasets/swap');
  if(swap.status==='saved_not_evaluated') $('swap-status').textContent=`SWAP: сохранено ${swap.total} диалога. Оценка не запускалась; в PROD не включены.`;
})();

function updateScore(result){
  const score=result?.score?.final_score;
  const present=typeof score==='number';
  const color=!present?'var(--line)':score>=80?'var(--green)':score>=60?'var(--amber)':'var(--red)';
  $('score-number').textContent=present?new Intl.NumberFormat(UI_LANG==='en'?'en-US':UI_LANG==='kk'?'kk-KZ':'ru-RU',{maximumFractionDigits:2}).format(score):'—';
  $('score-ring').style.setProperty('--score',present?score:0);$('score-ring').style.setProperty('--score-color',color);
  $('score-ring').setAttribute('aria-label',present?`Текущая оценка ${score} из 100`:'Оценка отсутствует');
  $('score-label').textContent=!present?'Ожидает оценки':score>=80?'Высокое качество':score>=60?'Есть что улучшить':'Требует внимания';
  $('score-description').textContent=present?state.view?.revision ? 'С учётом пересмотра' : 'Автоматическая оценка':'Запустите анализ выбранного диалога';
  $('critical-status').textContent=result?.score?.critical_flag?'Критическое нарушение':present?'Критических нарушений нет':'';
  $('critical-status').className=result?.score?.critical_flag?'critical-alert':'muted';
}
function renderConversationCards(){
  const query=$('conversation-search').value.toLowerCase();$('conversation-cards').replaceChildren();
  const rows=(state.conversations||[]).filter(c=>c.conversation_id.toLowerCase().includes(query));
  const pages=Math.max(1,Math.ceil(rows.length/10));state.libraryPage=Math.min(state.libraryPage||0,pages-1);
  for(const c of rows.slice(state.libraryPage*10,(state.libraryPage+1)*10)){
    const button=el('button',null,{type:'button',className:'conversation-card'+(state.conversation?.conversation_id===c.conversation_id?' selected':'')});
    const content=el('span');content.append(el('strong',c.conversation_id),el('small',`${ui(c.channel==='agent chat'?'Чат':'Звонок')} / ${c.turn_count} ${ui('реплик')}`));
    const status=c.evaluation_status?.status||'not_evaluated';
    const labels={evaluated:'Оценён',not_evaluated:'Не оценён',error:'Ошибка · повторить',queued:'В очереди'};
    const indicator=el('span',labels[status],{className:'evaluation-badge status-'+status});
    button.append(content,indicator,el('span',c.language,{className:'language-label'}),el('span','↗',{className:'list-arrow'}));
    button.setAttribute('aria-pressed',String(state.conversation?.conversation_id===c.conversation_id));
    button.onclick=run(async()=>{await openConversation(c.conversation_id);showWorkspace();});$('conversation-cards').append(button);
  }
  if(!rows.length)$('conversation-cards').append(el('p',query?'По этому запросу диалогов нет.':'В этом наборе пока нет диалогов.',{className:'empty-list'}));
  $('page-info').textContent=`${state.libraryPage+1} / ${pages}`;
  $('page-prev').disabled=!state.libraryPage;$('page-next').disabled=state.libraryPage>=pages-1;
  $('conversation-count').textContent=`${rows.length} ${ui('диалогов')} · ${rows.filter(c=>c.evaluation_status?.status==='evaluated').length} ${ui('оценено')}`;
}
async function refreshConversationStatuses(){
  const query=new URLSearchParams({dataset:$('dataset').value,checklist_id:$('checklist-select').value||'official-v1'});
  const rows=await api('/api/conversations?'+query);
  const statuses=new Map(rows.map(c=>[c.conversation_id,c.evaluation_status]));
  for(const row of state.conversations||[])row.evaluation_status=statuses.get(row.conversation_id);
  renderConversationCards();
}
setInterval(()=>{if(document.visibilityState==='visible'&&document.body.dataset.page==='conversations')refreshConversationStatuses().catch(()=>{});},10000);
function route(){const target=['overview','conversations','checklist-editor','appeals','data'].includes(location.hash.slice(1))?location.hash.slice(1):(new URLSearchParams(location.search).has('conversation')?'conversations':'overview');document.querySelectorAll('.page-content > section').forEach(s=>s.hidden=s.id!==target);document.body.dataset.page=target;document.querySelectorAll('.app-header nav a').forEach(a=>{a.classList.toggle('active',a.hash==='#'+target);a.setAttribute('aria-current',a.hash==='#'+target?'page':'false');});}
$('conversation-search').oninput=()=>{state.libraryPage=0;renderConversationCards();};
$('close-appeal').onclick=()=>$('appeal-dialog').close();
$('appeal-dialog').addEventListener('click',e=>{if(e.target===$('appeal-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}});
let theme='dark';try{theme=new URLSearchParams(location.search).get('theme')||localStorage.getItem('cqa-theme')||'dark';}catch(_){}document.documentElement.dataset.theme=theme;
function updateThemeLabel(){
  const dark=document.documentElement.dataset.theme==='dark';
  $('theme-toggle').textContent=ui(dark?'Светлая тема':'Тёмная тема');
  $('theme-toggle').setAttribute('aria-label',ui(dark?'Включить светлую тему':'Включить тёмную тему'));
  $('theme-toggle').setAttribute('aria-pressed',String(dark));
}
updateThemeLabel();
$('theme-toggle').onclick=()=>{theme=document.documentElement.dataset.theme==='dark'?'light':'dark';document.documentElement.dataset.theme=theme;try{localStorage.setItem('cqa-theme',theme);}catch(_){}updateThemeLabel();};
window.addEventListener('hashchange',route);route();

function revealSelectedConversation(){
  const list=$('conversation-cards');
  const active=list.querySelector('[aria-pressed="true"]');
  if(!active || !list.clientWidth)return;
  if(getComputedStyle(list).flexDirection==='row')list.scrollLeft=active.offsetLeft-list.clientWidth/2+active.clientWidth/2;
  else list.scrollTop=active.offsetTop-list.clientHeight/2+active.clientHeight/2;
}
let listResizeFrame;
window.addEventListener('resize',()=>{cancelAnimationFrame(listResizeFrame);listResizeFrame=requestAnimationFrame(revealSelectedConversation);});
window.addEventListener('hashchange',()=>requestAnimationFrame(revealSelectedConversation));

document.addEventListener('keydown',e=>{if(e.key==='/'&&!['INPUT','TEXTAREA','SELECT'].includes(document.activeElement.tagName)){e.preventDefault();$('conversation-search').focus();}});

document.querySelectorAll('.editorial-links a,.hero-primary').forEach(a=>a.addEventListener('click',()=>{window.scrollTo({top:0,behavior:'instant'});}));
