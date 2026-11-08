'use strict';
let reviewMode='transcript';let visibleWorkspace=false;
function showWorkspace(){visibleWorkspace=true;$('conversation-library').hidden=true;$('review-workspace').hidden=false;setReviewMode(reviewMode);window.scrollTo({top:0,behavior:'instant'});}
function showLibrary(){visibleWorkspace=false;$('conversation-library').hidden=false;$('review-workspace').hidden=true;window.scrollTo({top:0,behavior:'instant'});}
function setReviewMode(mode){
 if(innerWidth<=900&&mode==='compare')mode='transcript';reviewMode=mode;$('review-panels').dataset.mode=mode;
 const transcript=mode!=='evaluation',assessment=mode!=='transcript';
 document.querySelector('.review-panels .conversation').hidden=!transcript;document.querySelector('.review-panels .assessment').hidden=!assessment;
 document.querySelectorAll('[data-review-mode]').forEach(b=>{const on=b.dataset.reviewMode===mode;b.setAttribute('aria-pressed',String(on));b.classList.toggle('active',on);});
 $('toggle-transcript').textContent=ui(transcript?'Скрыть переписку':'Показать переписку');$('toggle-transcript').setAttribute('aria-pressed',String(transcript));
 $('toggle-assessment').textContent=ui(assessment?'Скрыть оценку':'Показать оценку');$('toggle-assessment').setAttribute('aria-pressed',String(assessment));
}
$('back-library').onclick=showLibrary;
document.querySelectorAll('[data-review-mode]').forEach(b=>b.onclick=()=>setReviewMode(b.dataset.reviewMode));
$('toggle-transcript').onclick=()=>setReviewMode(reviewMode==='evaluation'?(innerWidth>900?'compare':'transcript'):'evaluation');
$('toggle-assessment').onclick=()=>setReviewMode(reviewMode==='transcript'?(innerWidth>900?'compare':'evaluation'):'transcript');
$('page-prev').onclick=()=>{state.libraryPage=Math.max(0,(state.libraryPage||0)-1);renderConversationCards();};
$('page-next').onclick=()=>{state.libraryPage=(state.libraryPage||0)+1;renderConversationCards();};
let viewportTimer;let previousWidth=innerWidth;
window.addEventListener('resize',()=>{clearTimeout(viewportTimer);viewportTimer=setTimeout(()=>{
 if(innerWidth<200||innerHeight<200)return;
 if(innerWidth!==previousWidth&&innerWidth<=900&&reviewMode==='compare')setReviewMode('transcript');
 previousWidth=innerWidth;positionSelectPopup();
},120);});
document.querySelector('.app-header nav a[href="#conversations"]').addEventListener('click',showLibrary);
document.querySelectorAll('.global-footer a[href="#conversations"],.hero-primary').forEach(a=>a.addEventListener('click',showLibrary));
if(new URLSearchParams(location.search).has('conversation'))showWorkspace();else showLibrary();

// The browser file chooser stays native; its visible control matches the site.
$('choose-file').onclick=()=>$('import-file').click();
$('import-file').addEventListener('change',()=>{$('file-name').textContent=$('import-file').files[0]?.name||ui('Файл не выбран');});

