'use strict';
// Tests ohne Abhängigkeiten: node tests/run.js
const fs = require('fs');
const vm = require('vm');
const http = require('http');
const path = require('path');
const assert = require('assert');

const root = path.join(__dirname, '..');
const htmlSrc = fs.readFileSync(path.join(root, 'ollama.html'), 'utf8');
const cssSrc = fs.readFileSync(path.join(root, 'style.css'), 'utf8');
const script = fs.readFileSync(path.join(root, 'script.js'), 'utf8');

let passed = 0;
async function test(name, fn){
  try { await fn(); passed++; console.log('  ok   ' + name); }
  catch(e){ console.error('  FAIL ' + name + '\n       ' + e.message); process.exitCode = 1; }
}

// Reine Funktionen aus dem Block <pure> laden
const pure = script.split('// <pure>')[1].split('// </pure>')[1 - 1];
const ctx = {};
vm.createContext(ctx);
vm.runInContext(pure + '\nthis.api={escapeHtml,inline,renderMarkdown,createNdjsonParser,normalizeUrl,chatToMarkdown,chatsToJson,parseImport,buildMessages,buildOptions,filterChats,cleanTitle,splitThink,highlight,fitViewport,isVisionModelName,isVisionModelFamilies,isVisionCapable,isCoderModelName,pickModelFor,artifactExt,artifactTitle,buildSystem,mergeDictation,dictationSupport,dictationErrorText,dictationLang,segDigit,formatTokens,sevenSegHtml,addUsage,tokensView,tokensAria,contextState};', ctx);
const api = ctx.api;

// Text eines Codeblocks ohne Hervorhebungs-Spans (bleibt escaped)
const codeText = html => html.match(/<pre><code>([\s\S]*?)<\/code><\/pre>/)[1].replace(/<[^>]*>/g, '');

