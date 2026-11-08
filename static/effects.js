// React Bits adaptations: David Haz, MIT + Commons Clause.
// Source revision and full license: /static/vendor/react-bits/ATTRIBUTION.md.

const motion=matchMedia('(prefers-reduced-motion: reduce)');
// Follow the OS until the user explicitly chooses play or pause in this app.
let motionMode='auto';try{const saved=localStorage.getItem('cqa-motion-mode');if(['auto','on','off'].includes(saved))motionMode=saved;else if(localStorage.getItem('cqa-effects-paused')==='true')motionMode='off';}catch(_){}
const reduced=()=>motionMode==='off'||(motionMode==='auto'&&motion.matches);
const dark=()=>document.documentElement.dataset.theme==='dark';
const clamp=(n,a,b)=>Math.max(a,Math.min(b,n));

// A controlled, read-only Comet Dial. Only updateScore can supply its target.
class ScoreComet {
 constructor(root){
  this.root=root;this.position=0;this.target=null;this.velocity=0;this.frame=0;this.last=0;
  const ns='http://www.w3.org/2000/svg';const make=(tag,attrs={})=>{const n=document.createElementNS(ns,tag);for(const [k,v]of Object.entries(attrs))n.setAttribute(k,v);return n;};
  this.svg=make('svg',{viewBox:'0 0 200 200',class:'comet-dial-svg','aria-hidden':'true'});
  this.track=make('path',{class:'comet-track',d:this.arc(110,430)});this.lit=make('path',{class:'comet-lit'});
  this.trails=Array.from({length:12},()=>make('path',{class:'comet-trail',opacity:0}));
  this.head=make('circle',{class:'comet-head',r:5.5});
  this.svg.append(this.track,this.lit,...this.trails,this.head);root.prepend(this.svg);root.classList.add('comet-dial');
  this.targetChanged=()=>{const label=document.getElementById('score-number').textContent.trim();let target=Number.parseFloat(label.replace(',','.'));if(!Number.isFinite(target))target=null;if(target!==this.target){this.target=target;if(target===null){this.stop();this.paint(0,0);}else if(reduced()){this.position=target;this.stop();this.paint(target,0);}else this.wake();}};
  this.observer=new MutationObserver(this.targetChanged);this.observer.observe(document.getElementById('score-number'),{childList:true,characterData:true,subtree:true});
  this.visibility=new IntersectionObserver(entries=>{this.visible=entries.some(e=>e.isIntersecting);if(this.visible&&this.target!==null){if(reduced()){this.position=this.target;this.paint(this.target,0);}else this.wake();}else this.stop();});this.visibility.observe(root);
  root.addEventListener('pointerenter',()=>{if(this.target!==null&&!reduced()){this.position=Math.max(0,this.target-12);this.velocity=0;this.wake();}});
  this.targetChanged();
 }
 point(deg){const a=deg*Math.PI/180;return[100+Math.cos(a)*80,100+Math.sin(a)*80];}
 arc(a,b){const [x,y]=this.point(a),[x2,y2]=this.point(b);return`M ${x} ${y} A 80 80 0 ${b-a>180?1:0} 1 ${x2} ${y2}`;}
 paint(value,speed){
  const present=this.target!==null;const angle=110+clamp(value,0,100)*3.2;
  this.lit.setAttribute('d',present&&value>.01?this.arc(110,angle):'');
  const [x,y]=this.point(angle);this.head.setAttribute('cx',x);this.head.setAttribute('cy',y);this.head.style.opacity=present?'1':'0';
  const strength=clamp(Math.abs(speed)/400,0,1),segment=180*strength/12;
  this.trails.forEach((path,i)=>{const a=clamp(angle-(i+1)*segment,110,430),b=clamp(angle-i*segment,110,430),weight=1-i/12;path.setAttribute('d',b-a>.01?this.arc(a,b):'');path.setAttribute('stroke-width',3+12*weight*strength);path.setAttribute('opacity',strength*weight);});
 }
 wake(){if(this.frame||this.target===null||this.visible===false||document.hidden)return;this.last=performance.now();this.frame=requestAnimationFrame(this.tick.bind(this));}
 tick(now){this.frame=0;if(document.hidden||this.visible===false)return;const dt=Math.min(.025,(now-this.last)/1000);this.last=now;
  if(reduced()){this.position=this.target;this.velocity=0;}else{this.velocity+=(this.target-this.position)*250*dt;this.velocity*=Math.exp(-25*dt);this.position+=this.velocity*dt;}
  this.paint(this.position,this.velocity);
  if(!reduced()&&(Math.abs(this.position-this.target)>.02||Math.abs(this.velocity)>.05))this.frame=requestAnimationFrame(this.tick.bind(this));else{this.position=this.target;this.velocity=0;this.paint(this.target,0);}
 }
 stop(){cancelAnimationFrame(this.frame);this.frame=0;}
 settle(){this.stop();if(this.target!==null){this.position=this.target;this.paint(this.target,0);}}
}