// A single accessible listbox replaces operating-system select menus.
const SELECTS=new Map();let popup=null;let popupOwner=null;let activeOption=0;let selectSerial=0;
function closeSelectPopup(){if(popupOwner){popupOwner.button.setAttribute('aria-expanded','false');popupOwner.button.removeAttribute('aria-activedescendant');}popup?.remove();popup=null;popupOwner=null;}
function syncSelect(item){
 const option=item.select.selectedOptions[0];const text=option?ui(option.textContent):'—';if(item.label.textContent!==text)item.label.textContent=text;
 if(item.button.disabled!==item.select.disabled)item.button.disabled=item.select.disabled;
}
function openSelectPopup(item,index){
 if(item.select.disabled)return;closeSelectPopup();popupOwner=item;popup=el('div',null,{className:'select-popup',id:item.id});popup.setAttribute('role','listbox');
 const options=[...item.select.options];activeOption=index??Math.max(0,item.select.selectedIndex);
 options.forEach((option,i)=>{const b=el('button',ui(option.textContent),{type:'button',id:item.id+'-'+i});b.setAttribute('role','option');b.setAttribute('aria-selected',String(option.selected));b.disabled=option.disabled;b.addEventListener('mousedown',e=>e.preventDefault());b.onclick=()=>{item.select.value=option.value;syncSelect(item);closeSelectPopup();item.select.dispatchEvent(new Event('change',{bubbles:true}));item.button.focus();};popup.append(b);});
 document.body.append(popup);item.button.setAttribute('aria-expanded','true');item.button.setAttribute('aria-controls',item.id);
 positionSelectPopup();highlightOption();
}
function positionSelectPopup(){if(!popup||!popupOwner||innerWidth<200||innerHeight<200)return;
 const r=popupOwner.button.getBoundingClientRect();if(r.width<1)return;
 const height=Math.min(320,popup.scrollHeight),below=innerHeight-r.bottom-14,top=below>=Math.min(height,150)?r.bottom+5:Math.max(10,r.top-height-5);
 popup.style.left=Math.max(10,Math.min(r.left,innerWidth-r.width-10))+'px';popup.style.top=top+'px';popup.style.width=Math.min(r.width,innerWidth-20)+'px';popup.style.maxHeight=Math.max(90,Math.min(320,top>=r.bottom?innerHeight-top-10:r.top-15))+'px';
}
function highlightOption(){if(!popup)return;const options=[...popup.children];activeOption=Math.max(0,Math.min(activeOption,options.length-1));options.forEach((b,i)=>b.classList.toggle('active-option',i===activeOption));const active=options[activeOption];if(active){popupOwner.button.setAttribute('aria-activedescendant',active.id);active.scrollIntoView({block:'nearest'});}}
function enhanceSelects(){
 document.querySelectorAll('select:not([multiple]):not(#conversation-list)').forEach(select=>{
  if(SELECTS.has(select)){syncSelect(SELECTS.get(select));return;}
  const wrapper=el('div',null,{className:'enhanced-select'});select.before(wrapper);wrapper.append(select);select.tabIndex=-1;select.setAttribute('aria-hidden','true');
  const button=el('button',null,{type:'button',className:'select-trigger'});button.setAttribute('role','combobox');button.setAttribute('aria-haspopup','listbox');button.setAttribute('aria-expanded','false');
  const enclosing=wrapper.closest('label');let labelText=select.getAttribute('aria-label')||enclosing?.childNodes[0]?.textContent.trim()||ui('Выберите значение');button.setAttribute('aria-label',labelText);
  const label=el('span');button.append(label,el('span','⌄',{className:'select-arrow','ariaHidden':'true'}));wrapper.append(button);
  const item={select,button,label,id:'cqa-options-'+(++selectSerial)};SELECTS.set(select,item);syncSelect(item);
  button.onclick=()=>popupOwner===item?closeSelectPopup():openSelectPopup(item);
  button.onkeydown=e=>{if(e.key==='Escape'&&popup){e.preventDefault();e.stopPropagation();closeSelectPopup();return;}if(e.key==='Tab'){closeSelectPopup();return;}if(['ArrowDown','ArrowUp','Home','End','Enter',' '].includes(e.key)){e.preventDefault();if(popupOwner!==item){openSelectPopup(item);return;}if(e.key==='Enter'||e.key===' '){popup.children[activeOption]?.click();return;}activeOption=e.key==='Home'?0:e.key==='End'?select.options.length-1:activeOption+(e.key==='ArrowDown'?1:-1);highlightOption();}else if(e.key.length===1){const found=[...select.options].findIndex(o=>ui(o.textContent).toLocaleLowerCase().startsWith(e.key.toLocaleLowerCase()));if(found>=0){e.preventDefault();if(popupOwner!==item)openSelectPopup(item,found);else{activeOption=found;highlightOption();}}}};
  select.addEventListener('change',()=>syncSelect(item));select.addEventListener('invalid',()=>button.focus());
 });
 for(const [select,item] of SELECTS){if(!select.isConnected)SELECTS.delete(select);else syncSelect(item);}
}
document.addEventListener('pointerdown',e=>{if(popup&&!popup.contains(e.target)&&!popupOwner.button.contains(e.target))closeSelectPopup();});
window.addEventListener('scroll',e=>{if(popup&&!popup.contains(e.target))requestAnimationFrame(positionSelectPopup);},{capture:true,passive:true});
window.addEventListener('hashchange',closeSelectPopup);
let selectRefresh=false;new MutationObserver(()=>{if(selectRefresh)return;selectRefresh=true;queueMicrotask(()=>{selectRefresh=false;enhanceSelects();});}).observe(document.body,{childList:true,subtree:true,attributes:true,attributeFilter:['disabled','selected']});

