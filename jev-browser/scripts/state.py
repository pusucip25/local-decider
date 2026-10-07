"""Verificarea independenta a succesului: citeste DOM-ul real al paginii, nu ce zice agentul."""
import json, sys, urllib.request
from websocket import create_connection

def pages():
    return json.load(urllib.request.urlopen('http://127.0.0.1:9222/json/list', timeout=5))

def state(url_part='form.html'):
    tgt = [p for p in pages() if p.get('type') == 'page']
    t = next((p for p in tgt if url_part in p.get('url', '')), tgt[0])
    ws = create_connection(t['webSocketDebuggerUrl'], timeout=10, suppress_origin=True)
    expr = ("JSON.stringify({result:((document.querySelector('#result')||{}).textContent||''),"
            "display:(document.querySelector('#result')?getComputedStyle(document.querySelector('#result')).display:'-'),"
            "fields:[...document.querySelectorAll('input,select,textarea')].map(e=>[e.id,e.value,e.checked])})")
    ws.send(json.dumps({"id": 1, "method": "Runtime.evaluate",
                        "params": {"expression": expr, "returnByValue": True}}))
    while True:
        m = json.loads(ws.recv())
        if m.get('id') == 1:
            break
    ws.close()
    return json.loads(m['result']['result']['value'])

if __name__ == '__main__':
    s = state()
    print('DOM #result :', repr(s['result']))
    print('DOM campuri :', s['fields'])
    ok = s['result'].startswith('SUBMITTED')
    print('VERDICT     :', 'SUCCES' if ok else 'EȘEC')
    sys.exit(0 if ok else 1)