// Original Color Bends shader, driven by a small native WebGL fullscreen triangle.
async function colorBends(host){
 const canvas=host.querySelector('canvas');let gl;
 try{gl=canvas.getContext('webgl',{alpha:false,antialias:false,depth:false,powerPreference:'low-power',preserveDrawingBuffer:false});}catch(_){}
 if(!gl){host.dataset.renderer='fallback';return{refresh(){},pause(){},frames:0};}
 const source=await fetch('/static/vendor/react-bits/color-bends.frag').then(r=>{if(!r.ok)throw Error('Color Bends shader unavailable');return r.text();});
 const compile=(type,text)=>{const shader=gl.createShader(type);gl.shaderSource(shader,text);gl.compileShader(shader);if(!gl.getShaderParameter(shader,gl.COMPILE_STATUS))throw Error(gl.getShaderInfoLog(shader));return shader;};
 const vertex=compile(gl.VERTEX_SHADER,'attribute vec2 aPosition; varying vec2 vUv; void main(){vUv=aPosition*.5+.5;gl_Position=vec4(aPosition,0.,1.);}');
 const fragment=compile(gl.FRAGMENT_SHADER,source);const program=gl.createProgram();gl.attachShader(program,vertex);gl.attachShader(program,fragment);gl.linkProgram(program);
 if(!gl.getProgramParameter(program,gl.LINK_STATUS))throw Error(gl.getProgramInfoLog(program));
 gl.deleteShader(vertex);gl.deleteShader(fragment);gl.useProgram(program);
 const buffer=gl.createBuffer();gl.bindBuffer(gl.ARRAY_BUFFER,buffer);gl.bufferData(gl.ARRAY_BUFFER,new Float32Array([-1,-1,3,-1,-1,3]),gl.STATIC_DRAW);
 const attr=gl.getAttribLocation(program,'aPosition');gl.enableVertexAttribArray(attr);gl.vertexAttribPointer(attr,2,gl.FLOAT,false,0,0);
 const u=name=>gl.getUniformLocation(program,name);
 const uniforms=Object.fromEntries(['uCanvas','uTime','uSpeed','uRot','uColorCount','uColors[0]','uTransparent','uScale','uFrequency','uWarpStrength','uPointer','uMouseInfluence','uParallax','uNoise','uIterations','uIntensity','uBandWidth','uLight'].map(n=>[n,u(n)]));
 const one=(name,v)=>gl.uniform1f(uniforms[name],v);const integer=(name,v)=>gl.uniform1i(uniforms[name],v);
 one('uSpeed',.16);one('uScale',1.05);one('uFrequency',1.1);one('uWarpStrength',1);one('uMouseInfluence',.35);one('uParallax',.28);one('uNoise',.035);one('uIntensity',1.15);one('uBandWidth',5.5);
 integer('uIterations',2);integer('uTransparent',0);integer('uColorCount',3);
 const palette=new Float32Array(24);['19b718','0f5431','51af3d'].forEach((hex,i)=>{palette.set([parseInt(hex.slice(0,2),16)/255,parseInt(hex.slice(2,4),16)/255,parseInt(hex.slice(4,6),16)/255],i*3);});gl.uniform3fv(uniforms['uColors[0]'],palette);
 let raf=0,last=0,time=0,frames=0,px=0,py=0,tx=0,ty=0;let valid=true;
 function resize(){if(innerWidth<200||innerHeight<200)return;const scale=Math.min(1.25,devicePixelRatio||1,1600/innerWidth,1100/innerHeight);canvas.width=Math.round(innerWidth*scale);canvas.height=Math.round(innerHeight*scale);gl.viewport(0,0,canvas.width,canvas.height);gl.uniform2f(uniforms.uCanvas,canvas.width,canvas.height);draw();}
 function draw(){if(!valid)return;gl.useProgram(program);integer('uLight',dark()?0:1);one('uTime',time);const angle=(70+Math.sin(time*.08)*12)*Math.PI/180;gl.uniform2f(uniforms.uRot,Math.cos(angle),Math.sin(angle));gl.uniform2f(uniforms.uPointer,px,py);gl.drawArrays(gl.TRIANGLES,0,3);frames++;}
 function loop(now){raf=0;if(reduced()||document.hidden||!valid)return;const dt=last?Math.min(.08,(now-last)/1000):.033;if(!last||now-last>=32){last=now;time+=dt;px+=(tx-px)*.12;py+=(ty-py)*.12;draw();}raf=requestAnimationFrame(loop);}
 function refresh(){cancelAnimationFrame(raf);raf=0;last=0;draw();if(!reduced()&&!document.hidden&&valid)raf=requestAnimationFrame(loop);}
 host.dataset.renderer='webgl';resize();refresh();
 document.addEventListener('pointermove',e=>{if(reduced())return;tx=e.clientX/innerWidth*2-1;ty=1-e.clientY/innerHeight*2;},{passive:true});
 let resizeFrame;addEventListener('resize',()=>{cancelAnimationFrame(resizeFrame);resizeFrame=requestAnimationFrame(resize);});
 canvas.addEventListener('webglcontextlost',e=>{e.preventDefault();valid=false;cancelAnimationFrame(raf);host.dataset.renderer='fallback';});
 return{refresh,pause(){cancelAnimationFrame(raf);raf=0;},get frames(){return frames;}};
}

