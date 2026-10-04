/* Pandora AI System – Ollama-Simulator
 *
 * Wird vor script.js in die eingebettete Chat-App (ollama.html) gesetzt und ersetzt window.fetch für
 * die drei Ollama-Endpunkte /api/tags, /api/ps und /api/chat. Es läuft kein Ollama und es geht nichts
 * ins Netz: Antworten kommen aus kleinen Vorlagen und werden Stück für Stück gestreamt, damit
 * Token-Anzeige, Abbrechen und Kontextwarnung genauso reagieren wie mit einem echten Modell.
 */
(function () {
  'use strict';

  var MODELS = [
    { name: 'qwen2.5-coder:7b', model: 'qwen2.5-coder:7b', details: { families: ['qwen2'], parameter_size: '7.6B' } },
    { name: 'llama3.2:3b', model: 'llama3.2:3b', details: { families: ['llama'], parameter_size: '3.2B' } },
    { name: 'gemma3:4b', model: 'gemma3:4b', details: { families: ['gemma3'], parameter_size: '4B' } }
  ];
  var CTX = 4096;

  // Beim ersten Besuch gleich das Code-Modell wählen und eine Demo-Adresse eintragen (eigene Einstellungen bleiben unangetastet).
  try {
    if (!localStorage.getItem('ollamaMobile.v1')) {
      localStorage.setItem('ollamaMobile.v1', JSON.stringify({ url: 'http://localhost:11434', model: MODELS[0].name }));
    }
  } catch (e) { /* Speicher gesperrt: die App wählt dann selbst ein Modell */ }
  var realFetch = window.fetch ? window.fetch.bind(window) : null;

  function jsonResponse(obj, status) {
    return new Response(JSON.stringify(obj), { status: status || 200, headers: { 'Content-Type': 'application/json' } });
  }

  function pathOf(input) {
    var url = typeof input === 'string' ? input : (input && input.url) || '';
    return url.replace(/^[a-z]+:\/\/[^/]+/i, '').split('?')[0];
  }

  /* ---------- Antwortvorlagen (Markdown) ---------- */
  var REPLIES = {
    hallo:
      'Hallo! Ich bin ein **simulierter** Assistent. Hier läuft kein echtes Modell, aber die Oberfläche ist die echte Pandora-Chat-App.\n\n' +
      'Probier aus:\n\n- die **Token-Anzeige** oben (IN, OUT, Σ) zählt live mit\n- **Abbrechen** mit dem Stopp-Knopf während der Antwort\n- die **Kontextwarnung** über den Knopf „Kontextwarnung zeigen“\n\n' +
      'Mit einem echten Ollama sind Antworten und Zahlen echt.',
    python:
      'Hier eine kleine Funktion, die Dateien einer Liste der Größe nach sortiert:\n\n' +
      '```python\nfrom pathlib import Path\n\n\ndef dateien_nach_groesse(ordner: str, anzahl: int = 5):\n    """Gibt die größten Dateien eines Ordners zurück."""\n    dateien = [p for p in Path(ordner).rglob("*") if p.is_file()]\n    dateien.sort(key=lambda p: p.stat().st_size, reverse=True)\n    return [(p.name, p.stat().st_size) for p in dateien[:anzahl]]\n\n\nif __name__ == "__main__":\n    for name, groesse in dateien_nach_groesse("."):\n        print(f"{groesse:>10}  {name}")\n```\n\n' +
      'Die Funktion nutzt nur die Standardbibliothek. Soll ich Fehlerbehandlung für fehlende Rechte ergänzen?',
    html:
      'Eine minimale Seite mit dunklem Design:\n\n' +
      '```html\n<!DOCTYPE html>\n<html lang="de">\n<head>\n  <meta charset="UTF-8">\n  <meta name="viewport" content="width=device-width, initial-scale=1">\n  <title>Hallo Pandora</title>\n  <style>\n    body { margin: 0; display: grid; place-items: center; min-height: 100vh;\n           background: #070913; color: #e8f3ff; font-family: system-ui, sans-serif; }\n    h1 { text-shadow: 0 0 18px #22e4ff; }\n  </style>\n</head>\n<body>\n  <h1>Hallo Pandora</h1>\n</body>\n</html>\n```\n\n' +
      'Speichere den Code als `index.html` und öffne ihn im Browser. Mit dem **Mini Webserver** siehst du ihn auch am Handy.',
    token:
      'Die Anzeige oben zeigt den Verbrauch des aktuellen Chats:\n\n' +
      '- **IN**: Tokens der letzten Anfrage (Verlauf, System-Prompt, Dateien)\n- **OUT**: Tokens der letzten Antwort, live mitgezählt\n- **Σ**: Summe aller Anfragen in diesem Chat\n\n' +
      'Ist das Kontextfenster fast voll, wird **IN** gelb, bei vollem Fenster rot. Dann kappt Ollama den Verlauf und das Modell verliert den Bezug.',
    standard:
      'Das ist eine **simulierte** Antwort. In der Demo gibt es kein echtes Sprachmodell, aber du kannst die Oberfläche in Ruhe testen.\n\n' +
      'Versuche es mit „Hallo“, „Python-Funktion“, „HTML-Seite“ oder „Token-Anzeige“. Für echte Antworten brauchst du Ollama und den Mini Webserver.'
  };

  function pickReply(text) {
    var t = (text || '').toLowerCase();
    if (/kontextwarnung|kontext voll/.test(t)) return { key: 'warn', text: 'Das Kontextfenster ist in dieser Demo **künstlich voll** gemeldet: Die Anfrage zählt über 4000 Tokens. Achte auf die rote, pulsierende **IN**-Anzeige oben und den Hinweis. Mit echtem Ollama passiert das bei langen Gesprächen oder großen Dateien.' };
    if (/\b(hallo|hi|hey|moin|servus)\b/.test(t)) return { key: 'hallo', text: REPLIES.hallo };
    if (/python|funktion|skript|script/.test(t)) return { key: 'python', text: REPLIES.python };
    if (/html|seite|webseite|css/.test(t)) return { key: 'html', text: REPLIES.html };
    if (/token|kontext|anzeige|verbrauch/.test(t)) return { key: 'token', text: REPLIES.token };
    return { key: 'standard', text: REPLIES.standard };
  }

  // Grobe Schätzung: etwa 4 Zeichen pro Token.
  function estTokens(s) { return Math.max(1, Math.round(String(s || '').length / 4)); }

  // Text in Stücke zerlegen, die etwa einem Token entsprechen (Wortgrenzen bleiben erhalten).
  function chunk(text) {
    var out = [], re = /\s*\S{1,4}|\s+/g, m;
    while ((m = re.exec(text)) !== null) out.push(m[0]);
    return out;
  }

  function abortError() {
    var e = new Error('Aborted'); e.name = 'AbortError'; return e;
  }

  function streamChat(init) {
    var body = {};
    try { body = JSON.parse((init && init.body) || '{}'); } catch (e) { body = {}; }
    var msgs = body.messages || [];
    var lastUser = '';
    for (var i = msgs.length - 1; i >= 0; i--) { if (msgs[i].role === 'user') { lastUser = msgs[i].content || ''; break; } }
    var reply = pickReply(lastUser);
    var parts = chunk(reply.text);
    var promptTokens = msgs.reduce(function (n, m) { return n + estTokens(m.content) + 4; }, 0);
    if (reply.key === 'warn') promptTokens = 4050;
    var signal = init && init.signal;
    var enc = new TextEncoder();
    var idx = 0, timer = null, closed = false;

    var stream = new ReadableStream({
      start: function (controller) {
        function finish(err) {
          if (closed) return; closed = true; clearTimeout(timer);
          if (err) controller.error(err); else controller.close();
        }
        if (signal) {
          if (signal.aborted) { finish(abortError()); return; }
          signal.addEventListener('abort', function () { finish(abortError()); });
        }
        function tick() {
          if (closed) return;
          if (idx < parts.length) {
            controller.enqueue(enc.encode(JSON.stringify({ model: body.model || MODELS[0].name, message: { role: 'assistant', content: parts[idx++] }, done: false }) + '\n'));
            timer = setTimeout(tick, 22);
          } else {
            controller.enqueue(enc.encode(JSON.stringify({
              model: body.model || MODELS[0].name, message: { role: 'assistant', content: '' }, done: true, done_reason: 'stop',
              prompt_eval_count: promptTokens, eval_count: parts.length
            }) + '\n'));
            finish();
          }
        }
        timer = setTimeout(tick, 350);   // kurze „Denkpause“ vor dem ersten Stück
      },
      cancel: function () { closed = true; clearTimeout(timer); }
    });
    return new Response(stream, { status: 200, headers: { 'Content-Type': 'application/x-ndjson' } });
  }

  window.fetch = function (input, init) {
    var p = pathOf(input);
    if (p === '/api/tags') return Promise.resolve(jsonResponse({ models: MODELS }));
    if (p === '/api/ps') return Promise.resolve(jsonResponse({ models: [{ name: MODELS[0].name, model: MODELS[0].name, context_length: CTX }] }));
    if (p === '/api/chat') return Promise.resolve(streamChat(init));
    if (realFetch) return realFetch(input, init);
    return Promise.reject(new Error('Kein Netzwerk in der Demo'));
  };

  /* Steuerung von außen (Beispiel-Knöpfe der Landingpage): postMessage({type:'pandora-demo-send', text:'…'}) */
  window.addEventListener('message', function (ev) {
    var d = ev.data;
    if (!d || d.type !== 'pandora-demo-send' || typeof d.text !== 'string') return;
    var input = document.getElementById('input'), send = document.getElementById('send');
    if (!input || !send) return;
    if (send.classList.contains('stop')) { send.click(); }        // laufende Antwort zuerst abbrechen
    setTimeout(function () {
      input.value = d.text;
      input.dispatchEvent(new Event('input', { bubbles: true }));
      send.click();
    }, 60);
  });

  window.__PANDORA_DEMO__ = { models: MODELS, ctx: CTX, pickReply: pickReply, estTokens: estTokens, chunk: chunk };
})();