// Human-readable, expandable criterion editor. Source instructions remain editable data.
const criterionNames={contact:'Первый контакт',discovery:'Выявление потребности',identification:'Идентификация',consultation:'Качество консультации',empathy:'Эмпатия и деловой тон',dialogue:'Управление диалогом',closure:'Завершение диалога',critical:'Критические нарушения'};
function editorLabel(text,node){const label=el('label');label.append(el('span',text),node);return label;}
appendCriterion=function(c){
 const row=el('details',null,{className:'editor-criterion'});row.dataset.section=c.section||'';
 const summary=el('summary');const titleText=el('strong',criterionNames[c.id]||c.title||'Новый критерий');summary.append(titleText,el('span',`${c.weight} ${ui('баллов')}`,{className:'editor-weight'}),el('span','+',{className:'editor-plus'}));row.append(summary);
 const body=el('div',null,{className:'editor-rule-body'});
 const field=(tag,value,name,props={})=>{const n=editorField(tag,value,ui(name),props);return n;};
 const id=field('input',c.id,'ID',{required:true});id.dataset.field='id';
 const title=field('input',c.title,'Название критерия',{required:true});title.dataset.field='title';
 const description=field('textarea',c.description,'Что проверяем',{required:true,rows:5});description.dataset.field='description';
 const weight=field('input',c.weight,'Вес в общей оценке',{type:'number',min:0,step:'any',required:true});weight.dataset.field='weight';
 const type=field('select','','Тип результата');type.dataset.field='response_type';for(const [value,label]of [['boolean','Да / Нет'],['scale','Шкала баллов'],['flag','Критический флаг']])option(type,label,value);type.value=c.response_type;
 const allowed=field('input',JSON.stringify(c.allowed_values),'Allowed values',{type:'hidden'});allowed.dataset.field='allowed_values';
 const scale=field('input',c.allowed_values.filter(v=>typeof v==='number').join(', '),'Шаги шкалы через запятую',{placeholder:'0, 5, 10, 15, 20'});
 const allow=field('input','','Разрешить N/A',{type:'checkbox',checked:c.allow_na});allow.dataset.field='allow_na';
 const condition=field('textarea',c.na_condition,'Когда критерий неприменим',{rows:3});condition.dataset.field='na_condition';
 const grid=el('div',null,{className:'rule-grid'});grid.append(editorLabel('Вес в общей оценке',weight),editorLabel('Тип результата',type));
 const scaleLabel=editorLabel('Шаги шкалы через запятую',scale);scaleLabel.hidden=c.response_type!=='scale';
 const conditionLabel=editorLabel('Когда критерий неприменим',condition);conditionLabel.hidden=!c.allow_na;
 body.append(editorLabel('Название критерия',title),editorLabel('Что проверяем',description),grid,scaleLabel,editorLabel('Разрешить N/A',allow),conditionLabel,allowed);
 const advanced=el('details',null,{className:'rule-advanced'});advanced.append(el('summary','Технические параметры'),editorLabel('ID',id));body.append(advanced);
 if(c.decision_guidance){const guidance=el('details',null,{className:'rule-advanced'});const p=el('p');p.textContent=c.decision_guidance;p.dataset.source='true';guidance.append(el('summary','Применяемые правила оценки'),p);body.append(guidance);}
 const remove=el('button','Удалить критерий',{type:'button',className:'remove-rule'});remove.onclick=()=>row.remove();body.append(remove);row.append(body);
 const rebuildAllowed=()=>{scaleLabel.hidden=type.value!=='scale';conditionLabel.hidden=!allow.checked;let values=type.value==='scale'?scale.value.split(',').filter(x=>x.trim()).map(x=>Number(x.trim())):[true,false];if(allow.checked)values.push(null);allowed.value=JSON.stringify(values);};
 type.onchange=rebuildAllowed;allow.onchange=rebuildAllowed;scale.oninput=rebuildAllowed;
 weight.oninput=()=>{summary.querySelector('.editor-weight').textContent=`${weight.value} ${ui('баллов')}`;};
 title.oninput=()=>{titleText.textContent=title.value;};
 row.addEventListener('toggle',()=>{row.querySelector('.editor-plus').textContent=row.open?'−':'+';if(row.open)for(const other of $('criteria-editor').children)if(other!==row)other.open=false;});
 $('criteria-editor').append(row);
};
function refreshEditorVersions(){const select=$('editor-version-select');select.replaceChildren();for(const c of state.checklists)option(select,`${c.name} (${c.id})`,c.id);select.value=$('checklist-select').value;enhanceSelects();}
$('editor-version-select').onchange=run(async()=>{$('checklist-select').value=$('editor-version-select').value;state.selection++;renderEditor();clearEvaluation();await loadEvaluations();});
$('checklist-select').addEventListener('change',()=>{$('editor-version-select').value=$('checklist-select').value;});
$('add-criterion').onclick=()=>{appendCriterion({id:'criterion_'+Date.now(),title:ui('Новый критерий'),description:'',weight:10,response_type:'boolean',allowed_values:[true,false],allow_na:false,na_condition:''});$('criteria-editor').lastElementChild.open=true;refreshInterface();};

