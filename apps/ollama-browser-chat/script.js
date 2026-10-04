'use strict';

// <pure>
function escapeHtml(s){
  return String(s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;');
}

function inline(s){
  const codes = [];
  s = s.replace(/`([^`]+)`/g, function(m, c){ codes.push(c); return '\u0001' + (codes.length - 1) + '\u0001'; });
  s = escapeHtml(s);
  s = s.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  s = s.replace(/~~([^~\s](?:[^~\n]*[^~\s])?)~~/g, '<del>$1</del>');
  s = s.replace(/(^|[^*\w])\*([^*\s][^*]*?)\*(?!\*)/g, '$1<em>$2</em>');
  s = s.replace(/\[([^\]]+)\]\((https?:\/\/[^\s)]+)\)/g, '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>');
  s = s.replace(/\u0001(\d+)\u0001/g, function(m, i){ return '<code>' + escapeHtml(codes[+i]) + '</code>'; });
  return s;
}

function splitRow(line){
  let t = line.trim();
  if(t.charAt(0) === '|') t = t.slice(1);
  const cells = [];
  let cur = '';
  for(let i = 0; i < t.length; i++){
    const ch = t.charAt(i);
    if(ch === '\\' && t.charAt(i + 1) === '|'){ cur += '|'; i++; }
    else if(ch === '|'){ cells.push(cur.trim()); cur = ''; }
    else cur += ch;
  }
  if(cur.trim() !== '' || !cells.length) cells.push(cur.trim());
  return cells;
}

function isTableSep(l){
  return l.indexOf('|') >= 0 && /^\s*\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)*\|?\s*$/.test(l);
}

function alignOf(c){
  c = c.trim();
  const l = c.charAt(0) === ':', r = c.charAt(c.length - 1) === ':';
  return l && r ? 'center' : r ? 'right' : '';
}

function tableHtml(head, aligns, rows){
  const n = head.length;
  const cell = function(tag, txt, i){
    return '<' + tag + (aligns[i] ? ' style="text-align:' + aligns[i] + '"' : '') + '>' + inline(txt || '') + '</' + tag + '>';
  };
  let h = '<div class="tablewrap"><table><thead><tr>' + head.map(function(c, i){ return cell('th', c, i); }).join('') + '</tr></thead>';
  if(rows.length){
    h += '<tbody>' + rows.map(function(r){
      const cs = [];
      for(let i = 0; i < n; i++) cs.push(cell('td', r[i], i));
      return '<tr>' + cs.join('') + '</tr>';
    }).join('') + '</tbody>';
  }
  return h + '</table></div>';
}

const HL_KW = {
  js: 'async await break case catch class const continue default delete do else export extends finally for from function if import in instanceof let new null of return static super switch this throw true false try typeof undefined var void while yield',
  py: 'and as assert async await break class continue def del elif else except False finally for from global if import in is lambda None nonlocal not or pass raise return True try while with yield self',
  sh: 'if then else elif fi for while do done case esac function in echo export local return cd ls sudo',
  c: 'auto bool break case char class const continue default do double else enum extern false float for goto if inline int long namespace new nullptr private protected public register return short signed sizeof static struct switch template this throw true try typedef union unsigned using virtual void volatile while fn let mut impl pub use mod match self trait func package import interface type var go defer range map string byte',
  sql: 'select from where and or not insert into values update set delete create table drop alter join left right inner outer on group by order having limit as null is in like distinct union primary key foreign references index'
};
const HL_FAM = {
  js: { kw: 'js', line: '\\/\\/', block: 1, tpl: 1 },
  py: { kw: 'py', line: '#', triple: 1 },
  sh: { kw: 'sh', line: '#' },
  c: { kw: 'c', line: '\\/\\/', block: 1 },
  sql: { kw: 'sql', line: '--', block: 1, ci: 1 },
  css: { block: 1, css: 1 },
  markup: { markup: 1 }
};
const HL_ALIAS = {
  js: 'js', javascript: 'js', jsx: 'js', ts: 'js', typescript: 'js', tsx: 'js', json: 'js', mjs: 'js',
  py: 'py', python: 'py',
  sh: 'sh', bash: 'sh', shell: 'sh', zsh: 'sh',
  c: 'c', cpp: 'c', 'c++': 'c', java: 'c', cs: 'c', csharp: 'c', go: 'c', rust: 'c', rs: 'c', kotlin: 'c', swift: 'c', php: 'c',
  sql: 'sql', css: 'css', html: 'markup', xml: 'markup', svg: 'markup'
};
const hlCache = {};

function hlBuild(fam){
  if(hlCache[fam]) return hlCache[fam];
  const f = HL_FAM[fam], parts = [];
  if(f.block) parts.push(['c', '\\/\\*[\\s\\S]*?(?:\\*\\/|$)']);
  if(f.line) parts.push(['c', f.line + '[^\\n]*']);
  if(f.markup){ parts.push(['c', '<!--[\\s\\S]*?(?:-->|$)']); parts.push(['k', '<\\/?[A-Za-z][\\w:-]*']); }
  if(f.tpl) parts.push(['s', '`(?:\\\\[\\s\\S]|[^`\\\\])*`?']);
  if(f.triple){ parts.push(['s', '"""[\\s\\S]*?(?:"""|$)']); parts.push(['s', "'''[\\s\\S]*?(?:'''|$)"]); }
  parts.push(['s', '"(?:\\\\.|[^"\\\\\\n])*"?']);
  if(!f.markup) parts.push(['s', "'(?:\\\\.|[^'\\\\\\n])*'?"]);
  if(f.css){ parts.push(['k', '@[\\w-]+']); parts.push(['n', '#[0-9a-fA-F]{3,8}\\b']); }
  parts.push(['n', '\\b(?:0x[0-9a-fA-F]+|\\d+(?:\\.\\d+)?)\\b']);
  parts.push(['i', '[A-Za-z_$][\\w$]*']);
  const re = new RegExp(parts.map(function(p){ return '(' + p[1] + ')'; }).join('|'), 'g');
  const kws = {};
  if(f.kw) HL_KW[f.kw].split(' ').forEach(function(w){ kws[w] = 1; });
  return (hlCache[fam] = { re: re, types: parts.map(function(p){ return p[0]; }), kws: kws, ci: !!f.ci });
}

function highlight(code, lang){
  const fam = HL_ALIAS[String(lang || '').toLowerCase().trim()];
  if(!fam) return escapeHtml(code);
  const h = hlBuild(fam);
  h.re.lastIndex = 0;
  let out = '', last = 0, m;
  while((m = h.re.exec(code)) !== null){
    if(m[0] === ''){ h.re.lastIndex++; continue; }
    let t = '';
    for(let k = 0; k < h.types.length; k++){ if(m[k + 1] !== undefined){ t = h.types[k]; break; } }
    out += escapeHtml(code.slice(last, m.index));
    last = m.index + m[0].length;
    if(t === 'i') t = h.kws[h.ci ? m[0].toLowerCase() : m[0]] ? 'k' : '';
    out += t ? '<span class="tk-' + t + '">' + escapeHtml(m[0]) + '</span>' : escapeHtml(m[0]);
  }
  return out + escapeHtml(code.slice(last));
}

function renderBlocks(text){
  const lines = text.split('\n');
  let out = '', para = [], list = null;
  const flushP = function(){ if(para.length){ out += '<p>' + para.map(inline).join('<br>') + '</p>'; para = []; } };
  const flushL = function(){ if(list){ out += '</' + list + '>'; list = null; } };
  for(let li = 0; li < lines.length; li++){
    const line = lines[li];
    let m;
    if(!line.trim()){ flushP(); flushL(); continue; }
    if(line.indexOf('|') >= 0 && li + 1 < lines.length && isTableSep(lines[li + 1]) && splitRow(line).length === splitRow(lines[li + 1]).length){
      flushP(); flushL();
      const head = splitRow(line), aligns = splitRow(lines[li + 1]).map(alignOf), rows = [];
      li += 2;
      while(li < lines.length && lines[li].trim() && lines[li].indexOf('|') >= 0){ rows.push(splitRow(lines[li])); li++; }
      li--;
      out += tableHtml(head, aligns, rows);
      continue;
    }
    if((m = line.match(/^(#{1,4})\s+(.*)$/))){ flushP(); flushL(); const n = m[1].length + 1; out += '<h' + n + '>' + inline(m[2]) + '</h' + n + '>'; continue; }
    if((m = line.match(/^\s*[-*]\s+(.*)$/))){ flushP(); if(list !== 'ul'){ flushL(); out += '<ul>'; list = 'ul'; } out += '<li>' + inline(m[1]) + '</li>'; continue; }
    if((m = line.match(/^\s*\d+[.)]\s+(.*)$/))){ flushP(); if(list !== 'ol'){ flushL(); out += '<ol>'; list = 'ol'; } out += '<li>' + inline(m[1]) + '</li>'; continue; }
    if((m = line.match(/^>\s?(.*)$/))){ flushP(); flushL(); out += '<blockquote>' + inline(m[1]) + '</blockquote>'; continue; }
    flushL(); para.push(line);
  }
  flushP(); flushL();
  return out;
}

function renderMarkdown(src){
  const parts = String(src).split(/(```[\s\S]*?(?:```|$))/g);
  let html = '';
  for(const part of parts){
    if(part.startsWith('```')){
      const m = part.match(/^```([^\n]*)\n?([\s\S]*?)(?:```)?$/);
      const lang = (m[1] || '').trim();
      const code = (m[2] || '').replace(/\n$/, '');
      html += '<div class="code"><div class="code-head"><span>' + escapeHtml(lang || 'Code') + '</span><span class="cb"><button type="button" class="copy" data-art>Artefakt</button><button type="button" class="copy" data-copy>Kopieren</button></span></div><pre><code>' + highlight(code, lang) + '</code></pre></div>';
    } else {
      html += renderBlocks(part);
    }
  }
  return html;
}

function createNdjsonParser(onObj){
  let buf = '';
  const emit = function(line){
    line = line.trim();
    if(!line) return;
    let o;
    try { o = JSON.parse(line); } catch(e){ return; }
    onObj(o);
  };
  return {
    push: function(chunk){
      buf += chunk;
      let i;
      while((i = buf.indexOf('\n')) >= 0){
        const line = buf.slice(0, i);
        buf = buf.slice(i + 1);
        emit(line);
      }
    },
    end: function(){ const rest = buf; buf = ''; emit(rest); }
  };
}

function normalizeUrl(u){
  u = String(u || '').trim();
  if(!u) return '';
  if(!/^https?:\/\//i.test(u)) u = 'http://' + u;
  return u.replace(/\/+$/, '');
}
function chatToMarkdown(chat){
  let s = '# ' + (chat.title || 'Chat') + '\n\n';
  chat.messages.forEach(function(m){
    s += '## ' + (m.role === 'user' ? 'Du' : 'Modell') + '\n\n' + (m.imgN ? '[' + m.imgN + ' Bild(er)]\n\n' : '') + (m.content || '') + '\n\n';
  });
  return s.trim() + '\n';
}

function stripImages(k, v){ return k === 'images' ? undefined : v; }

function chatsToJson(chats){
  return JSON.stringify({ app: 'ollama-mobile-chat', version: 1, chats: chats }, stripImages, 2);
}

function holdPartial(s, tag){
  for(let n = Math.min(tag.length - 1, s.length); n > 0; n--){
    if(tag.startsWith(s.slice(-n))) return s.slice(0, -n);
  }
  return s;
}

function splitThink(raw){
  const OPEN = '<think>', CLOSE = '</think>';
  raw = String(raw);
  const body = raw.replace(/^\s+/, '');
  if(body.startsWith(OPEN)){
    const rest = body.slice(OPEN.length);
    const end = rest.indexOf(CLOSE);
    if(end < 0) return { thinking: holdPartial(rest, CLOSE), content: '' };
    return { thinking: rest.slice(0, end).trim(), content: rest.slice(end + CLOSE.length).replace(/^\s+/, '') };
  }
  if(body && OPEN.startsWith(body)) return { thinking: '', content: '' };
  return { thinking: '', content: raw };
}

function filterChats(chats, q){
  q = String(q || '').trim().toLowerCase();
  const sorted = chats.slice().sort(function(a, b){ return b.ts - a.ts; });
  if(!q) return sorted;
  return sorted.filter(function(c){
    if(String(c.title).toLowerCase().indexOf(q) >= 0) return true;
    return c.messages.some(function(m){ return String(m.content || '').toLowerCase().indexOf(q) >= 0; });
  });
}

function cleanTitle(t){
  t = String(t == null ? '' : t).replace(/\s+/g, ' ').trim().slice(0, 80);
  return t || null;
}

function clampNum(v, lo, hi, def){
  v = parseFloat(v);
  if(!isFinite(v)) return def;
  return Math.min(hi, Math.max(lo, v));
}

function buildOptions(st){
  const o = {
    temperature: clampNum(st.temperature, 0, 2, 0.7),
    top_p: clampNum(st.topP, 0, 1, 0.9),
    repeat_penalty: clampNum(st.repeatPenalty, 0.5, 2, 1.1)
  };
  const n = parseInt(st.numCtx, 10);
  if(n > 0) o.num_ctx = Math.min(n, 262144);
  return o;
}

function buildMessages(system, messages){
  const out = [];
  if(system && system.trim()) out.push({ role: 'system', content: system.trim() });
  messages.forEach(function(m){
    if(!m.content && !(m.images && m.images.length)) return;
    const o = { role: m.role, content: m.content || '' };
    if(m.role === 'user' && m.images && m.images.length) o.images = m.images.slice();
    out.push(o);
  });
  return out;
}

function parseImport(text){
  let o;
  try { o = JSON.parse(text); } catch(e){ throw new Error('Die Datei ist kein gültiges JSON.'); }
  const list = Array.isArray(o) ? o : (o && Array.isArray(o.chats) ? o.chats : null);
  if(!list) throw new Error('Keine Chats in der Datei gefunden.');
  const out = [];
  list.forEach(function(c){
    if(!c || !Array.isArray(c.messages)) return;
    const msgs = [];
    c.messages.forEach(function(m){
      if(!m || (m.role !== 'user' && m.role !== 'assistant') || typeof m.content !== 'string') return;
      const r = { role: m.role, content: m.content };
      if(m.role === 'user' && Number(m.imgN) > 0) r.imgN = Math.min(Number(m.imgN), 9) | 0;
      if(m.role === 'assistant' && typeof m.thinking === 'string' && m.thinking) r.thinking = m.thinking;
      msgs.push(r);
    });
    if(!msgs.length) return;
    out.push({ title: String(c.title || 'Importierter Chat').slice(0, 80), ts: Number(c.ts) || Date.now(), messages: msgs });
  });
  if(!out.length) throw new Error('Keine gültigen Chats in der Datei gefunden.');
  return out;
}

function isVisionModelName(name){
  return /vision|llava|bakllava|moondream|pixtral|minicpm-v|internvl|cogvlm|paligemma|florence|qwen.?-?\d*-?vl\b|-vl:/i.test(String(name || ''));
}

function isVisionModelFamilies(families){
  const known = ['clip', 'mllama', 'vision', 'qwen2vl', 'qwenvl'];
  return Array.isArray(families) && families.some(function(f){ return known.indexOf(String(f).toLowerCase()) >= 0; });
}

function isVisionCapable(name, families){
  return isVisionModelFamilies(families) || isVisionModelName(name);
}

function isCoderModelName(name){
  return /coder|code-|codellama|starcoder|codegemma|codestral|codeqwen|deepseek-coder|granite-code|stable-code|magicoder|wizardcoder/i.test(String(name || ''));
}

// Bestes installiertes Modell für einen Bedarf ('vision'|'coder') aus der Namensliste waehlen.
// info: Map name -> { families }. current: aktuell gewaehltes Modell (wird bevorzugt uebersprungen,
// wenn es den Bedarf schon erfuellt). Gibt null zurueck, wenn kein Wechsel noetig/moeglich ist.
function pickModelFor(need, names, info, current){
  if(!need) return null;
  const fits = function(n){
    if(need === 'vision') return isVisionCapable(n, info && info[n] && info[n].families);
    if(need === 'coder') return isCoderModelName(n);
    return false;
  };
  if(current && fits(current)) return null;
  const list = (names || []).filter(fits);
  return list.length ? list[0] : null;
}

function fitViewport(vv, innerH){
  if(!vv) return null;
  const h = Number(vv.height);
  if(!isFinite(h) || h <= 0) return null;
  if(Math.abs((Number(vv.scale) || 1) - 1) > 0.01) return null;
  const height = Math.round(h);
  const top = Math.max(0, Math.round(Number(vv.offsetTop) || 0));
  const ih = Number(innerH) > 0 ? Number(innerH) : height;
  return { height: height, top: top, bottom: Math.max(0, Math.round(ih - height - top)), keyboard: ih - height > 120 };
}
const ART_EXT = { javascript: 'js', js: 'js', typescript: 'ts', ts: 'ts', python: 'py', py: 'py', html: 'html', css: 'css', json: 'json', bash: 'sh', sh: 'sh', markdown: 'md', md: 'md', sql: 'sql', java: 'java', c: 'c', cpp: 'cpp', go: 'go', rust: 'rs', php: 'php' };

function artifactExt(lang){ return ART_EXT[String(lang || '').toLowerCase().trim()] || 'txt'; }

function artifactTitle(code, lang){
  const first = String(code || '').split('\n').map(function(s){ return s.trim(); }).filter(Boolean)[0] || 'Artefakt';
  return (lang ? String(lang).trim() + ': ' : '') + first.slice(0, 40);
}

function buildSystem(sys, project){
  const parts = [];
  if(sys && sys.trim()) parts.push(sys.trim());
  if(project && project.instructions && project.instructions.trim()) parts.push('Projekt "' + project.name + '":\n' + project.instructions.trim());
  return parts.join('\n\n');
}
function mergeDictation(base, spoken){
  base = String(base || '');
  spoken = String(spoken || '').replace(/\s+/g, ' ').trim();
  if(!spoken) return base;
  if(!base || /\s$/.test(base)) return base + spoken;
  return base + ' ' + spoken;
}

function dictationSupport(win, secure){
  const Ctor = win && (win.SpeechRecognition || win.webkitSpeechRecognition);
  if(!Ctor) return { ok: false, Ctor: null, reason: 'Dieser Browser bietet keine Spracherkennung (Firefox kann das nicht). Nutze Chrome, Edge oder Safari, oder das Mikrofon deiner Bildschirmtastatur.' };
  if(!secure) return { ok: false, Ctor: null, reason: 'Diktieren braucht eine sichere Adresse (https:// oder localhost). Über http://<IP> sperrt der Browser das Mikrofon. Starte im Mini Webserver HTTPS und öffne die Seite über https://<IP>:<Port>.' };
  return { ok: true, Ctor: Ctor, reason: '' };
}

function dictationErrorText(code){
  const m = {
    'not-allowed': 'Mikrofon-Zugriff verweigert. Erlaube ihn in den Browser- oder Systemeinstellungen.',
    'service-not-allowed': 'Spracherkennung auf diesem Gerät nicht erlaubt (iPhone: Diktierfunktion in den Einstellungen aktivieren).',
    'audio-capture': 'Kein Mikrofon gefunden.',
    'network': 'Die Spracherkennung braucht Internet, der Browser sendet das Audio an seinen Anbieter.',
    'language-not-supported': 'Diese Diktier-Sprache wird nicht unterstützt.',
    'no-speech': 'Nichts gehört. Sprich näher am Mikrofon.',
    'aborted': ''
  };
  return Object.prototype.hasOwnProperty.call(m, code) ? m[code] : 'Diktieren fehlgeschlagen (' + code + ').';
}

function dictationLang(setting, navLang){
  const s = String(setting || '');
  return s && s !== 'auto' ? s : (navLang || 'de-DE');
}
/* ---------- 7-Segment-Anzeige fuer den Token-Verbrauch ---------- */
const SEG_PATHS = {
  a: 'M3.5 2L5.5 0H14.5L16.5 2L14.5 4H5.5Z',
  b: 'M18 3.5L20 5.5V14.5L18 16.5L16 14.5V5.5Z',
  c: 'M18 18.5L20 20.5V29.5L18 31.5L16 29.5V20.5Z',
  d: 'M3.5 32L5.5 30H14.5L16.5 32L14.5 34H5.5Z',
  e: 'M2 18.5L4 20.5V29.5L2 31.5L0 29.5V20.5Z',
  f: 'M2 3.5L4 5.5V14.5L2 16.5L0 14.5V5.5Z',
  g: 'M3.5 17L5.5 15H14.5L16.5 17L14.5 19H5.5Z'
};
const SEG_MAP = { '0': 'abcdef', '1': 'bc', '2': 'abdeg', '3': 'abcdg', '4': 'bcfg', '5': 'acdfg', '6': 'acdefg', '7': 'abc', '8': 'abcdefg', '9': 'abcdfg', '-': 'g', ' ': '' };

function segDigit(ch){
  const on = Object.prototype.hasOwnProperty.call(SEG_MAP, ch) ? SEG_MAP[ch] : '';
  let h = '<svg viewBox="0 0 24 34" aria-hidden="true"><g transform="translate(3.6 0) skewX(-6)">';
  'abcdefg'.split('').forEach(function(k){
    h += '<path class="s' + (on.indexOf(k) >= 0 ? ' on' : '') + '" d="' + SEG_PATHS[k] + '"/>';
  });
  return h + '</g></svg>';
}

function nonNeg(v){
  const n = Math.floor(Number(v));
  return isFinite(n) && n > 0 ? n : 0;
}

// Zahl auf feste Stellenzahl bringen: links mit Leerzeichen aufgefuellt, zu grosse Werte werden gekappt.
function formatTokens(n, digits){
  const max = Math.pow(10, digits) - 1;
  const s = String(Math.min(nonNeg(n), max));
  return new Array(Math.max(0, digits - s.length) + 1).join(' ') + s;
}

function sevenSegHtml(n, digits){
  return formatTokens(n, digits).split('').map(segDigit).join('');
}

// Verbrauch eines Chats fortschreiben. `o` ist die letzte Zeile der Ollama-Antwort
// (prompt_eval_count = Tokens der Anfrage, eval_count = Tokens der Antwort).
function addUsage(tok, o){
  const t = tok || {}, u = o || {};
  const inTok = u.prompt_eval_count == null ? nonNeg(t.in) : nonNeg(u.prompt_eval_count);
  const outTok = nonNeg(u.eval_count);
  return { in: inTok, out: outTok, sum: nonNeg(t.sum) + (u.prompt_eval_count == null ? 0 : inTok) + outTok };
}

// Was die Anzeige zeigt. Waehrend des Streamens (liveOut gesetzt) zaehlt die Antwort live mit.
function tokensView(tok, liveOut){
  const t = tok || {};
  if(liveOut == null) return { in: nonNeg(t.in), out: nonNeg(t.out), sum: nonNeg(t.sum) };
  return { in: nonNeg(t.in), out: nonNeg(liveOut), sum: nonNeg(t.sum) + nonNeg(liveOut) };
}

function tokensAria(v){
  return 'Token-Verbrauch: Anfrage ' + v.in + ', Antwort ' + v.out + ', Summe im Chat ' + v.sum + '.';
}
// Wie voll ist das Kontextfenster? Ollama schneidet bei Ueberlauf den aeltesten Teil des Gespraechs ab.
// Dann verliert das Modell den Bezug zu frueheren Nachrichten (es wiederholt oder antwortet an der Frage vorbei).
function contextState(tok, limit){
  const t = tok || {}, ctx = nonNeg(limit);
  const used = nonNeg(t.in) + nonNeg(t.out);
  if(!ctx || !used) return { level: 'unknown', ctx: ctx, used: used, pct: 0 };
  const pct = Math.round(used / ctx * 100);
  const full = nonNeg(t.in) >= ctx * 0.97 || used >= ctx;
  return { level: full ? 'full' : (pct >= 85 ? 'warn' : 'ok'), ctx: ctx, used: used, pct: pct };
}
// </pure>

(function(){
  const $ = function(id){ return document.getElementById(id); };
  const LS_KEY = 'ollamaMobile.v1';
  const ICON_SEND = '<svg viewBox="0 0 24 24"><path d="M12 19V5M5 12l7-7 7 7"/></svg>';
  const ICON_STOP = '<svg viewBox="0 0 24 24"><rect x="6" y="6" width="12" height="12" rx="2"/></svg>';

  function defaultUrl(){
    // Per https:// geladen: Ollama ist ueber den Mini Webserver unter /api erreichbar (gleiche Adresse wie die Seite).
    if(location.protocol === 'https:' && location.host) return location.origin;
    if(location.protocol === 'http:' && location.hostname) return 'http://' + location.hostname + ':11434';
    return 'http://192.168.0.10:11434';
  }

  function loadState(){
    const base = { url: defaultUrl(), model: '', system: '', temperature: 0.7, topP: 0.9, repeatPenalty: 1.1, numCtx: 0, chats: [], current: null, projects: [], artifacts: [], project: '', dictLang: 'auto' };
    try {
      const raw = localStorage.getItem(LS_KEY);
      if(raw) return Object.assign(base, JSON.parse(raw));
    } catch(e){}
    return base;
  }

  let state = loadState();
  let models = [];
  let modelInfo = {};   // name -> { families: string[] } aus /api/tags (fuer Bild-Erkennung)
  let status = 'wait';
  let connError = '';
  let busy = false;
  let abortCtl = null;
  let saveTimer = null;
  let rafPending = false;
  let tokLive = null;    // waehrend des Streamens: bisher gezaehlte Antwort-Tokens, sonst null
  let tokRaf = false;
  const tokCache = {};
  let ctxLimit = 0;          // wirksames Kontextfenster (aus den Einstellungen oder von Ollama /api/ps), 0 = unbekannt
  const ctxShown = {};       // pro Chat: zuletzt gemeldete Warnstufe
  let pending = [];
  let chatQuery = '';
  const MAX_ATTACH = 4;       // Bilder + Dateien zusammen
  const MAX_FILE_CHARS = 60000; // Zeichen pro Textdatei, danach wird gekuerzt
  const TEXT_EXT = /\.(txt|md|markdown|csv|tsv|log|json|jsonl|ya?ml|xml|ini|toml|conf|cfg|env|js|mjs|cjs|ts|tsx|jsx|py|java|c|h|cpp|hpp|cc|cs|go|rs|rb|php|sql|sh|bash|zsh|ps1|css|scss|html|htm|svg|vue|kt|swift|lua|pl|r|dart)$/i;

  function save(){
    try { localStorage.setItem(LS_KEY, JSON.stringify(state, stripImages)); } catch(e){}
  }
  function saveSoon(){
    clearTimeout(saveTimer);
    saveTimer = setTimeout(save, 400);
  }

  function toast(msg){
    const t = $('toast');
    t.textContent = msg;
    t.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(function(){ t.classList.remove('show'); }, 2200);
  }

  async function copyText(text){
    try {
      if(navigator.clipboard && window.isSecureContext){ await navigator.clipboard.writeText(text); return true; }
    } catch(e){}
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.cssText = 'position:fixed;opacity:0;top:0;left:0';
    document.body.appendChild(ta);
    ta.focus(); ta.select();
    let ok = false;
    try { ok = document.execCommand('copy'); } catch(e){}
    ta.remove();
    return ok;
  }

  /* ---------- Chats ---------- */
  function uid(){ return Date.now().toString(36) + Math.random().toString(36).slice(2, 7); }
  function currentChat(){ return state.chats.find(function(c){ return c.id === state.current; }) || null; }
  function newChat(){
    const c = { id: uid(), title: 'Neuer Chat', ts: Date.now(), messages: [], projectId: state.project || '' };
    state.chats.unshift(c);
    state.current = c.id;
    save();
    return c;
  }

  /* ---------- Rendering ---------- */
  function friendlyError(e){
    const url = state.url;
    if(e && e.name === 'AbortError') return 'Zeitüberschreitung bei ' + url + '.';
    if(e instanceof TypeError){
      let s = 'Keine Verbindung zu ' + url + '.\nPrüfe: Ollama läuft, Handy und Rechner sind im selben WLAN, die Adresse stimmt.';
      if(location.protocol === 'https:' && /^http:/i.test(url)) s += '\nDiese Seite wurde per HTTPS geladen und darf keine unverschlüsselte http-Adresse aufrufen. Trage in den Einstellungen die Adresse dieser Seite ein (' + location.origin + '). Der Mini Webserver leitet dann an Ollama weiter.';
      else if(url === location.origin) s += '\nDer Mini Webserver ist nicht erreichbar. Läuft er noch, und stimmt die Adresse?';
      else s += '\nAuf dem Rechner müssen OLLAMA_HOST=0.0.0.0 und OLLAMA_ORIGINS=* gesetzt sein.';
      return s;
    }
    return (e && e.message) ? e.message : String(e);
  }

  function emptyHtml(){
    let h = '<div class="empty">';
    if(status === 'err'){
      h += '<h1>Ollama ist nicht erreichbar</h1><p style="white-space:pre-wrap">' + escapeHtml(connError) + '</p>' +
        '<pre>OLLAMA_HOST=0.0.0.0 OLLAMA_ORIGINS=* ollama serve</pre>' +
        '<div class="row"><button class="btn primary" data-act="reconnect">Erneut verbinden</button><button class="btn" data-act="settings">Adresse ändern</button></div>';
    } else if(status === 'empty'){
      h += '<h1>Kein Modell installiert</h1><p>Lade zuerst eines auf dem Rechner herunter, zum Beispiel:</p><pre>ollama pull llama3.2</pre>' +
        '<div class="row"><button class="btn primary" data-act="reconnect">Liste aktualisieren</button></div>';
    } else if(status === 'wait'){
      h += '<h1>Verbinde mit Ollama</h1><p>' + escapeHtml(state.url) + '</p>';
    } else {
      h += '<h1>Bereit</h1><p>Modell: ' + escapeHtml(state.model) + '. Schreib unten deine erste Nachricht.</p>';
    }
    return h + '</div>';
  }

  function msgHtml(m, i, chat){
    if(m.role === 'user'){
      let ih = '';
      if(m.images && m.images.length) ih = '<div class="imgs">' + m.images.map(function(b){ return '<img alt="Angehängtes Bild" src="data:image/jpeg;base64,' + escapeHtml(b) + '">'; }).join('') + '</div>';
      else if(m.imgN) ih = '<div class="imgs">\uD83D\uDDBC ' + (m.imgN | 0) + ' Bild(er), nicht mehr gespeichert</div>';
      return '<div class="msg user"><div class="bubble">' + ih + '<span class="txt">' + escapeHtml(m.content) + '</span></div></div>';
    }
    const isLast = i === chat.messages.length - 1;
    const live = isLast && busy;
    let h = '<div class="msg bot' + (live ? ' live' : '') + '">';
    if(m.thinking) h += '<details class="think"><summary>Gedankengang</summary><div>' + escapeHtml(m.thinking) + '</div></details>';
    if(m.content) h += live ? '<div class="body stream">' + escapeHtml(m.content) + '</div>' : '<div class="body">' + renderMarkdown(m.content) + '</div>';
    else if(!m.error && isLast && busy) h += '<div class="typing" aria-label="Das Modell antwortet"><i></i><i></i><i></i></div>';
    if(m.error) h += '<div class="err">' + escapeHtml(m.error) + '</div>';
    if(!(isLast && busy)){
      h += '<div class="acts">';
      if(m.content) h += '<button data-act="copy" data-i="' + i + '">Kopieren</button>';
      if(isLast) h += '<button data-act="regen">Neu generieren</button>';
      h += '</div>';
    }
    return h + '</div>';
  }

  function nearBottom(){
    const el = $('messages');
    return el.scrollHeight - el.scrollTop - el.clientHeight < 120;
  }
  function scrollDown(force){
    const el = $('messages');
    if(force || nearBottom()) el.scrollTop = el.scrollHeight;
  }

  function render(){
    const chat = currentChat();
    const box = $('messages');
    if(!chat || !chat.messages.length) box.innerHTML = emptyHtml();
    else box.innerHTML = chat.messages.map(function(m, i){ return msgHtml(m, i, chat); }).join('');
    scrollDown(true);
    renderChatList();
    paintTokens();
  }

  /* Token-Anzeige (7 Segmente). Wird beim Streamen pro Bild hoechstens einmal neu gezeichnet. */
  function paintTokens(){
    const chat = currentChat();
    const v = tokensView(chat && chat.tok, tokLive);
    [['tokIn', v.in, 6], ['tokOut', v.out, 6], ['tokSum', v.sum, 7]].forEach(function(x){
      const el = $(x[0]);
      const key = formatTokens(x[1], x[2]);
      if(!el || tokCache[x[0]] === key) return;
      tokCache[x[0]] = key;
      el.innerHTML = sevenSegHtml(x[1], x[2]);
    });
    const bar = $('tokbar');
    if(bar) bar.setAttribute('aria-label', tokensAria(v));
    const cs = contextState(chat && chat.tok, ctxLimit), grp = $('tokIn') && $('tokIn').parentNode;
    if(grp){
      grp.classList.toggle('warn', cs.level === 'warn');
      grp.classList.toggle('full', cs.level === 'full');
      grp.title = cs.ctx ? 'Kontext: ' + cs.used + ' von ' + cs.ctx + ' Tokens (' + cs.pct + ' %)' : 'Tokens der letzten Anfrage';
    }
  }

  // Kontextgroesse ermitteln: erst die Einstellung, sonst fragt die App Ollama, welches Fenster das geladene Modell hat.
  async function refreshCtxLimit(){
    const n = parseInt(state.numCtx, 10);
    if(n > 0){ ctxLimit = n; return; }
    ctxLimit = 0;
    try {
      const ctl = new AbortController(), timer = setTimeout(function(){ ctl.abort(); }, 3000);
      const res = await fetch(state.url + '/api/ps', { signal: ctl.signal });
      clearTimeout(timer);
      if(!res.ok) return;
      const j = await res.json();
      const m = (j.models || []).find(function(x){ return x.name === state.model || x.model === state.model; });
      const c = m ? parseInt(m.context_length, 10) : 0;
      if(c > 0) ctxLimit = c;
    } catch(e) { /* aeltere Ollama-Versionen kennen /api/ps nicht oder liefern kein context_length */ }
  }
  function checkContext(chat){
    paintTokens();
    const cs = contextState(chat.tok, ctxLimit);
    if(cs.level === 'unknown' || ctxShown[chat.id] === cs.level) return;
    ctxShown[chat.id] = cs.level;
    if(cs.level === 'full') toast('Kontextfenster voll (' + cs.used + ' von ' + cs.ctx + '). Ollama kappt den Verlauf, das Modell verliert den Bezug. Stelle in den Einstellungen ein größeres num_ctx ein, zum Beispiel 8192.');
    else if(cs.level === 'warn') toast('Kontextfenster zu ' + cs.pct + ' % gefüllt. Bald wird älterer Verlauf abgeschnitten.');
  }
  function updateTokens(){
    if(tokRaf) return;
    tokRaf = true;
    requestAnimationFrame(function(){ tokRaf = false; paintTokens(); });
  }

  /* Streaming: nur Text anhängen, Markdown erst am Ende (finishLive) */
  function textNodeOf(el){
    let n = el.firstChild;
    if(!n || n.nodeType !== 3){ n = document.createTextNode(''); el.textContent = ''; el.appendChild(n); }
    return n;
  }
  function syncText(el, next){
    const n = textNodeOf(el), prev = n.data;
    if(next.length >= prev.length && next.startsWith(prev)) n.appendData(next.slice(prev.length));
    else n.data = next;
  }
  function livePaint(el, m){
    if(m.thinking){
      let think = el.querySelector(':scope > details.think');
      if(!think){
        el.insertAdjacentHTML('afterbegin', '<details class="think"><summary>Gedankengang</summary><div></div></details>');
        think = el.firstElementChild;
      }
      syncText(think.querySelector('div'), m.thinking);
    }
    if(m.content){
      let body = el.querySelector(':scope > .body');
      if(!body){
        body = document.createElement('div');
        body.className = 'body stream';
        const typing = el.querySelector(':scope > .typing');
        if(typing) typing.replaceWith(body); else el.appendChild(body);
      }
      syncText(body, m.content);
    }
  }

  function updateLive(){
    if(rafPending) return;
    rafPending = true;
    requestAnimationFrame(function(){
      rafPending = false;
      if(!busy) return;
      const chat = currentChat();
      const last = $('messages').querySelector('.msg.live:last-child');
      if(!chat || !last) return;
      const stick = nearBottom();
      livePaint(last, chat.messages[chat.messages.length - 1]);
      if(stick) scrollDown(true);
    });
  }

  function finishLive(chat){
    const last = $('messages').querySelector('.msg.live:last-child');
    const i = chat.messages.length - 1;
    if(last && i >= 0 && chat.messages[i].role === 'assistant'){
      const stick = nearBottom();
      last.outerHTML = msgHtml(chat.messages[i], i, chat);
      if(stick) scrollDown(true);
      renderChatList();
    } else render();
  }

  /* ---------- Diktat (Web Speech API) ---------- */
  let rec = null, dictOn = false, dict = { base: '', fin: '' }, quick = 0, lastStart = 0;
  const FATAL = ['not-allowed', 'service-not-allowed', 'audio-capture', 'language-not-supported', 'network'];

  function setMic(on){
    const b = $('btnMic');
    b.classList.toggle('rec', on);
    b.setAttribute('aria-pressed', on ? 'true' : 'false');
    b.setAttribute('aria-label', on ? 'Diktat beenden' : 'Diktieren');
  }
  function paintDictation(interim){
    const el = $('input');
    el.value = mergeDictation(dict.base, dict.fin + (interim ? ' ' + interim : ''));
    autosize();
  }
  function beginRec(Ctor){
    const touch = !!(window.matchMedia && window.matchMedia('(pointer:coarse)').matches);
    const r = new Ctor();
    r.lang = dictationLang(state.dictLang, navigator.language);
    r.continuous = !touch;      // Touch-Geraete: Einzelphrasen mit Neustart (verhindert Doppeltext auf Android)
    r.interimResults = true;
    r.maxAlternatives = 1;
    r.onresult = function(e){
      let interim = '';
      for(let i = e.resultIndex; i < e.results.length; i++){
        const t = String(e.results[i][0].transcript || '');
        if(e.results[i].isFinal) dict.fin = (dict.fin ? dict.fin + ' ' : '') + t.trim();
        else interim += t;
      }
      paintDictation(interim.trim());
    };
    r.onerror = function(e){
      const msg = dictationErrorText(e.error);
      if(msg && e.error !== 'no-speech') toast(msg);
      if(FATAL.indexOf(e.error) >= 0) dictOn = false;
    };
    r.onend = function(){
      // Angezeigten Text (inkl. unfertiger Woerter) als neue Basis uebernehmen
      dict = { base: $('input').value, fin: '' };
      if(dictOn){
        quick = Date.now() - lastStart < 500 ? quick + 1 : 0;
        if(quick < 3){ setTimeout(function(){ if(dictOn) beginRec(Ctor); }, 120); return; }
        dictOn = false;
        toast('Diktat beendet: keine Sprache erkannt.');
      }
      setMic(false);
    };
    rec = r;
    lastStart = Date.now();
    try { r.start(); setMic(true); }
    catch(err){ dictOn = false; setMic(false); toast('Diktat konnte nicht starten.'); }
  }
  function stopRec(hard){
    dictOn = false;
    if(!rec) return;
    const r = rec;
    if(hard){ r.onresult = r.onend = r.onerror = null; try { r.abort(); } catch(e){} rec = null; setMic(false); }
    else { try { r.stop(); } catch(e){} }
  }
  function toggleMic(){
    if(dictOn){ stopRec(false); return; }
    const sup = dictationSupport(window, window.isSecureContext);
    if(!sup.ok){ toast(sup.reason); return; }
    dict = { base: $('input').value, fin: '' };
    quick = 0; dictOn = true;
    beginRec(sup.Ctor);
  }

  /* ---------- Projekte und Artefakte ---------- */
  let tab = 'chats';
  let openArt = null;
  function activeProject(){ return state.projects.find(function(p){ return p.id === state.project; }) || null; }
  function matchQ(s){ const q = chatQuery.trim().toLowerCase(); return !q || String(s).toLowerCase().indexOf(q) >= 0; }
  const ICON_EDIT = '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg>';

  function renderProjects(box){
    const list = state.projects.filter(function(p){ return matchQ(p.name + ' ' + p.instructions); });
    if(!list.length){ box.innerHTML = '<div class="list-empty">' + (state.projects.length ? 'Keine Treffer.' : 'Noch keine Projekte. Ein Projekt bündelt Chats, Artefakte und Anweisungen.') + '</div>'; return; }
    box.innerHTML = list.map(function(p){
      const n = state.chats.filter(function(c){ return c.projectId === p.id; }).length;
      return '<div class="proj' + (p.id === state.project ? ' on' : '') + '" data-id="' + escapeHtml(p.id) + '">' +
        '<button class="pt" data-use><strong>' + escapeHtml(p.name) + '</strong><small>' + n + ' Chat(s)' + (p.instructions ? ' · mit Anweisungen' : '') + '</small></button>' +
        '<button class="cd" data-pedit aria-label="Projekt bearbeiten">' + ICON_EDIT + '</button>' +
        '<button class="cd" data-pdel aria-label="Projekt löschen">\u2715</button></div>';
    }).join('');
  }

  function renderArtifacts(box){
    const list = state.artifacts.filter(function(a){ return (!state.project || a.projectId === state.project) && matchQ(a.title + ' ' + a.code); }).sort(function(a, b){ return b.ts - a.ts; });
    if(!list.length){ box.innerHTML = '<div class="list-empty">' + (state.artifacts.length ? 'Keine Treffer.' : 'Noch keine Artefakte. Tippe an einem Codeblock auf "Artefakt", um ihn zu sichern.') + '</div>'; return; }
    box.innerHTML = list.map(function(a){
      return '<div class="art" data-id="' + escapeHtml(a.id) + '"><button class="at" data-aopen><strong>' + escapeHtml(a.title) + '</strong><small>' + escapeHtml(artifactExt(a.lang)) + ' · ' + new Date(a.ts).toLocaleDateString('de-DE') + '</small></button>' +
        '<button class="cd" data-adel aria-label="Artefakt löschen">\u2715</button></div>';
    }).join('');
  }

  function saveArtifact(code, lang){
    const chat = currentChat();
    if(state.artifacts.some(function(a){ return a.code === code && a.chatId === (chat && chat.id); })){ toast('Schon als Artefakt gespeichert'); return; }
    const l = lang === 'Code' ? '' : lang;
    state.artifacts.unshift({ id: uid(), title: artifactTitle(code, l), lang: l, code: code, chatId: chat ? chat.id : '', projectId: (chat && chat.projectId) || '', ts: Date.now() });
    save(); renderChatList(); toast('Artefakt gespeichert');
  }

  function showArtifact(a){
    openArt = a;
    $('artTitle').textContent = a.title;
    $('artCode').textContent = a.code;
    $('artFrame').hidden = true; $('artFrame').removeAttribute('srcdoc');
    $('artPrev').hidden = artifactExt(a.lang) !== 'html';
    if(!$('artDlg').open) $('artDlg').showModal();
  }

  function setTab(t){
    tab = t;
    document.querySelectorAll('.tabs button').forEach(function(b){ b.classList.toggle('on', b.getAttribute('data-tab') === t); });
    const nb = $('btnNew');
    nb.hidden = t === 'artifacts';
    nb.textContent = t === 'projects' ? 'Neues Projekt' : 'Neuer Chat';
    renderChatList();
  }

  function editProject(p){
    const name = cleanTitle(prompt('Name des Projekts', p ? p.name : ''));
    if(!name) return;
    const ins = prompt('Anweisungen für alle Chats dieses Projekts (optional)', p ? p.instructions : '');
    if(ins === null && !p) return;
    if(p){ p.name = name; if(ins !== null) p.instructions = ins.trim(); }
    else { p = { id: uid(), name: name, instructions: (ins || '').trim(), ts: Date.now() }; state.projects.unshift(p); state.project = p.id; }
    save(); renderChatList();
  }

  function renderChatList(){
    const box = $('chatList');
    if(tab === 'projects'){ renderProjects(box); return; }
    if(tab === 'artifacts'){ renderArtifacts(box); return; }
    const ap = activeProject();
    const banner = ap ? '<div class="pbanner"><span>Projekt: ' + escapeHtml(ap.name) + '</span><button type="button" data-clrproj>Alle Chats</button></div>' : '';
    const pool = state.chats.filter(function(c){ return !ap || c.projectId === ap.id; });
    if(!pool.length){ box.innerHTML = banner + '<div class="list-empty">Noch keine Chats.</div>'; return; }
    const sorted = filterChats(pool, chatQuery);
    if(!sorted.length){ box.innerHTML = banner + '<div class="list-empty">Keine Treffer.</div>'; return; }
    box.innerHTML = banner + sorted.map(function(c){
      return '<div class="ci' + (c.id === state.current ? ' active' : '') + '" data-id="' + escapeHtml(c.id) + '">' +
        '<button class="ct" data-open>' + escapeHtml(c.title) + '</button>' +
        '<button class="cd" data-ren aria-label="Chat umbenennen"><svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/></svg></button>' +
        '<button class="cd" data-del aria-label="Chat löschen">\u2715</button></div>';
    }).join('');
  }

  function setStatus(s){
    status = s;
    const dot = $('dot');
    dot.className = 'dot ' + (s === 'ok' ? 'ok' : s === 'err' ? 'err' : s === 'wait' ? 'wait' : '');
    dot.title = s === 'ok' ? 'Verbunden' : s === 'err' ? 'Nicht erreichbar' : s === 'wait' ? 'Verbinde …' : 'Kein Modell';
    const line = $('statusLine');
    if(line) line.textContent = s === 'ok' ? 'Verbunden, ' + models.length + ' Modell(e) gefunden.' : s === 'err' ? 'Nicht erreichbar.' : s === 'wait' ? 'Verbinde …' : 'Verbunden, aber kein Modell installiert.';
  }

  function fillModels(){
    const sel = $('model');
    if(!models.length){
      sel.innerHTML = '<option value="">Kein Modell</option>';
      sel.disabled = true;
      return;
    }
    sel.disabled = false;
    sel.innerHTML = models.map(function(n){
      return '<option value="' + escapeHtml(n) + '"' + (n === state.model ? ' selected' : '') + '>' + escapeHtml(n) + '</option>';
    }).join('');
  }

  function setBusy(b){
    busy = b;
    const btn = $('send');
    btn.classList.toggle('stop', b);
    btn.innerHTML = b ? ICON_STOP : ICON_SEND;
    btn.setAttribute('aria-label', b ? 'Stoppen' : 'Senden');
    $('messages').setAttribute('aria-busy', b ? 'true' : 'false');
  }

  /* ---------- Ollama ---------- */
  async function refreshModels(){
    setStatus('wait');
    if(!currentChat() || !currentChat().messages.length) render();
    const ctl = new AbortController();
    const timer = setTimeout(function(){ ctl.abort(); }, 7000);
    try {
      const url0 = state.url;
      const res = await fetch(url0 + '/api/tags', { signal: ctl.signal });
      if(res.status === 502 && url0 === location.origin) throw new Error('Der Mini Webserver erreicht Ollama nicht. Läuft Ollama, und stimmt die Ollama-Adresse im Mini Webserver?');
      if(!res.ok) throw new Error('Ollama antwortet mit HTTP ' + res.status + '.');
      const data = await res.json();
      const list = data.models || [];
      models = list.map(function(m){ return m.name; }).sort();
      modelInfo = {};
      list.forEach(function(m){ modelInfo[m.name] = { families: (m.details && m.details.families) || [] }; });
      if(models.indexOf(state.model) < 0) state.model = models[0] || '';
      connError = '';
      fillModels();
      setStatus(models.length ? 'ok' : 'empty');
      save();
    } catch(e){
      models = [];
      connError = friendlyError(e);
      fillModels();
      setStatus('err');
    } finally {
      clearTimeout(timer);
    }
    const c = currentChat();
    if(!c || !c.messages.length) render();
  }

  async function run(chat){
    const reply = { role: 'assistant', content: '', thinking: '' };
    chat.messages.push(reply);
    chat.ts = Date.now();
    setBusy(true);
    render();
    abortCtl = new AbortController();

    const msgs = buildMessages(buildSystem(state.system, activeProject()), chat.messages.slice(0, -1));
    let liveOut = 0, usage = null;
    tokLive = 0;
    updateTokens();

    try {
      const res = await fetch(state.url + '/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ model: state.model, messages: msgs, stream: true, options: buildOptions(state) }),
        signal: abortCtl.signal
      });
      if(!res.ok){
        let detail = '';
        try { const j = await res.json(); detail = j.error || ''; } catch(e){}
        throw new Error(detail || ('Ollama antwortet mit HTTP ' + res.status + '.'));
      }
      const reader = res.body.getReader();
      const dec = new TextDecoder();
      let raw = '', field = '';
      const parser = createNdjsonParser(function(o){
        if(o.error) throw new Error(o.error);
        const mm = o.message || {};
        if(mm.thinking) field += mm.thinking;
        if(mm.content) raw += mm.content;
        if(mm.thinking || mm.content){ liveOut++; tokLive = liveOut; updateTokens(); }  // ein Stueck entspricht in Ollama etwa einem Token
        if(o.done) usage = o;                                                           // letzte Zeile enthaelt die exakten Zahlen
        const sp = splitThink(raw);
        reply.thinking = field + sp.thinking;
        reply.content = sp.content;
        updateLive();
        saveSoon();
      });
      while(true){
        const r = await reader.read();
        if(r.done) break;
        parser.push(dec.decode(r.value, { stream: true }));
      }
      parser.end();
      if(!reply.content && !reply.thinking) reply.error = 'Das Modell hat keine Antwort geliefert.';
    } catch(e){
      if(e && e.name === 'AbortError'){
        if(!reply.content && !reply.thinking) chat.messages.pop();
      } else {
        reply.error = friendlyError(e);
        if(e instanceof TypeError) setStatus('err');
      }
    } finally {
      abortCtl = null;
      if(usage) chat.tok = addUsage(chat.tok, usage);
      else if(liveOut) chat.tok = addUsage(chat.tok, { eval_count: liveOut });   // Abbruch: Schaetzung statt exakter Zahl
      tokLive = null;
      paintTokens();
      refreshCtxLimit().then(function(){ checkContext(chat); });
      setBusy(false);
      save();
      finishLive(chat);
    }
  }

  async function send(){
    if(busy){ if(abortCtl) abortCtl.abort(); return; }
    stopRec(true);
    const input = $('input');
    const images = pending.filter(function(a){ return a.kind === 'image'; }).map(function(a){ return a.b64; });
    const fileParts = pending.filter(function(a){ return a.kind === 'file'; }).map(function(a){
      return '**Datei: ' + a.name + (a.truncated ? ' (gekürzt)' : '') + '**\n```' + (a.ext || '') + '\n' + a.text + '\n```';
    });
    let text = input.value.trim();
    if(fileParts.length) text = (text ? text + '\n\n' : '') + fileParts.join('\n\n');
    if(!text && !images.length) return;
    if(!state.model){ toast('Wähle zuerst ein Modell.'); if(status === 'err') openSettings(); return; }
    const chat = currentChat() || newChat();
    const um = { role: 'user', content: text };
    if(images.length){ um.images = images; um.imgN = images.length; }
    pending = []; renderAttachments();
    chat.messages.push(um);
    if(chat.messages.length === 1) chat.title = (input.value.trim() || fileParts.length && 'Datei' || 'Bild').replace(/\s+/g, ' ').slice(0, 42);
    input.value = '';
    autosize();
    await run(chat);
  }

  async function regenerate(){
    const chat = currentChat();
    if(!chat || busy) return;
    while(chat.messages.length && chat.messages[chat.messages.length - 1].role === 'assistant') chat.messages.pop();
    if(!chat.messages.length) return;
    await run(chat);
  }

  /* ---------- Export / Import ---------- */
  function download(name, text, type){
    const url = URL.createObjectURL(new Blob([text], { type: type }));
    const a = document.createElement('a');
    a.href = url; a.download = name;
    document.body.appendChild(a); a.click(); a.remove();
    setTimeout(function(){ URL.revokeObjectURL(url); }, 1000);
  }
  function slug(t){
    return String(t || 'chat').toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '').slice(0, 40) || 'chat';
  }
  function exportMarkdown(){
    const c = currentChat();
    if(!c || !c.messages.length){ toast('Kein Chat zum Exportieren'); return; }
    download(slug(c.title) + '.md', chatToMarkdown(c), 'text/markdown');
  }
  function exportJson(){
    if(!state.chats.length){ toast('Keine Chats vorhanden'); return; }
    download('ollama-chats.json', chatsToJson(state.chats), 'application/json');
  }
  async function importFile(file){
    try {
      const list = parseImport(await file.text());
      list.forEach(function(c){ c.id = uid(); });
      state.chats = list.concat(state.chats);
      save(); render();
      toast(list.length + ' Chat(s) importiert');
    } catch(e){
      toast(e.message || 'Import fehlgeschlagen');
    }
  }

  /* ---------- Bilder ---------- */
  function fileToBase64(file){
    return new Promise(function(resolve, reject){
      const url = URL.createObjectURL(file);
      const img = new Image();
      img.onload = function(){
        const k = Math.min(1, 1280 / Math.max(img.naturalWidth, img.naturalHeight));
        const c = document.createElement('canvas');
        c.width = Math.max(1, Math.round(img.naturalWidth * k));
        c.height = Math.max(1, Math.round(img.naturalHeight * k));
        const g = c.getContext('2d');
        g.fillStyle = '#fff'; g.fillRect(0, 0, c.width, c.height);
        g.drawImage(img, 0, 0, c.width, c.height);
        URL.revokeObjectURL(url);
        resolve(c.toDataURL('image/jpeg', 0.85).split(',')[1]);
      };
      img.onerror = function(){ URL.revokeObjectURL(url); reject(new Error('Bild konnte nicht gelesen werden.')); };
      img.src = url;
    });
  }
  function renderAttachments(){
    $('thumbs').innerHTML = pending.map(function(a, i){
      if(a.kind === 'image'){
        return '<div class="thumb"><img alt="Vorschau" src="data:image/jpeg;base64,' + escapeHtml(a.b64) + '"><button type="button" data-rm="' + i + '" aria-label="Bild entfernen">\u2715</button></div>';
      }
      return '<div class="filechip"><span class="fname">' + escapeHtml(a.name) + '</span><button type="button" data-rm="' + i + '" aria-label="Datei entfernen">\u2715</button></div>';
    }).join('');
  }
  // Erkennt Binaerdateien anhand eines NUL-Bytes in den ersten Bytes (PDF, ZIP, EXE, ...).
  // Text-Dateien beliebiger Programmiersprache/Kodierung enthalten praktisch nie ein NUL-Byte.
  function looksBinary(bytes){
    for(let i = 0; i < bytes.length; i++) if(bytes[i] === 0) return true;
    return false;
  }

  function fileExt(name){
    const m = /\.([a-z0-9]+)$/i.exec(name || '');
    return m ? m[1].toLowerCase() : '';
  }

  function readTextFile(file){
    return new Promise(function(resolve, reject){
      const probe = new FileReader();
      probe.onload = function(){
        if(looksBinary(new Uint8Array(probe.result))){ reject(new Error(file.name + ': keine Textdatei (Binärformat).')); return; }
        file.text().then(resolve, reject);
      };
      probe.onerror = function(){ reject(new Error(file.name + ' konnte nicht gelesen werden.')); };
      probe.readAsArrayBuffer(file.slice(0, 8192));
    });
  }

  // Waehlt bei Bedarf automatisch ein passendes installiertes Modell (Bild- oder Code-Modell).
  function applyModelForNeed(need){
    if(!need) return;
    const choice = pickModelFor(need, models, modelInfo, state.model);
    if(!choice) {
      if(need === 'vision' && !isVisionCapable(state.model, modelInfo[state.model] && modelInfo[state.model].families)){
        toast('Kein bild-fähiges Modell installiert (z. B. llava oder llama3.2-vision).');
      }
      return;
    }
    state.model = choice;
    save();
    fillModels();
    toast('Modell gewechselt zu ' + choice + (need === 'vision' ? ' (unterstützt Bilder)' : ' (Code-Modell)'));
  }

  async function addAttachments(files){
    let sawImage = false, sawCode = false;
    for(const f of files){
      if(pending.length >= MAX_ATTACH){ toast('Höchstens ' + MAX_ATTACH + ' Anhänge'); break; }
      if(/^image\//.test(f.type)){
        try { pending.push({ kind: 'image', b64: await fileToBase64(f) }); sawImage = true; }
        catch(e){ toast(e.message); }
        continue;
      }
      try {
        let text = await readTextFile(f);
        const ext = fileExt(f.name);
        let truncated = false;
        if(text.length > MAX_FILE_CHARS){ text = text.slice(0, MAX_FILE_CHARS); truncated = true; }
        pending.push({ kind: 'file', name: f.name, ext: ext, text: text, truncated: truncated });
        if(TEXT_EXT.test(f.name) && ext && !/^(txt|md|markdown|csv|tsv|log|json|jsonl|ya?ml|xml|ini|toml|conf|cfg|env)$/i.test(ext)) sawCode = true;
        if(truncated) toast(f.name + ' ist lang, wird gekürzt gesendet.');
      } catch(e){
        toast(e.message || (f.name + ' wird nicht unterstützt.'));
      }
    }
    renderAttachments();
    if(sawImage) applyModelForNeed('vision');
    else if(sawCode) applyModelForNeed('coder');
  }

  /* ---------- Soft-Tastatur (visualViewport) ---------- */
  function applyViewport(){
    const root = document.documentElement;
    const f = fitViewport(window.visualViewport, window.innerHeight);
    const stick = nearBottom();
    if(!f){
      root.classList.remove('vv', 'kb');
      ['--vvh', '--vvt', '--vvb'].forEach(function(k){ root.style.removeProperty(k); });
    } else {
      root.style.setProperty('--vvh', f.height + 'px');
      root.style.setProperty('--vvt', f.top + 'px');
      root.style.setProperty('--vvb', f.bottom + 'px');
      root.classList.add('vv');
      root.classList.toggle('kb', f.keyboard);
    }
    if(stick) scrollDown(true);
  }

  /* ---------- UI ---------- */
  function autosize(){
    const el = $('input');
    el.style.height = 'auto';
    el.style.height = Math.min(el.scrollHeight, 160) + 'px';
  }

  function openDrawer(open){
    $('drawer').classList.toggle('open', open);
    $('scrim').classList.toggle('open', open);
  }

  function openSettings(){
    $('url').value = state.url;
    $('system').value = state.system;
    $('temp').value = state.temperature;
    $('tempVal').textContent = Number(state.temperature).toFixed(1);
    $('topP').value = state.topP;
    $('topPVal').textContent = Number(state.topP).toFixed(2);
    $('repeat').value = state.repeatPenalty;
    $('repeatVal').textContent = Number(state.repeatPenalty).toFixed(2);
    $('dictLang').value = state.dictLang || 'auto';
    $('numCtx').value = String(state.numCtx || 0);
    if($('numCtx').value !== String(state.numCtx || 0)) $('numCtx').value = '0';
    setStatus(status);
    const d = $('settings');
    if(!d.open) d.showModal();
  }

  async function saveSettings(){
    state.url = normalizeUrl($('url').value) || defaultUrl();
    state.system = $('system').value;
    state.temperature = parseFloat($('temp').value);
    state.topP = parseFloat($('topP').value);
    state.repeatPenalty = parseFloat($('repeat').value);
    state.numCtx = parseInt($('numCtx').value, 10) || 0;
    state.dictLang = $('dictLang').value || 'auto';
    save();
    $('url').value = state.url;
    await refreshModels();
    if(status === 'ok' || status === 'empty') $('settings').close();
  }

  function init(){
    setBusy(false);
    $('model').addEventListener('change', function(e){ state.model = e.target.value; save(); render(); });
    $('btnMenu').addEventListener('click', function(){ openDrawer(true); });
    $('scrim').addEventListener('click', function(){ openDrawer(false); });
    $('btnSettings').addEventListener('click', openSettings);
    $('btnClose').addEventListener('click', function(){ $('settings').close(); });
    $('btnSave').addEventListener('click', saveSettings);
    $('temp').addEventListener('input', function(e){ $('tempVal').textContent = Number(e.target.value).toFixed(1); });
    $('topP').addEventListener('input', function(e){ $('topPVal').textContent = Number(e.target.value).toFixed(2); });
    $('repeat').addEventListener('input', function(e){ $('repeatVal').textContent = Number(e.target.value).toFixed(2); });
    $('chatSearch').addEventListener('input', function(e){ chatQuery = e.target.value; renderChatList(); });
    $('btnAttach').addEventListener('click', function(){ $('attachFile').click(); });
    $('attachFile').addEventListener('change', function(e){
      const fl = Array.from(e.target.files || []);
      e.target.value = '';
      if(fl.length) addAttachments(fl);
    });
    $('thumbs').addEventListener('click', function(e){
      const b = e.target.closest('[data-rm]');
      if(!b) return;
      pending.splice(+b.getAttribute('data-rm'), 1);
      renderAttachments();
    });
    $('btnExpMd').addEventListener('click', exportMarkdown);
    $('btnExpJson').addEventListener('click', exportJson);
    $('btnImp').addEventListener('click', function(){ $('impFile').click(); });
    $('impFile').addEventListener('change', function(e){
      const f = e.target.files && e.target.files[0];
      if(f) importFile(f);
      e.target.value = '';
    });
    $('btnWipe').addEventListener('click', function(){
      if(!confirm('Alle Chats unwiderruflich löschen?')) return;
      state.chats = []; state.current = null; save(); render(); $('settings').close(); openDrawer(false);
    });
    $('btnNew').addEventListener('click', function(){
      if(tab === 'projects'){ editProject(null); return; }
      if(busy) return;
      const c = currentChat();
      if(!c || c.messages.length) newChat();
      openDrawer(false); render(); $('input').focus();
    });
    $('chatList').addEventListener('click', function(e){
      if(e.target.closest('[data-clrproj]')){ state.project = ''; save(); renderChatList(); return; }
      const pj = e.target.closest('.proj');
      if(pj){
        const p = state.projects.find(function(x){ return x.id === pj.getAttribute('data-id'); });
        if(!p) return;
        if(e.target.closest('[data-pedit]')) editProject(p);
        else if(e.target.closest('[data-pdel]')){
          if(!confirm('Projekt "' + p.name + '" löschen? Chats und Artefakte bleiben erhalten.')) return;
          state.projects = state.projects.filter(function(x){ return x.id !== p.id; });
          state.chats.forEach(function(c){ if(c.projectId === p.id) c.projectId = ''; });
          state.artifacts.forEach(function(a){ if(a.projectId === p.id) a.projectId = ''; });
          if(state.project === p.id) state.project = '';
          save(); renderChatList();
        } else { state.project = state.project === p.id ? '' : p.id; save(); setTab('chats'); toast(state.project ? 'Projekt aktiv: ' + p.name : 'Projekt abgewählt'); }
        return;
      }
      const ar = e.target.closest('.art');
      if(ar){
        const a = state.artifacts.find(function(x){ return x.id === ar.getAttribute('data-id'); });
        if(!a) return;
        if(e.target.closest('[data-adel]')){ if(!confirm('Dieses Artefakt löschen?')) return; state.artifacts = state.artifacts.filter(function(x){ return x.id !== a.id; }); save(); renderChatList(); }
        else showArtifact(a);
        return;
      }
      const item = e.target.closest('.ci');
      if(!item) return;
      const id = item.getAttribute('data-id');
      if(e.target.closest('[data-ren]')){
        const chat = state.chats.find(function(c){ return c.id === id; });
        if(!chat) return;
        const t = cleanTitle(prompt('Neuer Titel für den Chat', chat.title));
        if(t){ chat.title = t; save(); renderChatList(); }
      } else if(e.target.closest('[data-del]')){
        if(busy || !confirm('Diesen Chat löschen?')) return;
        state.chats = state.chats.filter(function(c){ return c.id !== id; });
        if(state.current === id) state.current = null;
        save(); render();
      } else if(e.target.closest('[data-open]')){
        if(busy) return;
        state.current = id; save(); openDrawer(false); render();
      }
    });
    $('messages').addEventListener('click', async function(e){
      const artBtn = e.target.closest('[data-art]');
      if(artBtn){
        const box = artBtn.closest('.code');
        saveArtifact(box.querySelector('code').textContent, box.querySelector('.code-head span').textContent);
        return;
      }
      const codeBtn = e.target.closest('[data-copy]');
      if(codeBtn){
        const code = codeBtn.closest('.code').querySelector('code').textContent;
        toast(await copyText(code) ? 'Code kopiert' : 'Kopieren nicht möglich');
        return;
      }
      const act = e.target.closest('[data-act]');
      if(!act) return;
      const a = act.getAttribute('data-act');
      if(a === 'copy'){
        const chat = currentChat();
        const m = chat && chat.messages[+act.getAttribute('data-i')];
        if(m) toast(await copyText(m.content) ? 'Antwort kopiert' : 'Kopieren nicht möglich');
      } else if(a === 'regen') regenerate();
      else if(a === 'reconnect') refreshModels();
      else if(a === 'settings') openSettings();
    });
    document.querySelector('.tabs').addEventListener('click', function(e){
      const b = e.target.closest('[data-tab]');
      if(b) setTab(b.getAttribute('data-tab'));
    });
    $('artClose').addEventListener('click', function(){ $('artDlg').close(); });
    $('artCopy').addEventListener('click', async function(){ if(openArt) toast(await copyText(openArt.code) ? 'Code kopiert' : 'Kopieren nicht möglich'); });
    $('artDl').addEventListener('click', function(){ if(openArt) download(slug(openArt.title) + '.' + artifactExt(openArt.lang), openArt.code, 'text/plain'); });
    $('artPrev').addEventListener('click', function(){
      const f = $('artFrame');
      if(!openArt) return;
      f.hidden = !f.hidden;
      if(!f.hidden) f.srcdoc = openArt.code;
    });
    $('artDel').addEventListener('click', function(){
      if(!openArt || !confirm('Dieses Artefakt löschen?')) return;
      state.artifacts = state.artifacts.filter(function(x){ return x.id !== openArt.id; });
      openArt = null; save(); $('artDlg').close(); renderChatList();
    });
    $('send').addEventListener('click', send);
    $('input').addEventListener('input', function(){ autosize(); if(dictOn) dict = { base: this.value, fin: '' }; });
    $('btnMic').addEventListener('click', toggleMic);
    document.addEventListener('visibilitychange', function(){ if(document.hidden && dictOn) stopRec(false); });
    $('input').addEventListener('keydown', function(e){
      const touch = window.matchMedia && window.matchMedia('(pointer:coarse)').matches;
      if(e.key === 'Enter' && !e.shiftKey && !touch && !e.isComposing){ e.preventDefault(); send(); }
    });
    document.addEventListener('keydown', function(e){ if(e.key === 'Escape') openDrawer(false); });

    if(window.visualViewport){
      window.visualViewport.addEventListener('resize', applyViewport);
      window.visualViewport.addEventListener('scroll', applyViewport);
      window.addEventListener('orientationchange', applyViewport);
      applyViewport();
    }

    if(!currentChat() && state.chats.length) state.current = state.chats[0].id;
    renderChatList();
    render();
    refreshModels();
  }

  init();

  /* ---------- PWA (optional, nur wenn per http/https geladen) ---------- */
  if(/^https?:$/.test(location.protocol)){
    const lk = document.createElement('link');
    lk.rel = 'manifest'; lk.href = 'manifest.json';
    document.head.appendChild(lk);
    if('serviceWorker' in navigator && window.isSecureContext){
      navigator.serviceWorker.register('sw.js').catch(function(){});
    }
  }
})();