(async () => {
  console.log('Tests für ollama.html / script.js / style.css');

  await test('Export: Markdown enthält Titel und Rollen', () => {
    const md = api.chatToMarkdown({ title: 'Test', messages: [{ role: 'user', content: 'Hi' }, { role: 'assistant', content: 'Hallo' }] });
    assert(md.startsWith('# Test'), md);
    assert(md.includes('## Du\n\nHi') && md.includes('## Modell\n\nHallo'), md);
  });
  await test('Export/Import: JSON-Rundlauf', () => {
    const chats = [{ id: 'x', title: 'A', ts: 5, messages: [{ role: 'user', content: 'u' }, { role: 'assistant', content: 'a', thinking: 't' }] }];
    const back = api.parseImport(api.chatsToJson(chats));
    assert.strictEqual(back.length, 1);
    assert.strictEqual(back[0].messages[1].thinking, 't');
    assert.strictEqual(back[0].title, 'A');
  });
  await test('Import: ungültige Dateien werden abgelehnt', () => {
    assert.throws(() => api.parseImport('kein json'), /JSON/);
    assert.throws(() => api.parseImport('{"chats":[]}'), /gültigen/);
    assert.throws(() => api.parseImport('{"x":1}'), /Keine Chats/);
  });
  await test('Import: fremde Felder und Rollen werden verworfen', () => {
    const back = api.parseImport(JSON.stringify([{ title: 'B', messages: [{ role: 'system', content: 'x' }, { role: 'user', content: 'ok', evil: 1 }] }]));
    assert.strictEqual(back[0].messages.length, 1);
    assert(!('evil' in back[0].messages[0]));
  });

  await test('Bilder: buildMessages sendet images nur bei Nutzernachrichten', () => {
    const out = api.buildMessages(' Sys ', [{ role: 'user', content: '', images: ['AAA'] }, { role: 'assistant', content: 'ok', images: ['X'] }, { role: 'user', content: '' }]);
    assert.strictEqual(out.length, 3);
    assert.strictEqual(out[0].content, 'Sys');
    assert.deepStrictEqual(out[1].images, ['AAA']);
    assert(!('images' in out[2]));
  });
  await test('Bilder: JSON-Export enthält keine Base64-Daten', () => {
    const j = api.chatsToJson([{ title: 'B', messages: [{ role: 'user', content: 'x', images: ['GEHEIM'], imgN: 1 }] }]);
    assert(!j.includes('GEHEIM'));
    assert.strictEqual(api.parseImport(j)[0].messages[0].imgN, 1);
  });

  await test('Parameter: buildOptions setzt Werte, begrenzt und lässt num_ctx weg', () => {
    const o = api.buildOptions({ temperature: 0.5, topP: 0.8, repeatPenalty: 1.2, numCtx: 0 });
    assert.deepStrictEqual(JSON.parse(JSON.stringify(o)), { temperature: 0.5, top_p: 0.8, repeat_penalty: 1.2 });
    const p = api.buildOptions({ temperature: 9, topP: -1, repeatPenalty: 'x', numCtx: '8192' });
    assert.strictEqual(p.temperature, 2);
    assert.strictEqual(p.top_p, 0);
    assert.strictEqual(p.repeat_penalty, 1.1);
    assert.strictEqual(p.num_ctx, 8192);
  });

  await test('Suche: filterChats sucht in Titel und Nachrichten, neueste zuerst', () => {
    const cs = [{ id: 'a', title: 'Rezepte', ts: 1, messages: [] }, { id: 'b', title: 'Code', ts: 3, messages: [{ role: 'user', content: 'Wie backe ich REZEPT?' }] }, { id: 'c', title: 'Sonstiges', ts: 2, messages: [{ role: 'user', content: 'x' }] }];
    assert.deepStrictEqual(api.filterChats(cs, ' rezept ').map(c => c.id), ['b', 'a']);
    assert.deepStrictEqual(api.filterChats(cs, '').map(c => c.id), ['b', 'c', 'a']);
    assert.strictEqual(api.filterChats(cs, 'zzz').length, 0);
  });
  await test('Titel: cleanTitle bereinigt, begrenzt und lehnt leer ab', () => {
    assert.strictEqual(api.cleanTitle('  Mein   Titel \n'), 'Mein Titel');
    assert.strictEqual(api.cleanTitle('x'.repeat(200)).length, 80);
    assert.strictEqual(api.cleanTitle('   '), null);
    assert.strictEqual(api.cleanTitle(null), null);
  });

  await test('Think: splitThink trennt Gedankengang und Antwort', () => {
    assert.deepStrictEqual({ ...api.splitThink('<think>\nAlso 2+2.\n</think>\n\nVier.') }, { thinking: 'Also 2+2.', content: 'Vier.' });
    assert.deepStrictEqual({ ...api.splitThink('Nur Text mit <think> im Satz') }, { thinking: '', content: 'Nur Text mit <think> im Satz' });
    assert.deepStrictEqual({ ...api.splitThink('  <think>offen') }, { thinking: 'offen', content: '' });
  });
  await test('Think: zerstückelte Tags flackern im Stream nie durch', () => {
    const full = '<think>abc</think>Antwort';
    for(let i = 0; i <= full.length; i++){
      const sp = api.splitThink(full.slice(0, i));
      assert(!/</.test(sp.thinking) && !/</.test(sp.content), i + ': ' + JSON.stringify(sp));
      if(i < full.indexOf('</think>') + 8) assert.strictEqual(sp.content, '', i + ': ' + JSON.stringify(sp));
    }
    assert.strictEqual(api.splitThink(full).content, 'Antwort');
  });

  await test('Markdown: Durchgestrichen', () => {
    assert(api.renderMarkdown('das ~~alte~~ neue').includes('<del>alte</del>'));
    assert(!api.renderMarkdown('a ~~ b ~~ c ~ d').includes('<del>'));
  });
  await test('Markdown: Tabelle mit Ausrichtung, Escaping und Auffüllen', () => {
    const out = api.renderMarkdown('| Name | Wert | Mitte |\n|:---|---:|:---:|\n| **a** | 1 | <b>x</b> |\n| nur | zwei |\n\nDanach');
    assert(out.includes('<table>') && out.includes('<th>Name</th>'), out);
    assert(out.includes('<th style="text-align:right">Wert</th>'), out);
    assert(out.includes('<th style="text-align:center">Mitte</th>'), out);
    assert(out.includes('<td><strong>a</strong></td>'), out);
    assert(!out.includes('<b>'), 'HTML in Zelle nicht escaped');
    assert.strictEqual((out.match(/<tr>/g) || []).length, 3);
    assert(out.includes('<td style="text-align:center"></td>'), 'fehlende Zelle nicht aufgefüllt');
    assert(out.includes('<p>Danach</p>'));
  });
  await test('Markdown: Tabelle nur mit passender Trennzeile, sonst Absatz', () => {
    assert(!api.renderMarkdown('a | b\nc | d').includes('<table>'));
    assert(!api.renderMarkdown('| a | b |\n|---|\n| 1 | 2 |').includes('<table>'), 'Spaltenzahl ungleich');
    assert(!api.renderMarkdown('a | b\n--|--\n1 | 2').includes('<table>'), 'Trennzeile zu kurz');
    assert(api.renderMarkdown('| a \\| b | c |\n|---|---|\n| 1 | 2 |').includes('<th>a | b</th>'), 'escaped Pipe');
  });
  await test('Highlight: Schlüsselwörter, Strings, Kommentare, Zahlen', () => {
    const h = api.highlight('const x = "a<b"; // Notiz\nreturn 42;', 'js');
    assert(h.includes('<span class="tk-k">const</span>'), h);
    assert(h.includes('<span class="tk-s">&quot;a&lt;b&quot;</span>'), h);
    assert(h.includes('<span class="tk-c">// Notiz</span>'), h);
    assert(h.includes('<span class="tk-n">42</span>'), h);
  });
  await test('Highlight: Text bleibt exakt erhalten (alle Sprachen, Randfälle)', () => {
    const proben = ['x = "offen', "it's <b>&amp;</b>", '/* offen', '"""doc\nstring', '`tpl ${a}` + \'x\'', '', '\n\n', '<!-- c --><a href="x">t</a>', 'SELECT * FROM t WHERE a = 1 -- c', 'a{color:#fff;margin:0 auto}'];
    for(const lang of ['js', 'python', 'bash', 'java', 'sql', 'css', 'html', 'json'])
      for(const src of proben){
        const back = api.highlight(src, lang).replace(/<[^>]*>/g, '').replace(/&lt;/g, '<').replace(/&gt;/g, '>').replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&amp;/g, '&');
        assert.strictEqual(back, src, lang + ': ' + JSON.stringify(src));
      }
  });
  await test('Highlight: unbekannte Sprache und XSS-Versuche', () => {
    assert.strictEqual(api.highlight('<img src=x onerror=alert(1)>', 'klingon'), '&lt;img src=x onerror=alert(1)&gt;');
    const h = api.highlight('let s = "<img src=x onerror=alert(1)>";', 'js');
    assert(!/<img/i.test(h), h);
    assert.strictEqual(api.highlight('a', undefined), 'a');
  });
  await test('Highlight: Python-Dreifachstring, SQL ohne Groß-/Kleinschreibung', () => {
    assert(api.highlight('"""a\nb"""', 'py').startsWith('<span class="tk-s">'));
    assert(api.highlight('select 1', 'SQL').includes('<span class="tk-k">select</span>'));
  });

  await test('PWA: manifest.json ist gültig und vollständig', () => {
    const m = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
    for(const k of ['name', 'short_name', 'start_url', 'display', 'background_color', 'theme_color']) assert(m[k], k + ' fehlt');
    assert.strictEqual(m.display, 'standalone');
    assert(m.icons.some(i => i.sizes === '192x192') && m.icons.some(i => i.sizes === '512x512'), '192/512 fehlen');
    assert(m.icons.some(i => i.purpose === 'maskable'), 'maskable fehlt');
  });
  await test('PWA: Icons existieren, sind PNG und haben die angegebene Größe', () => {
    const m = JSON.parse(fs.readFileSync(path.join(root, 'manifest.json'), 'utf8'));
    const list = m.icons.map(i => [i.src, i.sizes]).concat([['icons/apple-touch-icon.png', '180x180']]);
    for(const [src, sizes] of list){
      const b = fs.readFileSync(path.join(root, src));
      assert.strictEqual(b.slice(1, 4).toString(), 'PNG', src + ' kein PNG');
      assert.strictEqual(b.readUInt32BE(16) + 'x' + b.readUInt32BE(20), sizes, src);
    }
  });
  await test('PWA: Dateien der SW-Hülle existieren, ollama.html verweist auf Icon', () => {
    const sw = fs.readFileSync(path.join(root, 'sw.js'), 'utf8');
    const shell = JSON.parse(sw.match(/const SHELL = (\[[^\]]*\])/)[1].replace(/'/g, '"'));
    for(const f of shell) if(f !== './') assert(fs.existsSync(path.join(root, f)), f + ' fehlt');
    assert(htmlSrc.includes('apple-touch-icon.png'));
  });
  await test('PWA: Service Worker fasst nur GET derselben Herkunft ohne /api/ an', async () => {
    const handlers = {}, puts = [];
    const cache = { addAll: async () => {}, put: async (r, c) => puts.push(r.url) };
    const sandbox = {
      self: { location: { origin: 'http://app.test' }, addEventListener: (n, f) => { handlers[n] = f; }, skipWaiting: async () => {}, clients: { claim: async () => {} } },
      caches: { open: async () => cache, keys: async () => ['alt', 'pandora-code-v3'], delete: async k => { sandbox.deleted = (sandbox.deleted || []).concat(k); return true; }, match: async () => undefined },
      fetch: async () => ({ ok: true, type: 'basic', clone() { return this; } }),
      URL, Response: { error: () => 'ERR' }
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(path.join(root, 'sw.js'), 'utf8'), sandbox);
    const fetchTo = (url, method = 'GET', mode = 'cors') => {
      let handled = false;
      handlers.fetch({ request: { url, method, mode }, respondWith: p => { handled = p; } });
      return handled;
    };
    assert.strictEqual(fetchTo('http://192.168.0.10:11434/api/chat', 'POST'), false, 'POST');
    assert.strictEqual(fetchTo('http://192.168.0.10:11434/api/tags'), false, 'fremde Herkunft');
    assert.strictEqual(fetchTo('http://app.test/api/tags'), false, '/api/ auf gleicher Herkunft');
    assert(fetchTo('http://app.test/ollama.html'), 'App-Datei wird nicht behandelt');
    await fetchTo('http://app.test/ollama.html');
    await new Promise(r => setImmediate(r));
    assert(puts.length >= 1, 'nichts im Cache abgelegt');
    let act; handlers.activate({ waitUntil: p => { act = p; } }); await act;
    assert.deepStrictEqual(sandbox.deleted, ['alt'], 'alter Cache nicht gelöscht');
  });
  await test('PWA: Offline-Rückfall liefert Cache, bei Navigation die Startseite', async () => {
    const handlers = {};
    const sandbox = {
      self: { location: { origin: 'http://app.test' }, addEventListener: (n, f) => { handlers[n] = f; } },
      caches: { match: async (k) => (k === 'ollama.html' ? 'STARTSEITE' : undefined), open: async () => ({}) },
      fetch: async () => { throw new TypeError('offline'); }, URL, Response: { error: () => 'ERR' }
    };
    vm.createContext(sandbox);
    vm.runInContext(fs.readFileSync(path.join(root, 'sw.js'), 'utf8'), sandbox);
    const ask = mode => { let p; handlers.fetch({ request: { url: 'http://app.test/x', method: 'GET', mode }, respondWith: q => { p = q; } }); return p; };
    assert.strictEqual(await ask('navigate'), 'STARTSEITE');
    assert.strictEqual(await ask('cors'), 'ERR');
  });

  await test('Skript hat gültige Syntax', () => { new vm.Script(script); });
  await test('Keine externen Ressourcen', () => {
    const all = htmlSrc.replace(/<a href="\$2"/g, '') + cssSrc + script;
    assert(!/(src|href)\s*=\s*["']https?:/i.test(all), 'externe Ressource gefunden');
    assert(!/@import|cdn\./i.test(all));
  });
  await test('HTML wird escaped (XSS)', () => {
    const out = api.renderMarkdown('<img src=x onerror=alert(1)> <script>x</script>');
    assert(!/<img|<script/i.test(out), out);
  });
  await test('Fettdruck, Kursiv, Inline-Code', () => {
    const out = api.renderMarkdown('**fett** und *kursiv* und `a<b`');
    assert(out.includes('<strong>fett</strong>'));
    assert(out.includes('<em>kursiv</em>'));
    assert(out.includes('<code>a&lt;b</code>'));
  });
  await test('Code in Backticks wird nicht formatiert', () => {
    const out = api.renderMarkdown('`**nicht fett**`');
    assert(!out.includes('<strong>'), out);
  });
  await test('Codeblock mit Sprache und Kopieren-Knopf', () => {
    const out = api.renderMarkdown('Text\n```python\nprint("<hi>")\n```\nDanach');
    assert(out.includes('<span>python</span>'));
    assert.strictEqual(codeText(out), 'print(&quot;&lt;hi&gt;&quot;)');
    assert(out.includes('data-copy'));
    assert(out.includes('<p>Danach</p>'));
  });
  await test('Unfertiger Codeblock (Stream) bricht nichts', () => {
    const out = api.renderMarkdown('```js\nlet a = 1;');
    assert.strictEqual(codeText(out), 'let a = 1;');
    assert(out.includes('<pre>'));
  });
  await test('Listen und Überschriften', () => {
    const out = api.renderMarkdown('# Titel\n- a\n- b\n\n1. eins\n2. zwei');
    assert(out.includes('<h2>Titel</h2>'));
    assert(out.includes('<ul><li>a</li><li>b</li></ul>'));
    assert(out.includes('<ol><li>eins</li><li>zwei</li></ol>'));
  });
  await test('Links nur mit http(s)', () => {
    assert(api.renderMarkdown('[x](https://a.de)').includes('href="https://a.de"'));
    assert(!api.renderMarkdown('[x](javascript:alert(1))').includes('<a '));
  });
  await test('normalizeUrl', () => {
    assert.strictEqual(api.normalizeUrl(' 192.168.0.5:11434/ '), 'http://192.168.0.5:11434');
    assert.strictEqual(api.normalizeUrl('https://x.de//'), 'https://x.de');
    assert.strictEqual(api.normalizeUrl(''), '');
  });
  await test('NDJSON-Parser setzt zerteilte Zeilen zusammen', () => {
    const got = [];
    const p = api.createNdjsonParser(o => got.push(o));
    p.push('{"a":1}\n{"b"'); p.push(':2}\n{"c":3}');
    assert.strictEqual(got.length, 2);
    p.end();
    assert.strictEqual(got.map(o => Object.keys(o)[0]).join(','), 'a,b,c');
  });
  await test('NDJSON-Parser ignoriert Müll, reicht Fehler durch', () => {
    const got = [];
    const p = api.createNdjsonParser(o => got.push(o));
    p.push('kein json\n{"error":"boom"}\n');
    assert.strictEqual(JSON.stringify(got), JSON.stringify([{ error: 'boom' }]));
  });

  await test('Diktat: nutzt nur die Browser-API, keine externen Skripte oder Dienste', () => {
    assert(!/<script[^>]+src=["']https?:/i.test(htmlSrc), 'externes Skript');
    assert(!/getUserMedia|MediaRecorder|new WebSocket|https?:\/\/[a-z0-9.-]+\/[^'"\s]*(speech|stt|transcribe)/i.test(script), 'eigene Audio-/Cloud-Anbindung gefunden');
  });
  await test('Branding: Kopf- und Fußzeile zeigen Pandora Code', () => {
    assert(/class="topbar"[^>]*>Pandora<sup>&reg;<\/sup> Code<\/div>/.test(htmlSrc), 'Kopfzeilen-Branding fehlt');
    assert(/class="brandfoot"[^>]*>Pandora&reg; \| by AKI_SystemDown &copy;2026<\/div>/.test(htmlSrc), 'Fußzeilen-Branding fehlt');
  });
  await test('Datei-Import: allgemeiner Dateianhang statt reinem Bild-Upload', () => {
    assert(/id="attachFile"/.test(htmlSrc), 'attachFile-Input fehlt');
    assert(!/id="imgFile"/.test(htmlSrc), 'altes imgFile-Input noch vorhanden');
    const accept = htmlSrc.match(/id="attachFile"[^>]*accept="([^"]+)"/);
    assert(accept && /image\/\*/.test(accept[1]) && /\.py/.test(accept[1]) && /\.js/.test(accept[1]), 'accept deckt Bilder und Code-Dateien nicht ab');
  });
  await test('Modellwahl: isVisionCapable erkennt Bild-Modelle über Name und families', () => {
    assert(api.isVisionCapable('llava:7b', []));
    assert(api.isVisionCapable('llama3.2-vision:11b', []));
    assert(api.isVisionCapable('qwen2.5-coder:7b', ['clip']));
    assert(!api.isVisionCapable('qwen2.5-coder:7b', ['llama']));
    assert(!api.isVisionCapable('llama3.2:3b', []));
  });
  await test('Modellwahl: isCoderModelName erkennt gängige Code-Modelle', () => {
    ['qwen2.5-coder:7b', 'codellama:13b', 'deepseek-coder-v2', 'starcoder2:3b'].forEach(n => assert(api.isCoderModelName(n), n));
    ['llama3.2:3b', 'llava:7b', 'gemma2:2b'].forEach(n => assert(!api.isCoderModelName(n), n));
  });
  await test('Modellwahl: pickModelFor wählt passendes Modell und wechselt nicht unnötig', () => {
    const names = ['gemma2:2b', 'llava:7b', 'qwen2.5-coder:7b', 'llama3.2:3b'];
    const info = { 'llava:7b': { families: ['clip'] } };
    assert.strictEqual(api.pickModelFor('vision', names, info, 'gemma2:2b'), 'llava:7b');
    assert.strictEqual(api.pickModelFor('vision', names, info, 'llava:7b'), null, 'schon bild-fähig, kein Wechsel');
    assert.strictEqual(api.pickModelFor('coder', names, info, 'gemma2:2b'), 'qwen2.5-coder:7b');
    assert.strictEqual(api.pickModelFor('vision', ['gemma2:2b'], {}, 'gemma2:2b'), null, 'kein Bild-Modell installiert');
    assert.strictEqual(api.pickModelFor(null, names, info, 'gemma2:2b'), null);
  });

  await test('Streaming: updateLive hängt nur Text an, volles Rendering erst in finishLive', () => {
    const live = script.slice(script.indexOf('function updateLive()'), script.indexOf('function finishLive('));
    assert(live.length > 50, 'updateLive nicht gefunden');
    assert(!/outerHTML|innerHTML|renderMarkdown|highlight\(/.test(live), 'updateLive rendert wieder komplett neu');
    assert(/appendData/.test(script), 'Text wird nicht angehängt');
    const fin = script.slice(script.indexOf('function finishLive('), script.indexOf('function renderChatList('));
    assert(/msgHtml\(/.test(fin), 'finishLive rendert die fertige Nachricht nicht');
    assert(/finishLive\(chat\)/.test(script), 'run() ruft finishLive nicht auf');
  });

  await test('Tastatur: fitViewport berechnet den sichtbaren Bereich', () => {
    const j = o => JSON.stringify(o);
    assert.strictEqual(j(api.fitViewport({ height: 664, offsetTop: 0, scale: 1 }, 664)), j({ height: 664, top: 0, bottom: 0, keyboard: false }));
    assert.strictEqual(j(api.fitViewport({ height: 350, offsetTop: 0, scale: 1 }, 664)), j({ height: 350, top: 0, bottom: 314, keyboard: true }));
    assert.strictEqual(j(api.fitViewport({ height: 350.4, offsetTop: 120.2, scale: 1 }, 664)), j({ height: 350, top: 120, bottom: 194, keyboard: true }));
    assert.strictEqual(api.fitViewport({ height: 620, offsetTop: 0, scale: 1 }, 664).keyboard, false, 'Adressleiste ist keine Tastatur');
    assert.strictEqual(api.fitViewport({ height: 350, offsetTop: -5, scale: 1 }, 664).top, 0, 'negativer Versatz wird 0');
    assert.strictEqual(api.fitViewport({ height: 400, offsetTop: 0 }, 400).keyboard, false, 'scale fehlt = 1');
  });
  await test('Tastatur: fitViewport meldet null bei Zoom, fehlender oder kaputter API', () => {
    assert.strictEqual(api.fitViewport(null, 600), null);
    assert.strictEqual(api.fitViewport(undefined, 600), null);
    assert.strictEqual(api.fitViewport({ height: 300, offsetTop: 0, scale: 2 }, 600), null, 'Pinch-Zoom');
    assert.strictEqual(api.fitViewport({ height: 0, offsetTop: 0, scale: 1 }, 600), null);
    assert.strictEqual(api.fitViewport({ height: NaN, offsetTop: 0, scale: 1 }, 600), null);
    const r = api.fitViewport({ height: 300, offsetTop: 0, scale: 1 }, NaN);
    assert(r && r.bottom === 0 && r.keyboard === false, 'unbekannte Fensterhöhe darf nichts kaputt machen');
  });
  await test('Tastatur: CSS und Verdrahtung vorhanden', () => {
    assert(/:root\.vv #app\{height:var\(--vvh\);transform:translateY\(var\(--vvt\)\)\}/.test(cssSrc), 'App-Regel fehlt');
    assert(/:root\.kb\{--sab:0px\}/.test(cssSrc), 'Safe-Area-Regel fehlt');
    assert(/:root\.vv #drawer/.test(cssSrc), 'Seitenleiste fehlt');
    assert(/--vvb/.test(cssSrc) && /visualViewport\.addEventListener\('resize'/.test(script) && /visualViewport\.addEventListener\('scroll'/.test(script));
    assert(/#app\{position:fixed/.test(cssSrc), '#app muss fest positioniert sein');
  });

  // Mock-Ollama: Streaming über echten HTTP-Server, Chunks mitten in Zeilen getrennt
  await test('Mock-Ollama: /api/tags und /api/chat-Stream', async () => {
    const server = http.createServer((req, res) => {
      res.setHeader('Access-Control-Allow-Origin', '*');
      if(req.url === '/api/tags'){ res.end(JSON.stringify({ models: [{ name: 'b:1' }, { name: 'a:2' }] })); return; }
      if(req.url === '/api/chat'){
        let body = '';
        req.on('data', d => body += d);
        req.on('end', () => {
          const j = JSON.parse(body);
          assert.strictEqual(j.stream, true);
          const lines = ['Hal', 'lo', ' Welt'].map(t => JSON.stringify({ message: { role: 'assistant', content: t }, done: false }) + '\n')
            .concat(JSON.stringify({ done: true }) + '\n').join('');
          res.write(lines.slice(0, 30));
          setTimeout(() => { res.write(lines.slice(30)); res.end(); }, 20);
        });
        return;
      }
      res.statusCode = 404; res.end();
    });
    await new Promise(r => server.listen(0, '127.0.0.1', r));
    const base = 'http://127.0.0.1:' + server.address().port;
    const tags = await (await fetch(base + '/api/tags')).json();
    assert.deepStrictEqual(tags.models.map(m => m.name).sort(), ['a:2', 'b:1']);
    const res = await fetch(base + '/api/chat', { method: 'POST', body: JSON.stringify({ model: 'a:2', messages: [], stream: true }) });
    let text = '';
    const p = api.createNdjsonParser(o => { if(o.message && o.message.content) text += o.message.content; });
    const dec = new TextDecoder();
    for await (const chunk of res.body) p.push(dec.decode(chunk, { stream: true }));
    p.end();
    server.close();
    assert.strictEqual(text, 'Hallo Welt');
  });


  await test('Projekte: buildSystem verbindet Systemprompt und Projektanweisungen', () => {
    assert.strictEqual(api.buildSystem(' A ', null), 'A');
    assert.strictEqual(api.buildSystem('', { name: 'P', instructions: ' Sei kurz ' }), 'Projekt "P":\nSei kurz');
    assert.strictEqual(api.buildSystem('A', { name: 'P', instructions: '' }), 'A');
    assert.strictEqual(api.buildSystem('', null), '');
  });
  await test('Artefakte: Dateiendung und Titel', () => {
    assert.strictEqual(api.artifactExt('Python'), 'py');
    assert.strictEqual(api.artifactExt('html'), 'html');
    assert.strictEqual(api.artifactExt('unbekannt'), 'txt');
    assert.strictEqual(api.artifactTitle('\n\n  def foo():\n  pass', 'py'), 'py: def foo():');
    assert.strictEqual(api.artifactTitle('', ''), 'Artefakt');
    assert(api.artifactTitle('x'.repeat(200), '').length <= 40);
  });
  await test('Artefakte: Codeblock hat Artefakt- und Kopieren-Knopf', () => {
    const h = api.renderMarkdown('```js\nlet a = 1;\n```');
    assert(h.includes('data-art') && h.includes('data-copy'), h);
  });
  await test('Neonglow: CSS enthaelt Glas, Hover und Electric Border', () => {
    assert(/backdrop-filter:var\(--blur\)/.test(cssSrc), 'Glas');
    assert(cssSrc.includes('@property --eb') && cssSrc.includes('conic-gradient(from var(--eb)'), 'Electric Border');
    assert(cssSrc.includes('@media (hover:hover)') && cssSrc.includes(':hover::before'), 'Hover');
  });
  await test('Dropdown: Listeneintraege haben deckenden Hintergrund (Windows: sonst weiss auf weiss)', () => {
    const m = cssSrc.match(/select option[^{]*\{([^}]*)\}/g) || [];
    const rule = m.find(r => /background-color:\s*#[0-9a-f]{6}\b/i.test(r) && /color:\s*#[0-9a-f]{6}\b/i.test(r));
    assert(rule, 'deckende option-Regel fehlt');
    assert(!/#model option\{background:var\(--surface\)/.test(cssSrc.split('Dropdown-Listen')[1] || ''), 'keine transparente Variable');
  });
  await test('7-Segment: Ziffern schalten die richtigen Segmente', () => {
    const on = ch => (api.segDigit(ch).match(/class="s on" d="([^"]+)"/g) || []).length;
    const expected = { '0': 6, '1': 2, '2': 5, '3': 5, '4': 4, '5': 5, '6': 6, '7': 3, '8': 7, '9': 6, '-': 1, ' ': 0 };
    for(const k of Object.keys(expected)) assert.strictEqual(on(k), expected[k], 'Ziffer ' + k);
    assert.strictEqual((api.segDigit('8').match(/<path/g) || []).length, 7, 'immer 7 Segmente');
    assert.strictEqual(on('x'), 0, 'unbekanntes Zeichen bleibt dunkel');
  });
  await test('7-Segment: formatTokens fuellt links auf, kappt und faengt Unsinn ab', () => {
    assert.strictEqual(api.formatTokens(42, 6), '    42');
    assert.strictEqual(api.formatTokens(0, 6), '     0');
    assert.strictEqual(api.formatTokens(1234567, 6), '999999');
    assert.strictEqual(api.formatTokens(-5, 4), '   0');
    assert.strictEqual(api.formatTokens('abc', 4), '   0');
    assert.strictEqual(api.formatTokens(12.9, 4), '  12');
    assert.strictEqual((api.sevenSegHtml(305, 6).match(/<svg/g) || []).length, 6);
  });
  await test('Token-Verbrauch: addUsage nimmt exakte Zahlen und summiert pro Chat', () => {
    let t = api.addUsage(undefined, { prompt_eval_count: 120, eval_count: 80 });
    assert.deepStrictEqual({ ...t }, { in: 120, out: 80, sum: 200 });
    t = api.addUsage(t, { prompt_eval_count: 300, eval_count: 50 });
    assert.deepStrictEqual({ ...t }, { in: 300, out: 50, sum: 550 });
    const est = api.addUsage(t, { eval_count: 7 });             // Abbruch: nur Schaetzung der Antwort
    assert.deepStrictEqual({ ...est }, { in: 300, out: 7, sum: 557 });
    assert.deepStrictEqual({ ...api.addUsage(null, null) }, { in: 0, out: 0, sum: 0 });
  });
  await test('Token-Verbrauch: tokensView zaehlt waehrend des Streamens live mit', () => {
    const tok = { in: 300, out: 50, sum: 550 };
    assert.deepStrictEqual({ ...api.tokensView(tok, null) }, { in: 300, out: 50, sum: 550 });
    assert.deepStrictEqual({ ...api.tokensView(tok, 12) }, { in: 300, out: 12, sum: 562 });
    assert.deepStrictEqual({ ...api.tokensView(undefined, 0) }, { in: 0, out: 0, sum: 0 });
    assert(/Anfrage 300.*Antwort 50.*Summe im Chat 550/.test(api.tokensAria(api.tokensView(tok, null))));
  });
  await test('Kontextwarnung: contextState erkennt volles Fenster', () => {
    const lv = (i, o, c) => api.contextState({ in: i, out: o }, c).level;
    assert.strictEqual(lv(100, 50, 0), 'unknown', 'Fenster unbekannt');
    assert.strictEqual(lv(0, 0, 4096), 'unknown', 'noch nichts gesendet');
    assert.strictEqual(lv(1000, 500, 4096), 'ok');
    assert.strictEqual(lv(3000, 600, 4096), 'warn');
    assert.strictEqual(lv(4090, 6, 4096), 'full', 'Anfrage fuellt das Fenster (Ollama meldet gekappte Zahl)');
    assert.strictEqual(lv(2000, 2100, 4096), 'full', 'Anfrage plus Antwort ueberschreiten');
    assert.strictEqual(api.contextState({ in: 3000, out: 600 }, 4096).pct, 88);
  });
  await test('Token-Anzeige: Verdrahtung (HTML, Zaehlung in run(), CSS)', () => {
    for(const id of ['tokbar', 'tokIn', 'tokOut', 'tokSum']) assert(htmlSrc.includes('id="' + id + '"'), id);
    assert(/usage = o/.test(script) && /addUsage\(chat\.tok, usage\)/.test(script), 'exakte Zahlen aus der letzten Zeile');
    assert(/paintTokens\(\);\s*\n\s*\}/.test(script.split('function render()')[1].split('Streaming:')[0]), 'render() zeichnet die Anzeige');
    assert(cssSrc.includes('.seg .s.on') && cssSrc.includes('.tokbar'), 'CSS');
    assert(/refreshCtxLimit\(\)\.then\(function\(\)\{ checkContext\(chat\)/.test(script), 'Kontextpruefung nach jeder Antwort');
    assert(cssSrc.includes('.tokgrp.full') && cssSrc.includes('.tokgrp.warn'), 'CSS Warnfarben');
    const iBar = htmlSrc.indexOf('id="tokbar"'), iHead = htmlSrc.indexOf('<header>'), iFoot = htmlSrc.indexOf('<footer>');
    assert(iBar > 0 && iBar < iHead && iHead < iFoot, 'Token-Anzeige steht ueber der Modellauswahl (vor <header>), nicht im Footer');
  });
  await test('Verdrahtung: jede getElementById-ID aus script.js existiert in ollama.html', () => {
    const ids = [...script.matchAll(/\$\('([A-Za-z0-9_]+)'\)/g)].map(m => m[1]);
    const missing = [...new Set(ids)].filter(id => !htmlSrc.includes('id="' + id + '"'));
    assert.deepStrictEqual(missing, []);
  });

  await test('Diktat: mergeDictation setzt Leerzeichen korrekt', () => {
    assert.strictEqual(api.mergeDictation('', ' hallo  welt '), 'hallo welt');
    assert.strictEqual(api.mergeDictation('Text', 'mehr'), 'Text mehr');
    assert.strictEqual(api.mergeDictation('Zeile\n', 'neu'), 'Zeile\nneu');
    assert.strictEqual(api.mergeDictation('Text', '   '), 'Text');
  });
  await test('Diktat: dictationSupport prueft API und sicheren Kontext', () => {
    class R {}
    assert.strictEqual(api.dictationSupport({}, true).ok, false);
    assert(/Firefox/.test(api.dictationSupport({}, true).reason));
    assert(/https/.test(api.dictationSupport({ webkitSpeechRecognition: R }, false).reason));
    const ok = api.dictationSupport({ webkitSpeechRecognition: R }, true);
    assert(ok.ok && ok.Ctor === R);
    assert(api.dictationSupport({ SpeechRecognition: R }, true).ok);
  });
  await test('Diktat: Fehlertexte und Sprachwahl', () => {
    assert(/Mikrofon-Zugriff/.test(api.dictationErrorText('not-allowed')));
    assert.strictEqual(api.dictationErrorText('aborted'), '');
    assert(/xyz/.test(api.dictationErrorText('xyz')));
    assert.strictEqual(api.dictationLang('auto', 'en-GB'), 'en-GB');
    assert.strictEqual(api.dictationLang('de-DE', 'en-GB'), 'de-DE');
    assert.strictEqual(api.dictationLang('', ''), 'de-DE');
  });
  await test('Diktat: Verdrahtung (Knopf, Sprachwahl, Abbruch beim Senden)', () => {
    assert(htmlSrc.includes('id="btnMic"') && htmlSrc.includes('id="dictLang"'));
    assert(/stopRec\(true\);\s*const input/.test(script), 'send() muss das Diktat hart beenden');
    assert(cssSrc.includes('#btnMic.rec'));
  });
  console.log('\n' + passed + ' Tests bestanden' + (process.exitCode ? ', es gibt Fehler.' : '.'));
})();