function refreshInterface(){if(state.view?.final.status==='ok')$('evaluation-summary').textContent=evaluationHistory(state.view);applyLocale();enhanceSelects();setReviewMode(reviewMode);updateThemeLabel();applyLocale();}
document.querySelectorAll('[data-ui-lang]').forEach(button=>button.onclick=()=>{
 closeSelectPopup();UI_LANG=button.dataset.uiLang;try{localStorage.setItem('cqa-ui-language',UI_LANG);}catch(_){}
 const open=state.view?[...$('results').children].map((r,i)=>r.open?i:-1).filter(i=>i>=0):[];
 if(state.view){renderEvaluation();for(const i of open)if($('results').children[i])$('results').children[i].open=true;}else updateScore(null);
 renderConversationCards();if(state.appealDetailView)$('appeal-details').textContent=appealDescription(state.appeal,state.appealDetailView);
 const selected=$('appeal-select').value;$('appeal-select').replaceChildren(el('option','Выберите апелляцию',{value:''}));for(const a of [...state.appeals].reverse())option($('appeal-select'),`${ui(a.status)} / ${ui(criterionNames[a.criterion_id]||a.criterion_id)} / ${a.comment.slice(0,70)}`,a.id);$('appeal-select').value=selected;
 refreshInterface();
});
function appealDescription(a,view){const criterion=view.final.criteria.find(c=>c.criterion_id===a.criterion_id);return `${ui(a.status)} / ${view.original.conversation_id} / ${ui(criterionNames[a.criterion_id]||a.criterion_id)}. ${ui('Результат')}: ${valueLabel(criterion.value)}. ${ui('Апелляция')}: ${a.comment}. ${ui('Обоснование')}: ${criterion.rationale}`;}
function evaluationHistory(view){const i=UI_LANG==='en'?1:UI_LANG==='kk'?2:0;const labels=[['Исходная оценка','Original score','Бастапқы баға'],['Текущая оценка','Current score','Ағымдағы баға'],['Решений эксперта','Review decisions','Сарапшы шешімдері']];return `${labels[0][i]}: ${view.original.score.final_score??'N/A'} / 100. ${labels[1][i]}: ${view.final.score.final_score??'N/A'} / 100. ${labels[2][i]}: ${view.revision}. ${view.original.model_metadata.name}.`;}
function sourceCheckSummary(original){const check=original.contact_check;if(!check)return '';return `${ui('Проверка первого ответа')} #${check.observation.turn}: ${ui(check.observation.informal_greeting?'Неформальное приветствие RU/KZ':'Приветствие и представление проверены по источнику')}. ${ui('Исходное решение модели')}: ${valueLabel(check.model_judgment_before_check.value)}.`;}
refreshInterface();

$('data-dataset').onchange=run(async()=>{$('dataset').value=$('data-dataset').value;$('expected').value=$('dataset').value==='dev'?65:10;await loadConversations();});
$('dataset').addEventListener('change',()=>{$('data-dataset').value=$('dataset').value;});