const pauseCopy=['Пауза анимации','Pause animation','Анимацияны тоқтату'];const resumeCopy=['Включить анимацию','Resume animation','Анимацияны қосу'];
for(const row of [pauseCopy,resumeCopy])for(const item of row)window.UI_LOOKUP?.set?.(item,row);
// i18n.js uses a global lexical Map, not a window property.
if(typeof UI_LOOKUP!=='undefined')for(const row of [pauseCopy,resumeCopy])for(const item of row)UI_LOOKUP.set(item,row);
const dial=new ScoreComet(document.getElementById('score-ring'));
let background={refresh(){},pause(){},frames:0};
const host=document.getElementById('freedom-background');
const motionControls=[...document.querySelectorAll('[data-effects-toggle]')];
function refresh(){
 const paused=reduced();document.body.dataset.effectsPaused=String(paused);document.body.dataset.motionMode=motionMode;
 for(const control of motionControls){control.textContent=typeof ui==='function'?ui(paused?resumeCopy[0]:pauseCopy[0]):paused?resumeCopy[1]:pauseCopy[1];control.setAttribute('aria-pressed',String(!paused));}
 background.refresh();if(paused)dial.settle();
}
function setMotion(mode){motionMode=mode;try{localStorage.setItem('cqa-motion-mode',mode);localStorage.removeItem('cqa-effects-paused');}catch(_){}refresh();}
for(const control of motionControls)control.addEventListener('click',()=>setMotion(reduced()?'on':'off'));
motion.addEventListener('change',refresh);
// Keep renderers in sync when a host changes its preference without a media event.
// This idle check never renders a frame while the state is unchanged.
function reconcileMotion(){if(document.body.dataset.effectsPaused!==String(reduced()))refresh();}
setInterval(()=>{if(!document.hidden)reconcileMotion();},1000);
document.addEventListener('visibilitychange',()=>{if(document.hidden){background.pause();dial.stop();}else{reconcileMotion();background.refresh();dial.wake();}});
new MutationObserver(()=>{background.refresh();}).observe(document.documentElement,{attributes:true,attributeFilter:['data-theme']});
try{background=await colorBends(host);}catch(error){host.dataset.renderer='fallback';console.warn('Color Bends fallback:',error.message);}
refresh();
window.CQAEffects={getState:()=>({background:host.dataset.renderer,backgroundFrames:background.frames,logo:'removed',paused:reduced(),motionMode,systemReducedMotion:motion.matches,dialTarget:dial.target}),pause:()=>setMotion('off'),followSystem:()=>setMotion('auto')};
