"""Ce zice arbiterul cand modelul s-a oprit cu [] fara sa apeleze nimic: refuz legitim sau abandon?
T4 = actiune pentru care NU exista tool (WhatsApp). T12 = Kanban + Discord (nu exista).
"""
import sys, os, json
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import bench

TOOLS = [t["function"]["name"] for t in bench.SMALL]
print("tool-uri reale in conditia SMALL:", TOOLS)

T4 = "Trimite mesajul 'salut' pe WhatsApp la numarul 0740000000."
T12 = "Creeaza un card in Kanban pe coloana 'de facut' si anunta pe Discord."

for tag, cerere in [("T4_whatsapp", T4), ("T12_kanban_discord", T12)]:
    st = {"cerere": cerere, "rezultate_tooluri": ["(niciun tool apelat)"],
          "ultimul_rezultat": "(niciunul)", "output_model": "``` [] ```",
          "tooluri_disponibile": TOOLS}
    a = bench.arbiter(st)
    print(f"\n--- {tag}: {cerere}")
    for k, v in (a or {}).items():
        print("   ", k, "=", json.dumps(v, ensure_ascii=False))
